"""Subscription-only Codex CLI adapter. Never reads or copies credential files."""

import asyncio
import contextlib
import json
import os
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path

from .agents import AgentResult, Capabilities
from .artifacts import private_dir
from .assessment_prompt import (
    LINEAGE,
    PROMPT_VERSION,
    evidence_input,
    instructions,
    output_schema,
    prompt_hash,
)
from .contracts import ROLES, canonical, default_config
from .measurement import unavailable_usage, validate_usage

RUNTIME = "codex-subscription-v1"
DISABLED = (
    "shell_tool",
    "unified_exec",
    "apps",
    "plugins",
    "remote_plugin",
    "multi_agent",
    "memories",
    "browser_use",
    "browser_use_external",
    "in_app_browser",
    "computer_use",
    "image_generation",
    "view_image",
    "shell_snapshot",
    "goals",
    "code_mode",
    "skill_search",
    "skill_mcp_dependency_install",
    "tool_suggest",
    "request_permissions_tool",
    "sleep_tool",
)
OPTIONS = {"timeout_seconds": 180, "max_output_bytes": 4 * 1024 * 1024, "max_concurrent": 5}


class RuntimeExecutionError(RuntimeError):
    """A dispatched session failed; preserve its usage/receipt without auto-redispatch."""

    def __init__(self, message, usage, receipt):
        super().__init__(message)
        self.usage, self.receipt = usage, receipt


def subscription_config():
    return {
        **default_config(),
        "runtime": RUNTIME,
        "prompt_version": PROMPT_VERSION,
        "runtime_options": dict(OPTIONS),
    }


def subscription_environment(source=None):
    # Keep ordinary platform variables (including existing CLI login location),
    # but prevent API-key/provider overrides and inherited parent-session routing.
    source = os.environ if source is None else source
    allowed = {
        "PATH",
        "HOME",
        "CODEX_HOME",
        "USER",
        "LOGNAME",
        "LANG",
        "LC_ALL",
        "TMPDIR",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_RUNTIME_DIR",
        "DBUS_SESSION_BUS_ADDRESS",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "HTTPS_PROXY",
        "HTTP_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "https_proxy",
        "http_proxy",
        "all_proxy",
        "no_proxy",
    }
    return {k: v for k, v in source.items() if k in allowed}


def login_status(executable="codex"):
    result = subprocess.run(
        [executable, "login", "status"],
        env=subscription_environment(),
        capture_output=True,
        text=True,
        timeout=20,
    )
    return result.returncode == 0 and "Logged in using ChatGPT" in result.stdout + result.stderr


def normalize_usage(events, version):
    completed = [e for e in events if e.get("type") == "turn.completed"]
    usage = unavailable_usage("codex_did_not_report_usage")
    usage["source"] = version
    if not completed:
        return usage
    native = completed[-1].get("usage", {})
    usage.update(
        usage_status="partial",
        missing_reason="reasoning/total counters and billing semantics not exposed",
    )
    for key in ("input_tokens", "cached_input_tokens", "output_tokens"):
        usage[key] = native.get(key)
    # Native counters are retained, but billing inclusion semantics are not guessed.
    return validate_usage(usage)


