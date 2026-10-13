"""Bounded public HTTP collection, with pinned DNS and no ambient credentials."""

import asyncio
import http.client
import json
import socket
import ssl
import subprocess
import sys
import threading
import time
import uuid
import zlib
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

from .contracts import ContractError, digest, normalize_url, public_address, utcnow
from .extraction import extract

USER_AGENT = "Pramana/0.1"
HEADERS = {"content-type", "content-encoding", "location", "retry-after", "content-length"}


class FetchError(Exception):
    def __init__(self, outcome, detail=None):
        super().__init__(outcome)
        self.outcome = outcome
        self.detail = detail


@dataclass
class Response:
    status: int
    headers: dict
    body: bytes
    address: str = "synthetic"
    truncated: bool = False
    observed_bytes: int | None = None


def bounded_resolve(host, port, timeout):
    # A subprocess gives libc resolution a real deadline and can be terminated;
    # abandoning a resolver thread would exhaust a bounded worker pool.
    script = "import json,socket,sys; print(json.dumps(socket.getaddrinfo(sys.argv[1], int(sys.argv[2]), type=socket.SOCK_STREAM)))"
    try:
        result = subprocess.run(
            [sys.executable, "-c", script, host, str(port)],
            capture_output=True,
            timeout=timeout,
            check=True,
            text=True,
        )
        return [(a, b, c, d, tuple(e)) for a, b, c, d, e in json.loads(result.stdout)]
    except subprocess.TimeoutExpired as exc:
        raise FetchError("dns_timeout") from exc
    except (subprocess.CalledProcessError, ValueError) as exc:
        raise FetchError("dns_failure") from exc


class PublicHTTP:
    """A new DNS lookup and pinned connection for every request, including robots.

    Blocking I/O runs in a bounded worker executor. DNS uses a deadline-bounded
    subprocess; a socket watchdog bounds headers and slow response streams.
    No proxies, cookies, authorization headers or automatic redirects are used.
    """

    def __init__(self, resolver=None):
        self.resolver = resolver

    def request(self, url, timeout, cap):
        parsed = urlsplit(normalize_url(url))
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        deadline = time.monotonic() + timeout
        addresses = (
            self.resolver(parsed.hostname, port, type=socket.SOCK_STREAM)
            if self.resolver
            else bounded_resolve(parsed.hostname, port, timeout)
        )
        if not addresses or any(not public_address(a[4][0]) for a in addresses):
            raise FetchError("nonpublic_destination")
        family, socktype, proto, _, sockaddr = addresses[0]
        raw = socket.socket(family, socktype, proto)
        connection = None
        response = None

        def expire():
            try:
                raw.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            raw.close()

        watchdog = threading.Timer(max(0.001, deadline - time.monotonic()), expire)
        watchdog.daemon = True
        watchdog.start()
        try:
            raw.settimeout(max(0.001, deadline - time.monotonic()))
            raw.connect(sockaddr)
            if not public_address(raw.getpeername()[0]) or raw.getpeername()[0] != sockaddr[0]:
                raise FetchError("destination_changed")
            if parsed.scheme == "https":
                raw = ssl.create_default_context().wrap_socket(raw, server_hostname=parsed.hostname)
            connection = http.client.HTTPConnection(parsed.hostname, port, timeout=timeout)
            connection.sock = raw
            path = parsed.path + ("?" + parsed.query if parsed.query else "")
            connection.request(
                "GET",
                path,
                headers={
                    "Host": parsed.netloc,
                    "User-Agent": USER_AGENT,
                    "Accept": "text/html,text/plain;q=0.8",
                    "Accept-Encoding": "gzip",
                    "Connection": "close",
                },
            )
            response = connection.getresponse()
            headers = {k.lower(): v for k, v in response.getheaders() if k.lower() in HEADERS}
            encoding = headers.get("content-encoding", "identity").lower()
            if encoding not in ("identity", "gzip"):
                raise FetchError("unsupported_encoding")
            decoder = zlib.decompressobj(16 + zlib.MAX_WBITS) if encoding == "gzip" else None
            output, observed, truncated = bytearray(), 0, False
            while True:
                # HTTPResponse closes its file at the end of a length-delimited
                # body. With Connection: close, that also closes the socket.
                # Check completion before updating that socket's timeout.
                if response.isclosed():
                    if decoder and not decoder.eof:
                        raise FetchError("invalid_compression")
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise FetchError("timeout")
                raw.settimeout(remaining)
                block = response.read1(min(16384, cap + 1 - len(output)))
                if not block:
                    if decoder and not decoder.eof:
                        raise FetchError("invalid_compression")
                    break
                observed += len(block)
                decoded = decoder.decompress(block, cap + 1 - len(output)) if decoder else block
                output.extend(decoded)
                if len(output) > cap or (decoder and decoder.unconsumed_tail):
                    truncated = True
                    del output[cap:]
                    break
                if observed > cap * 2:
                    truncated = True
                    break
            return Response(
                response.status, headers, bytes(output), sockaddr[0], truncated, observed
            )
        except ssl.SSLCertVerificationError as exc:
            raise FetchError(
                "tls_validation_failed",
                {"verify_code": exc.verify_code, "verify_message": exc.verify_message},
            ) from exc
        except TimeoutError as exc:
            raise FetchError("timeout") from exc
        except socket.gaierror as exc:
            raise FetchError("dns_failure") from exc
        except (OSError, http.client.HTTPException, zlib.error) as exc:
            raise FetchError("connection_failure") from exc
        finally:
            watchdog.cancel()
            if response is not None:
                response.close()
            if connection:
                connection.close()
            raw.close()


