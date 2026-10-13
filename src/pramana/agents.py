"""Explicit runtime seam. SyntheticRuntime tests mechanics, never label quality."""

import asyncio
from dataclasses import asdict, dataclass
from typing import Protocol

from .contracts import ROLES
from .measurement import unavailable_usage


@dataclass(frozen=True)
class Capabilities:
    name: str
    isolated_contexts: bool
    max_concurrent: int
    model_identity_visible: bool
    usage_visible: bool
    reconciliation: bool
    cancellation: bool
    synthetic: bool = False


@dataclass
class AgentResult:
    output: dict
    usage: dict
    actual_model: str | None
    native_receipt: dict | None = None


class Runtime(Protocol):
    capabilities: Capabilities

    async def invoke(self, task: dict) -> AgentResult: ...


def preflight(runtime, config):
    caps = runtime.capabilities
    required = sum(config["concurrency"][role] for role in (*ROLES, "judge"))
    problems = []
    if not caps.isolated_contexts:
        problems.append("Fresh isolated contexts are required")
    if caps.max_concurrent < required:
        problems.append(
            f"Need {required} concurrent label/judge slots; runtime exposes {caps.max_concurrent}"
        )
    if config["runtime"] != caps.name:
        problems.append("Configured runtime differs from installed adapter")
    if not caps.synthetic and config["prompt_version"] == "none":
        problems.append("An execution-ready, reviewed prompt version is required")
    return {
        "capabilities": asdict(caps),
        "required_concurrency": required,
        "ready": not problems,
        "problems": problems,
        "warnings": [
            name
            for name, visible in (
                (
                    "Actual model identity unavailable; reuse stays run-scoped",
                    caps.model_identity_visible,
                ),
                ("Usage unavailable; complete model cost is unknown", caps.usage_visible),
                ("Unreconciled interruptions require explicit retry", caps.reconciliation),
            )
            if not visible
        ],
    }


class SyntheticRuntime:
    capabilities = Capabilities("synthetic-v1", True, 1024, True, False, False, True, True)

    def __init__(self, delay=0.005):
        self.delay = delay
        self.calls = 0
        self.active = 0
        self.peak_active = 0

    async def invoke(self, task):
        self.calls += 1
        self.active += 1
        self.peak_active = max(self.peak_active, self.active)
        try:
            await asyncio.sleep(self.delay)
            output = {
                key: task[key]
                for key in (
                    "case_id",
                    "round_id",
                    "role",
                    "invocation_id",
                    "company_snapshot_hash",
                    "bundle_id",
                    "rubric_version",
                    "relationship_policy_version",
                )
            }
            output.update(
                verdict="uncertain",
                reason_codes=["synthetic"],
                rationale="Synthetic adapter exercises orchestration only; no identity assessment was made.",
                citations=[],
                relationship=None,
                missing_evidence=["real_assessment"],
                conflicting_evidence=[],
                collection_request=None,
            )
            if task["rubric_version"] == "rubric-v2":
                output["corroboration"] = None
            elif task["rubric_version"] == "rubric-v3":
                output.update(
                    site_substance={"value": "indeterminate", "passage_id": None},
                    operator_identity={"value": "indeterminate", "passage_id": None},
                    identifier_findings=[],
                )
            if task.get("assessment_version") == "pramana.v2":
                output["website_page_id"] = None
                if task["role"] == "judge":
                    output["label_reviews"] = dict.fromkeys(
                        ("a", "b", "c"), "Synthetic review only."
                    )
            if task["role"] == "judge":
                output.update(label_ids=task["label_ids"], disposition="uncertain")
            return AgentResult(
                output, unavailable_usage("synthetic_no_model_invoked"), "synthetic-v1"
            )
        finally:
            self.active -= 1
