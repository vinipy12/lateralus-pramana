import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from pramana.assessment_prompt import INSTRUCTIONS, PROMPT_VERSION, evidence_input
from pramana.codex_runtime import (
    CodexRuntime,
    RuntimeExecutionError,
    normalize_usage,
    subscription_config,
    subscription_environment,
)
from pramana.contracts import validate_config
from pramana.validation import validate_assessment

FAKE_CLI = """#!/usr/bin/python3
import json, os, sys, time
args=sys.argv[1:]
if args == ["--version"]:
 print("codex-cli 0.155.1"); sys.exit(0)
if args == ["login","status"]:
 print("Logged in using ChatGPT"); sys.exit(0)
assert "OPENAI_API_KEY" not in os.environ
assert "CODEX_API_KEY" not in os.environ
assert "OPENAI_BASE_URL" not in os.environ
payload=json.load(sys.stdin)
mode=payload["company"]["fields"]["name"]
print(json.dumps({"type":"thread.started", "thread_id":"thread-"+str(os.getpid())}), flush=True)
if mode == "hang":
 time.sleep(60)
if mode == "tool":
 print(json.dumps({"type":"item.started","item":{"type":"command_execution"}}),flush=True)
 time.sleep(60)
answer={"verdict":"uncertain","reason_codes":["insufficient_evidence"],"rationale":"Insufficient synthetic evidence.","citations":[],"relationship":None,"missing_evidence":["identity"],"conflicting_evidence":[],"collection_request":None,"website_page_id":None,"site_substance":{"value":"indeterminate","passage_id":None},"operator_identity":{"value":"indeterminate","passage_id":None},"identifier_findings":[]}
if "labels" in payload:
 if "label_ids" in payload:
  answer.update(label_ids=payload["label_ids"],disposition="uncertain")
 else:
  answer.update(label_reviews={slot:"Insufficient evidence." for slot in payload["labels"]},disposition="uncertain")
output=args[args.index("--output-last-message")+1]
with open(output,"w") as f:
 f.write("invalid" if mode == "invalid" else json.dumps(answer))
print(json.dumps({"type":"turn.completed","usage":{"input_tokens":31,"cached_input_tokens":7,"output_tokens":11}}),flush=True)
if mode == "failed":
 sys.exit(1)
"""


def task(role="labeler_1", mode="Example", invocation="invocation_1"):
    result = {
        "case_id": "opaque_case",
        "round_id": 0,
        "role": role,
        "invocation_id": invocation,
        "company_snapshot_hash": "snapshot",
        "bundle_id": "bundle",
        "rubric_version": "rubric-v3",
        "relationship_policy_version": "evidence-directional-v1",
        "prompt_version": PROMPT_VERSION,
        "model": "gpt-5.6-luna",
        "company": {"fields": {"name": mode}, "limitations": {}},
        "bundle": {
            "bundle_id": "bundle",
            "outcome": "unavailable",
            "pages": [],
            "attempts": [{"secret_source": "never disclose"}],
        },
    }
    if role == "judge":
        result.update(
            labels=[{"assessment_id": f"label_{i}", "verdict": "uncertain"} for i in range(3)],
            label_ids=[f"label_{i}" for i in range(3)],
        )
    return result


class CodexRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        executable = Path(self.temp.name) / "fake-codex"
        executable.write_text(FAKE_CLI)
        executable.chmod(0o700)
        self.runtime = CodexRuntime(self.temp.name, executable=str(executable))

    def test_subscription_configuration_and_environment(self):
        validate_config(subscription_config())
        env = subscription_environment(
            {
                "HOME": "/home/example",
                "PATH": "/usr/bin",
                "CODEX_HOME": "/home/example/.codex",
                "OPENAI_API_KEY": "private",
                "CODEX_API_KEY": "private",
                "OPENAI_BASE_URL": "wrong",
                "CODEX_THREAD_ID": "parent",
            }
        )
        self.assertEqual(set(env), {"HOME", "PATH", "CODEX_HOME"})
        command = self.runtime.command(task(), Path(self.temp.name), "/tmp/empty")
        self.assertIn('forced_login_method="chatgpt"', command)
        self.assertIn("--ignore-user-config", command)
        self.assertIn("read-only", command)
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", command)
        self.assertNotIn("resume", command)
        for feature in ("shell_tool", "apps", "plugins", "multi_agent", "browser_use"):
            self.assertIn(feature, command)

    async def test_fresh_sessions_schema_output_and_usage(self):
        tasks = [task(invocation=f"invocation_{i}") for i in range(3)]
        results = await asyncio.gather(*(self.runtime.invoke(t) for t in tasks))
        self.assertEqual(len({r.native_receipt["thread_id"] for r in results}), 3)
        for result, original in zip(results, tasks):
            validate_assessment(result.output, original)
            self.assertEqual(result.usage["input_tokens"], 31)
            self.assertEqual(result.usage["usage_status"], "partial")
            self.assertIsNone(result.actual_model)
        with self.assertRaises(ValueError):
            await self.runtime.invoke(tasks[0])

    async def test_judge_sees_all_anonymous_labels(self):
        original = task(role="judge")
        result = await self.runtime.invoke(original)
        validated = validate_assessment(result.output, original)
        self.assertEqual(validated["label_ids"], original["label_ids"])

    async def test_failed_and_invalid_results_preserve_incurred_usage(self):
        for mode in ("failed", "invalid"):
            with self.assertRaises(RuntimeExecutionError) as caught:
                await self.runtime.invoke(task(mode=mode, invocation=mode))
            self.assertEqual(caught.exception.usage["output_tokens"], 11)
            self.assertTrue(Path(caught.exception.receipt["directory"], "receipt.json").exists())

    async def test_timeout_and_tool_attempt_stop_session(self):
        self.runtime.options["timeout_seconds"] = 1
        for mode in ("hang", "tool"):
            with self.assertRaises(RuntimeExecutionError) as caught:
                await self.runtime.invoke(task(mode=mode, invocation=mode))
            self.assertIsNotNone(caught.exception.receipt["returncode"])
            self.assertEqual(caught.exception.usage["usage_status"], "unavailable")

    async def test_cancellation_persists_receipt(self):
        work = asyncio.create_task(self.runtime.invoke(task(mode="hang")))
        directory = self.runtime.root / "invocation_1"
        while (
            not (directory / "events.jsonl").exists()
            or not (directory / "events.jsonl").stat().st_size
        ):
            await asyncio.sleep(0.01)
        work.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await work
        receipt = json.loads((directory / "receipt.json").read_text())
        self.assertIsNotNone(receipt["returncode"])

    def test_prompt_minimization_and_injection_contract(self):
        payload = evidence_input(task())
        self.assertNotIn(b"secret_source", payload)
        self.assertNotIn(b"invocation_1", payload)
        self.assertIn("untrusted data", INSTRUCTIONS)
        self.assertIn("Never apply majority vote", INSTRUCTIONS)
        self.assertIsNone(normalize_usage([], "test")["input_tokens"])

    async def test_legacy_prompt_remains_executable(self):
        original = task(invocation="legacy")
        original["prompt_version"] = "codex-evidence-v1"
        original["rubric_version"] = "rubric-v1"
        original["relationship_policy_version"] = "conservative-v1"
        result = await self.runtime.invoke(original)
        validated = validate_assessment(result.output, original)
        self.assertNotIn("assessment_version", validated)
        self.assertEqual(validated["verdict"], "uncertain")
        payload = json.loads(evidence_input(original))
        self.assertIn("bundle_id", payload)