def challenge(body):
    """Conservative diagnostic signature; never an identity verdict or bypass."""
    raw = body.lower()
    return b"<html" in raw and (b"/cdn-cgi/challenge-platform/" in raw or b"_cf_chl_opt" in raw)


class AttemptLog(list):
    def __init__(self, observer=None):
        super().__init__()
        self.observer = observer

    async def emit(self, phase, attempt):
        if self.observer is not None:
            await self.observer(phase, dict(attempt))

    async def record(self, attempt):
        self.append(attempt)
        await self.emit("finished", attempt)


class Collector:
    def __init__(self, artifacts, policy, transport=None, concurrency=8):
        self.artifacts = artifacts
        self.policy = policy
        self.transport = transport or PublicHTTP()
        self.semaphore = asyncio.Semaphore(concurrency)
        self.origins = {}  # Only currently active origins; pruned after each target.

    def _expire_origin(self, origin, state):
        if self.origins.get(origin) is not state or state["users"]:
            return
        remaining = state["next"] - time.monotonic()
        if remaining > 0:
            state["timer"] = asyncio.get_running_loop().call_later(
                remaining, self._expire_origin, origin, state
            )
        else:
            del self.origins[origin]

    async def request(self, url, deadline, attempts, purpose, network_budget=None):
        if network_budget is not None and network_budget[0] <= 0:
            raise FetchError("time_budget_exhausted")
        origin = urlsplit(url).netloc
        # A reference count prevents pruning a lock still used by another target.
        state = self.origins.setdefault(
            origin,
            {
                "lock": asyncio.Lock(),
                "next": 0,
                "last": 0,
                "users": 0,
                "interval": self.policy["origin_interval"],
                "timer": None,
            },
        )
        if state["timer"]:
            state["timer"].cancel()
            state["timer"] = None
        state["users"] += 1
        try:
            async with state["lock"]:
                delay = max(0, state["next"] - time.monotonic())
                if time.monotonic() + delay >= deadline:
                    raise FetchError("time_budget_exhausted")
                await asyncio.sleep(delay)
                async with self.semaphore:
                    remaining = deadline - time.monotonic()
                    if network_budget is not None:
                        remaining = min(remaining, network_budget[0])
                    if remaining <= 0:
                        raise FetchError("time_budget_exhausted")
                    start = time.monotonic()
                    state["last"] = start
                    state["next"] = start + state["interval"]
                    attempt = {
                        "fetch_attempt_id": uuid.uuid4().hex,
                        "url": url,
                        "purpose": purpose,
                        "started_at": utcnow(),
                        "network_phase_timings": None,
                        "missing_timing_reason": "transport_does_not_expose_phases",
                    }
                    await attempts.emit("intent", attempt)
                    try:
                        response = await asyncio.to_thread(
                            self.transport.request, url, remaining, self.policy["body_bytes"]
                        )
                        attempt.update(
                            status=response.status,
                            destination=response.address,
                            headers=response.headers,
                            decoded_bytes=len(response.body),
                            observed_bytes=response.observed_bytes,
                            outcome="response",
                            truncated=response.truncated,
                        )
                        return response
                    except FetchError as exc:
                        attempt["outcome"] = exc.outcome
                        if self.policy["version"] == "collector-v4" and exc.detail is not None:
                            attempt["detail"] = exc.detail
                        raise
                    finally:
                        elapsed = time.monotonic() - start
                        if network_budget is not None:
                            network_budget[0] -= elapsed
                        attempt["duration_ms"] = elapsed * 1000
                        attempt.setdefault("outcome", "interrupted")
                        await attempts.record(attempt)
        finally:
            state["users"] -= 1
            # Retain only cooling/active origins without delaying the completed request.
            if not state["users"]:
                state["timer"] = asyncio.get_running_loop().call_later(
                    max(0, state["next"] - time.monotonic()), self._expire_origin, origin, state
                )

    async def robots(self, url, deadline, attempts, cache, network_budget=None):
        p = urlsplit(url)
        origin = f"{p.scheme}://{p.netloc}"
        if origin not in cache:
            robot_url = origin + "/robots.txt"
            seen = set()
            for hop in range(self.policy["redirects"] + 1):
                try:
                    robot_url = normalize_url(robot_url)
                except ContractError as exc:
                    raise FetchError("destination_policy_blocked") from exc
                if robot_url in seen:
                    raise FetchError("robots_redirect_loop")
                seen.add(robot_url)
                response = await self.request(
                    robot_url, deadline, attempts, "robots", network_budget
                )
                if response.status not in (301, 302, 303, 307, 308) or self.policy[
                    "version"
                ] not in ("collector-v3", "collector-v4"):
                    break
                if hop == self.policy["redirects"]:
                    raise FetchError("robots_redirect_limit")
                location = response.headers.get("location")
                if not location:
                    raise FetchError("robots_redirect_missing_location")
                robot_url = urljoin(robot_url, location)
            if response.status in (404, 410):
                cache[origin] = None
            elif response.status != 200 or response.truncated:
                if self.policy["version"] == "collector-v4" and challenge(response.body):
                    raise FetchError("robots_challenge_blocked")
                raise FetchError("robots_unavailable")
            else:
                parser = RobotFileParser()
                parser.parse(response.body.decode("utf-8", errors="replace").splitlines())
                cache[origin] = parser
        parser = cache[origin]
        if parser:
            if not parser.can_fetch(USER_AGENT, url):
                raise FetchError("robots_denied")
            delay = parser.crawl_delay(USER_AGENT)
            rate = parser.request_rate(USER_AGENT)
            interval = max(
                self.policy["origin_interval"],
                delay or 0,
                rate.seconds / rate.requests if rate else 0,
            )
            if interval > self.policy["origin_interval"] and self.policy["version"] not in (
                "collector-v3",
                "collector-v4",
            ):
                raise FetchError("robots_rate_deferred")
            if interval >= deadline - time.monotonic():
                raise FetchError("robots_rate_deferred")
            state = self.origins.get(p.netloc)
            if state:
                state["interval"] = max(state["interval"], interval)
                state["next"] = max(state["next"], state["last"] + interval)
            elif interval:
                # A cross-origin robots redirect may outlast the original cooldown.
                self.origins[p.netloc] = {
                    "lock": asyncio.Lock(),
                    "next": time.monotonic() + interval,
                    "last": time.monotonic(),
                    "users": 0,
                    "interval": interval,
                    "timer": None,
                }

    async def chain(self, url, deadline, attempts, robots_cache, allowed_host=None):
        seen = set()
        network_budget = None
        if self.policy["version"] == "collector-v4":
            # One shared active-work budget across robots, redirects and retries.
            # Required pacing waits consume only the outer target deadline.
            network_budget = [self.policy["chain_seconds"]]
        else:
            deadline = min(deadline, time.monotonic() + self.policy["chain_seconds"])
        for hop in range(self.policy["redirects"] + 1):
            try:
                url = normalize_url(url)
            except ContractError as exc:
                raise FetchError("destination_policy_blocked") from exc
            if allowed_host is not None and urlsplit(url).hostname != allowed_host:
                raise FetchError("secondary_origin_blocked")
            if url in seen:
                raise FetchError("redirect_loop")
            seen.add(url)
            await self.robots(url, deadline, attempts, robots_cache, network_budget)
            response = None
            for retry in range(self.policy["retries"] + 1):
                try:
                    response = await self.request(url, deadline, attempts, "page", network_budget)
                except FetchError as exc:
                    if (
                        exc.outcome not in ("timeout", "connection_failure", "dns_failure")
                        or retry == self.policy["retries"]
                    ):
                        raise
                    continue
                if response.status not in (429, 503) or retry == self.policy["retries"]:
                    break
                retry_after = response.headers.get("retry-after", "1")
                try:
                    delay = max(1.0, float(retry_after))
                except ValueError:
                    raise FetchError("retry_after_deferred") from None
                if not delay < deadline - time.monotonic():
                    raise FetchError("retry_after_deferred")
                await asyncio.sleep(delay)
            if response.status in (301, 302, 303, 307, 308):
                if hop == self.policy["redirects"]:
                    raise FetchError("redirect_limit")
                location = response.headers.get("location")
                if not location:
                    raise FetchError("redirect_missing_location")
                url = urljoin(url, location)
                continue
            return url, response
        raise FetchError("redirect_limit")

    async def collect(
        self, url, predecessor=None, supplemental=False, on_attempt=None, budget_seconds=None
    ):
        start = time.monotonic()
        observed = utcnow()
        deadline = start + (
            budget_seconds
            if budget_seconds is not None
            else (30 if supplemental else self.policy["target_seconds"])
        )
        pages, attempts, robots_cache, failures = [], AttemptLog(on_attempt), {}, []
        queue = [url]
        seen = set()
        char_budget = self.policy["bundle_chars"]
        logo_budget = self.policy["bundle_logos"]
        while queue and len(pages) < (1 if supplemental else self.policy["pages"]):
            requested = queue.pop(0)
            if requested in seen:
                continue
            seen.add(requested)
            try:
                allowed_host = (
                    urlsplit(pages[0]["final_url"]).hostname
                    if pages
                    else urlsplit(url).hostname
                    if supplemental
                    else None
                )
                final, response = await self.chain(
                    requested, deadline, attempts, robots_cache, allowed_host
                )
                if not 200 <= response.status < 300:
                    failures.append(
                        {
                            "url": requested,
                            "outcome": "page_challenge_blocked"
                            if self.policy["version"] == "collector-v4" and challenge(response.body)
                            else f"http_{response.status}",
                        }
                    )
                    continue
                body_hash = await asyncio.to_thread(self.artifacts.put, response.body)
                limits = {
                    **self.policy,
                    "page_chars": min(self.policy["page_chars"], char_budget),
                    "page_logos": min(self.policy["page_logos"], logo_budget),
                }
                page = await asyncio.to_thread(
                    extract, response.body, final, limits, response.headers.get("content-type", "")
                )
                if self.policy["version"] == "collector-v4" and not page["elements"]:
                    raw = response.body.lower()
                    outcome = (
                        "unsupported_media"
                        if page["unsupported_media"]
                        else "script_only_content"
                        if b"<script" in raw
                        else "empty_content"
                    )
                    indicators = ["suspected_parking_shell"] if b"parking-lander" in raw else []
                    failures.append(
                        {"url": requested, "outcome": outcome, "indicators": indicators}
                    )
                char_budget -= page["retained_characters"]
                logo_budget -= len(page["logos"])
                page.update(
                    body_hash=body_hash,
                    requested_url=requested,
                    fetch_truncated=response.truncated,
                    fetch_attempt_index=len(attempts) - 1,
                )
                pages.append(page)
                if len(pages) == 1 and not supplemental:
                    host = urlsplit(final).hostname
                    for category in ("about", "contact"):
                        candidates = sorted(
                            {
                                link["url"]
                                for link in page["links"]
                                if link["category"] == category
                                and urlsplit(link["url"]).hostname == host
                            }
                        )
                        if candidates:
                            queue.append(candidates[0])
            except FetchError as exc:
                failure = {"url": requested, "outcome": exc.outcome}
                if self.policy["version"] == "collector-v4" and exc.detail is not None:
                    failure["detail"] = exc.detail
                failures.append(failure)
        bundle = {
            "schema_version": "pramana.v1",
            "target_id": digest(url),
            "configuration_hash": digest(self.policy),
            "pages": pages,
            "attempts": attempts,
            "failures": failures,
            "observed_from": observed,
            "observed_to": utcnow(),
            "duration_ms": (time.monotonic() - start) * 1000,
            "outcome": "available" if pages else "unavailable",
            "predecessor_bundle_id": predecessor,
        }
        bundle["bundle_id"] = digest(bundle)
        return bundle


class SyntheticCollector:
    """Offline workflow fixture, never a real website observation."""

    def __init__(self, artifacts, policy):
        self.artifacts, self.policy = artifacts, policy
        self.calls = 0

    async def collect(
        self, url, predecessor=None, supplemental=False, on_attempt=None, budget_seconds=None
    ):
        self.calls += 1
        await asyncio.sleep(0.001)
        body = b"<html><title>Synthetic fixture</title><body><h1>Example Workshop</h1><p>Offline scheduling evidence only.</p></body></html>"
        page = extract(body, url, self.policy)
        page["body_hash"] = self.artifacts.put(body)
        value = {
            "schema_version": "pramana.v1",
            "target_id": digest(url),
            "configuration_hash": digest(self.policy),
            "pages": [page],
            "attempts": [],
            "failures": [],
            "observed_from": utcnow(),
            "observed_to": utcnow(),
            "outcome": "synthetic",
            "predecessor_bundle_id": predecessor,
        }
        value["bundle_id"] = digest(value)
        return value