class CodexRuntime:
    def __init__(self, root, options=None, executable="codex"):
        self.root = private_dir(Path(root) / "codex-invocations").resolve()
        self.options = {**OPTIONS, **(options or {})}
        if set(self.options) != set(OPTIONS) or any(
            type(v) is not int or v < 1 for v in self.options.values()
        ):
            raise ValueError("Invalid Codex runtime limits")
        self.executable = shutil.which(executable)
        if not self.executable:
            raise ValueError("Codex CLI is not installed")
        self.version = subprocess.run(
            [self.executable, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            env=subscription_environment(),
        ).stdout.strip()
        if not self.version.startswith("codex-cli 0.155."):
            raise ValueError(
                "This adapter has been validated with Codex CLI 0.155.x; revalidate flags before upgrading"
            )
        if not login_status(self.executable):
            raise ValueError(
                "ChatGPT login required: run codex login; API-key auth is not accepted"
            )
        self.capabilities = Capabilities(
            RUNTIME, True, self.options["max_concurrent"], False, True, False, True
        )
        self.capacity = asyncio.Semaphore(self.options["max_concurrent"])

    def command(self, task, directory, workdir):
        args = [
            self.executable,
            "exec",
            "--ignore-user-config",
            "--ephemeral",
            "--json",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--color",
            "never",
            "--cd",
            str(workdir),
            "--model",
            task["model"],
            "--output-schema",
            str(directory / "schema.json"),
            "--output-last-message",
            str(directory / "assessment.json"),
        ]
        settings = {
            "forced_login_method": "chatgpt",
            "model_provider": "openai",
            "approval_policy": "never",
            "web_search": "disabled",
            "mcp_servers": {},
            "project_doc_max_bytes": 0,
            "skills.include_instructions": False,
            "tools.update_plan.enabled": False,
            "agents.enabled": False,
            "tools.experimental_request_user_input.enabled": False,
            "log_dir": str(directory / "logs"),
            "developer_instructions": instructions(task["prompt_version"]),
        }
        for key, value in settings.items():
            # JSON literals used here are valid TOML scalar strings/bools or {}.
            args.extend(["-c", key + "=" + json.dumps(value)])
        for feature in DISABLED:
            args.extend(["--disable", feature])
        return [*args, "-"]

    async def _stop(self, process):
        if process.returncode is not None:
            return
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
        try:
            await asyncio.wait_for(process.wait(), 3)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            await process.wait()

    async def invoke(self, task):
        policies = {
            ("codex-evidence-v1", "rubric-v1"): "conservative-v1",
            ("codex-evidence-v2", "rubric-v1"): "conservative-v1",
            ("codex-evidence-v3", "rubric-v2"): "conservative-v1",
            (PROMPT_VERSION, "rubric-v3"): "evidence-directional-v1",
        }
        revision = (task["prompt_version"], task["rubric_version"])
        if policies.get(revision) != task["relationship_policy_version"]:
            raise ValueError(
                "This adapter only implements compatible versioned prompts, rubrics and policies"
            )
        if task["role"] not in (*ROLES, "judge"):
            raise ValueError("Unsupported Codex assessor role")
        async with self.capacity:
            return await self._invoke(task)

    async def _invoke(self, task):
        from .contracts import identifier

        directory = private_dir(self.root / identifier(task["invocation_id"]))
        if any(directory.iterdir()):
            raise ValueError(
                "Invocation directory already exists; reconcile instead of redispatching"
            )
        for name, data in (
            (
                "schema.json",
                canonical(output_schema(task["role"] == "judge", task["prompt_version"])),
            ),
            ("input.json", evidence_input(task)),
        ):
            path = directory / name
            path.write_bytes(data)
            path.chmod(0o600)
        # Work outside the checkout and artifact tree: no project instructions or
        # neighboring case payloads are presented as working context.
        with tempfile.TemporaryDirectory(prefix="pramana-codex-") as workdir:
            command = self.command(task, directory, workdir)
            events = []
            receipt = {
                "runtime": RUNTIME,
                "cli_version": self.version,
                "prompt_hash": prompt_hash(task["prompt_version"]),
                "auth": "chatgpt",
                "configured_model": task["model"],
                "actual_model": None,
                "invocation_id": task["invocation_id"],
                "directory": str(directory),
                "started_monotonic": time.monotonic(),
                "thread_id": None,
            }
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=subscription_environment(),
                start_new_session=True,
                limit=self.options["max_output_bytes"],
            )
            receipt["pid"] = process.pid
            (directory / "intent.json").write_bytes(canonical(receipt))
            total = 0

            async def drain(reader, filename, parse=False):
                nonlocal total
                with (directory / filename).open("wb") as stream:
                    while line := await reader.readline():
                        total += len(line)
                        if total > self.options["max_output_bytes"]:
                            raise ValueError("Codex output limit exceeded")
                        stream.write(line)
                        stream.flush()
                        if parse:
                            event = json.loads(line)
                            events.append(event)
                            if event.get("type") == "thread.started":
                                receipt["thread_id"] = event.get("thread_id")
                            item = event.get("item", {})
                            if item.get("type") in (
                                "command_execution",
                                "mcp_tool_call",
                                "web_search",
                                "file_change",
                            ):
                                raise ValueError(
                                    "Evidence-only Codex session attempted a tool action"
                                )

            async def communicate():
                process.stdin.write(evidence_input(task))
                await process.stdin.drain()
                process.stdin.close()
                await asyncio.gather(
                    drain(process.stdout, "events.jsonl", True), drain(process.stderr, "stderr.log")
                )
                await process.wait()

            communication = asyncio.create_task(communicate())
            failure = None
            try:
                await asyncio.wait_for(
                    asyncio.shield(communication), self.options["timeout_seconds"]
                )
            except (TimeoutError, ValueError, OSError) as exc:
                failure = type(exc).__name__
                await self._stop(process)
            except asyncio.CancelledError:
                failure = "CancelledError"
                await self._stop(process)
                raise
            finally:
                if not communication.done():
                    communication.cancel()
                await asyncio.gather(communication, return_exceptions=True)
                receipt.update(
                    returncode=process.returncode,
                    failure=failure,
                    duration_ms=(time.monotonic() - receipt["started_monotonic"]) * 1000,
                )
                receipt["usage"] = normalize_usage(events, self.version)
                (directory / "receipt.json").write_bytes(canonical(receipt))
            usage = receipt["usage"]
            if (
                failure
                or process.returncode
                or not any(e.get("type") == "turn.completed" for e in events)
            ):
                raise RuntimeExecutionError(
                    f"Codex session failed ({failure or process.returncode}); see private receipt",
                    usage,
                    receipt,
                )
            try:
                path = directory / "assessment.json"
                if path.stat().st_size > self.options["max_output_bytes"]:
                    raise ValueError("Assessment output limit exceeded")
                answer = json.loads(path.read_text())
                if not isinstance(answer, dict):
                    raise ValueError("Assessment must be an object")
            except (ValueError, OSError) as exc:
                raise RuntimeExecutionError(
                    "Codex final output is missing or invalid", usage, receipt
                ) from exc
            output = {**answer, **{key: task[key] for key in LINEAGE}}
            return AgentResult(output, usage, None, receipt)
