import tempfile
import unittest

from pramana.artifacts import ArtifactStore
from pramana.collection import Collector, FetchError, PublicHTTP, Response
from pramana.contracts import default_config


class FakeHTTP:
    def __init__(self, mapping):
        self.mapping, self.calls = mapping, []

    def request(self, url, timeout, cap):
        self.calls.append(url)
        if url.endswith("/robots.txt"):
            return self.mapping.get(url, Response(404, {}, b""))
        value = self.mapping[url]
        if isinstance(value, Exception):
            raise value
        return value


class CollectionTests(unittest.IsolatedAsyncioTestCase):
    def test_connection_close_response_retains_complete_body(self):
        import socket
        import threading
        from unittest.mock import patch

        body = b"<h1>Example Workshop</h1>"
        with socket.socket() as server:
            server.bind(("127.0.0.1", 0))
            server.listen(1)
            server.settimeout(3)

            def serve():
                conn, _ = server.accept()
                with conn:
                    conn.recv(8192)
                    conn.sendall(
                        b"HTTP/1.1 200 OK\r\nConnection: close\r\nContent-Length: "
                        + str(len(body)).encode()
                        + b"\r\nContent-Type: text/html\r\n\r\n"
                        + body
                    )

            worker = threading.Thread(target=serve, daemon=True)
            worker.start()

            def resolver(*args, **kwargs):
                return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", server.getsockname())]

            try:
                with patch("pramana.collection.public_address", return_value=True):
                    result = PublicHTTP(resolver).request("http://example.test/", 2, 1024)
                self.assertEqual(result.body, body)
                self.assertEqual(result.status, 200)
                self.assertFalse(result.truncated)
            finally:
                worker.join(timeout=3)

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.artifacts = ArtifactStore(self.temp.name)
        self.policy = {**default_config()["collection"], "origin_interval": 0}

    async def collect(self, mapping):
        transport = FakeHTTP(mapping)
        result = await Collector(self.artifacts, self.policy, transport).collect(
            "https://example.test/"
        )
        return result, transport

    async def test_redirect_loop_and_private_redirect(self):
        for target, reason in (
            ("https://example.test/", "redirect_loop"),
            ("http://127.0.0.1/", "destination_policy_blocked"),
        ):
            bundle, _ = await self.collect(
                {"https://example.test/": Response(302, {"location": target}, b"")}
            )
            self.assertEqual(bundle["outcome"], "unavailable")
            self.assertEqual(bundle["failures"][0]["outcome"], reason)

    async def test_robots_and_retry_after(self):
        bundle, http = await self.collect(
            {"https://example.test/robots.txt": Response(200, {}, b"User-agent: *\nDisallow: /\n")}
        )
        self.assertEqual(bundle["failures"][0]["outcome"], "robots_denied")
        self.assertEqual(len(http.calls), 1)
        bundle, _ = await self.collect(
            {"https://example.test/": Response(429, {"retry-after": "999"}, b"")}
        )
        self.assertEqual(bundle["failures"][0]["outcome"], "retry_after_deferred")

    async def test_secondary_discovery_is_bounded_and_same_host(self):
        bundle, http = await self.collect(
            {
                "https://example.test/": Response(
                    200,
                    {"content-type": "text/html"},
                    b'<title>Example</title><a href="/about">About</a><a href="https://elsewhere.test/contact">Contact</a>',
                ),
                "https://example.test/about": Response(
                    200, {"content-type": "text/html"}, b"<h1>About Example</h1>"
                ),
            }
        )
        self.assertEqual(len(bundle["pages"]), 2)
        self.assertFalse(any("elsewhere" in c for c in http.calls))
        self.assertEqual(len(bundle["attempts"]), 3)

    def test_dns_rebinding_private_answer_rejected_before_connect(self):
        def resolver(*args, **kwargs):
            return [(2, 1, 6, "", ("127.0.0.1", 443))]

        with self.assertRaises(FetchError) as caught:
            PublicHTTP(resolver).request("https://example.test/", 1, 1024)
        self.assertEqual(caught.exception.outcome, "nonpublic_destination")

    def test_compressed_body_is_bounded_before_allocation(self):
        import gzip
        from unittest.mock import MagicMock, patch

        compressed = gzip.compress(b"x" * 1_000_000)
        sock = MagicMock()
        sock.getpeername.return_value = ("8.8.8.8", 80)
        response = MagicMock()
        response.isclosed.return_value = False
        response.status = 200
        response.getheaders.return_value = [
            ("Content-Encoding", "gzip"),
            ("Content-Type", "text/html"),
        ]
        response.read1.side_effect = [compressed, b""]
        conn = MagicMock()
        conn.getresponse.return_value = response

        def resolver(*args, **kwargs):
            return [(2, 1, 6, "", ("8.8.8.8", 80))]

        with (
            patch("pramana.collection.socket.socket", return_value=sock),
            patch("pramana.collection.http.client.HTTPConnection", return_value=conn),
        ):
            result = PublicHTTP(resolver).request("http://example.test/", 1, 1024)
        self.assertEqual(len(result.body), 1024)
        self.assertTrue(result.truncated)
        self.assertEqual(sock.connect.call_args.args[0], ("8.8.8.8", 80))
        headers = conn.request.call_args.kwargs["headers"]
        self.assertNotIn("Authorization", headers)
        self.assertNotIn("Cookie", headers)

    def test_dns_deadline_is_a_terminal_failure(self):
        import subprocess
        from unittest.mock import patch

        with patch(
            "pramana.collection.subprocess.run",
            side_effect=subprocess.TimeoutExpired("resolver", 0.01),
        ):
            with self.assertRaises(FetchError) as caught:
                PublicHTTP().request("https://example.test/", 0.01, 1024)
        self.assertEqual(caught.exception.outcome, "dns_timeout")

    async def test_secondary_redirect_cannot_escape_homepage_host(self):
        bundle, http = await self.collect(
            {
                "https://example.test/": Response(
                    200, {"content-type": "text/html"}, b'<a href="/about">About</a>'
                ),
                "https://example.test/about": Response(
                    302, {"location": "https://elsewhere.test/about"}, b""
                ),
            }
        )
        self.assertEqual(bundle["failures"][0]["outcome"], "secondary_origin_blocked")
        self.assertFalse(any("elsewhere" in url for url in http.calls))

    async def test_fetch_intent_precedes_transport_and_completion_is_recorded(self):
        events = []
        transport = FakeHTTP(
            {
                "https://example.test/": Response(
                    200, {"content-type": "text/html"}, b"<h1>Example</h1>"
                )
            }
        )

        async def observe(phase, attempt):
            events.append((phase, attempt["fetch_attempt_id"], len(transport.calls)))

        await Collector(self.artifacts, self.policy, transport).collect(
            "https://example.test/", on_attempt=observe
        )
        self.assertEqual(
            [event[0] for event in events], ["intent", "finished", "intent", "finished"]
        )
        self.assertEqual(events[0][2], 0)
        self.assertEqual(events[1][2], 1)
        self.assertEqual(events[0][1], events[1][1])

    async def test_robots_redirect_is_followed_without_changing_page_target(self):
        bundle, http = await self.collect(
            {
                "https://example.test/robots.txt": Response(
                    302, {"location": "https://policy.test/rules"}, b""
                ),
                "https://policy.test/rules": Response(200, {}, b"User-agent: *\nAllow: /\n"),
                "https://example.test/": Response(
                    200, {"content-type": "text/html"}, b"<h1>Example</h1>"
                ),
            }
        )
        self.assertEqual(bundle["outcome"], "available")
        self.assertEqual(
            http.calls,
            [
                "https://example.test/robots.txt",
                "https://policy.test/rules",
                "https://example.test/",
            ],
        )

    async def test_crawl_delay_schedules_page_within_budget(self):
        import time

        starts = []

        class TimedHTTP(FakeHTTP):
            def request(self, *args):
                starts.append(time.monotonic())
                return super().request(*args)

        http = TimedHTTP(
            {
                "https://example.test/robots.txt": Response(
                    200, {}, b"User-agent: *\nCrawl-delay: 1\n"
                ),
                "https://example.test/": Response(
                    200, {"content-type": "text/html"}, b"<h1>Example</h1>"
                ),
            }
        )
        bundle = await Collector(self.artifacts, self.policy, http).collect(
            "https://example.test/", budget_seconds=3
        )
        self.assertEqual(bundle["outcome"], "available")
        self.assertGreaterEqual(starts[1] - starts[0], 0.99)

    async def test_robots_redirect_controls_and_legacy_policy(self):
        for target, outcome in (
            ("http://127.0.0.1/", "destination_policy_blocked"),
            ("https://example.test/robots.txt", "robots_redirect_loop"),
        ):
            bundle, http = await self.collect(
                {
                    "https://example.test/robots.txt": Response(302, {"location": target}, b""),
                }
            )
            self.assertEqual(bundle["failures"][0]["outcome"], outcome)
            self.assertEqual(len(http.calls), 1)
        self.policy["version"] = "collector-v2"
        bundle, _ = await self.collect(
            {"https://example.test/robots.txt": Response(302, {"location": "/rules"}, b"")}
        )
        self.assertEqual(bundle["failures"][0]["outcome"], "robots_unavailable")

    async def test_crawl_delay_exceeding_budget_never_fetches_page(self):
        http = FakeHTTP(
            {
                "https://example.test/robots.txt": Response(
                    200, {}, b"User-agent: *\nCrawl-delay: 100\n"
                )
            }
        )
        bundle = await Collector(self.artifacts, self.policy, http).collect(
            "https://example.test/", budget_seconds=0.1
        )
        self.assertEqual(bundle["failures"][0]["outcome"], "robots_rate_deferred")
        self.assertEqual(http.calls, ["https://example.test/robots.txt"])

    async def test_crawl_delay_equal_to_chain_budget_is_affordable(self):
        import time

        self.policy["chain_seconds"] = 1
        starts = []

        class TimedHTTP(FakeHTTP):
            def request(self, *args):
                starts.append(time.monotonic())
                return super().request(*args)

        http = TimedHTTP(
            {
                "https://example.test/robots.txt": Response(
                    200, {}, b"User-agent: *\nCrawl-delay: 1\n"
                ),
                "https://example.test/": Response(
                    200, {"content-type": "text/html"}, b"<h1>Example</h1>"
                ),
            }
        )
        bundle = await Collector(self.artifacts, self.policy, http).collect(
            "https://example.test/", budget_seconds=3
        )
        self.assertEqual(bundle["outcome"], "available")
        self.assertGreaterEqual(starts[1] - starts[0], 0.99)

    async def test_chain_network_budget_is_shared_across_redirects(self):
        import time

        self.policy["chain_seconds"] = 0.08
        timeouts = []

        class SlowHTTP(FakeHTTP):
            def request(self, url, timeout, cap):
                timeouts.append(timeout)
                time.sleep(0.02)
                return super().request(url, timeout, cap)

        http = SlowHTTP(
            {
                "https://example.test/": Response(302, {"location": "/next"}, b""),
                "https://example.test/next": Response(
                    200, {"content-type": "text/html"}, b"<h1>Example</h1>"
                ),
            }
        )
        await Collector(self.artifacts, self.policy, http).collect("https://example.test/")
        self.assertEqual(len(timeouts), 3)
        self.assertLess(timeouts[2], timeouts[0] - 0.03)
        self.assertLessEqual(timeouts[0], 0.08)

    async def test_challenge_and_script_only_diagnostics(self):
        bundle, http = await self.collect(
            {
                "https://example.test/robots.txt": Response(
                    403,
                    {},
                    b'<html><title>Just a moment...</title><script src="/cdn-cgi/challenge-platform/test"></script></html>',
                ),
            }
        )
        self.assertEqual(bundle["failures"][0]["outcome"], "robots_challenge_blocked")
        self.assertEqual(len(http.calls), 1)
        bundle, _ = await self.collect(
            {
                "https://example.test/": Response(
                    200,
                    {"content-type": "text/html"},
                    b'<html><script src="/parking-lander/app.js"></script><div id="root"></div></html>',
                ),
            }
        )
        self.assertEqual(bundle["failures"][0]["outcome"], "script_only_content")
        self.assertEqual(bundle["failures"][0]["indicators"], ["suspected_parking_shell"])
        self.assertEqual(bundle["pages"][0]["elements"], [])

    async def test_legacy_chain_limit_still_includes_pacing(self):
        self.policy.update(version="collector-v3", chain_seconds=1)
        bundle, http = await self.collect(
            {
                "https://example.test/robots.txt": Response(
                    200, {}, b"User-agent: *\nCrawl-delay: 1\n"
                ),
            }
        )
        self.assertEqual(bundle["failures"][0]["outcome"], "robots_rate_deferred")
        self.assertEqual(len(http.calls), 1)

    async def test_network_budget_exhaustion_stops_retry(self):
        import time

        self.policy["chain_seconds"] = 0.03

        class TimeoutHTTP(FakeHTTP):
            def request(self, url, timeout, cap):
                if url.endswith("robots.txt"):
                    return super().request(url, timeout, cap)
                self.calls.append(url)
                time.sleep(timeout)
                raise FetchError("timeout")

        http = TimeoutHTTP({})
        bundle = await Collector(self.artifacts, self.policy, http).collect("https://example.test/")
        self.assertEqual(bundle["failures"][0]["outcome"], "time_budget_exhausted")
        self.assertEqual(len(http.calls), 2)

    async def test_tls_diagnostic_survives_into_bundle(self):
        detail = {"verify_code": 20, "verify_message": "unable to get local issuer certificate"}
        bundle, _ = await self.collect(
            {
                "https://example.test/": FetchError("tls_validation_failed", detail),
            }
        )
        self.assertEqual(bundle["failures"][0]["detail"], detail)
        self.assertEqual(bundle["attempts"][-1]["detail"], detail)
