import asyncio
import copy
import json
import tempfile
import unittest

from pramana.agents import Capabilities, SyntheticRuntime, preflight
from pramana.cli import synthetic_cases
from pramana.collection import SyntheticCollector
from pramana.contracts import ROLES, default_config
from pramana.measurement import unavailable_usage
from pramana.orchestration import Pipeline
from pramana.reporting import export, summary
from pramana.storage import Store, sqlite_supported


class ObservedRuntime(SyntheticRuntime):
    def __init__(self, total):
        super().__init__(0.01)
        self.total = total
        self.label_calls = 0
        self.judge_overlap = False
        self.tasks = []
        self.roles_active = set()
        self.three_roles_overlap = False

    async def invoke(self, task):
        self.tasks.append(copy.deepcopy(task))
        role = task["role"]
        if role in ROLES:
            self.label_calls += 1
            self.roles_active.add(role)
            self.three_roles_overlap |= self.roles_active.issuperset(ROLES)
        else:
            self.judge_overlap |= self.label_calls < 3 * self.total
        try:
            return await super().invoke(task)
        finally:
            self.roles_active.discard(role)


class WorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name, "consumer_a")
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.store.close)
        self.config = default_config()
        self.config["judge_high_water"] = 1
        self.collector = SyntheticCollector(self.store.artifacts, self.config["collection"])

    def imported(self, count=12):
        self.store.import_cases("run", synthetic_cases(count), self.config)

    async def test_barrier_overlap_blindness_and_idempotent_resume(self):
        self.imported()
        self.assertIsNone(self.store.claim("run", "labeler_1", "owner"))
        runtime = ObservedRuntime(12)
        state = await Pipeline(self.store, self.collector, runtime).run("run")
        self.assertEqual(state, "completed")
        self.assertTrue(runtime.three_roles_overlap)
        self.assertTrue(runtime.judge_overlap)
        self.assertEqual(runtime.calls, 48)
        self.assertEqual(self.collector.calls, 6)
        before = summary(self.store, "run")
        self.assertEqual(before["completed_cases"], 12)
        self.assertEqual(before["invocation_attempts"], 48)
        self.assertIsNone(before["complete_model_cost"])
        for task in runtime.tasks:
            self.assertNotIn("synthetic", task["company"])
            self.assertNotIn("company_id", task["company"])
            self.assertNotIn("stratum", task)
            if task["role"] in ROLES:
                self.assertNotIn("labels", task)
            else:
                self.assertEqual(len(task["labels"]), 3)
                self.assertFalse(
                    any("role" in label or "invocation_id" in label for label in task["labels"])
                )
        await Pipeline(self.store, self.collector, runtime).run("run")
        self.assertEqual(runtime.calls, 48)
        self.assertEqual(self.collector.calls, 6)
        self.assertEqual(before, summary(self.store, "run"))
        report, root = export(self.store, "run")
        self.assertEqual(report, export(self.store, "run")[0])
        self.assertTrue(list(root.glob("events-*.jsonl")))
        events = [
            json.loads(r[0])
            for r in self.store.db.execute("SELECT payload FROM events ORDER BY seq")
        ]
        barrier = next(i for i, e in enumerate(events) if e["outcome"] == "barrier_released")
        self.assertTrue(all(i > barrier for i, e in enumerate(events) if e["stage"] in ROLES))

    async def test_duplicate_completion_and_stale_lease(self):
        self.imported(1)
        await Pipeline(self.store, self.collector, SyntheticRuntime()).run("run", collect_only=True)
        job = self.store.claim("run", "labeler_1", "first")
        output = (await SyntheticRuntime().invoke(self.store.task(job))).output
        self.assertTrue(self.store.complete(job, output))
        self.assertFalse(self.store.complete(job, output))
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM labels").fetchone()[0], 1)
        self.assertEqual(
            self.store.db.execute(
                "SELECT count(*) FROM receipts WHERE attempt=?", (job["attempt_id"],)
            ).fetchone()[0],
            1,
        )
        stale = self.store.claim("run", "labeler_2", "stale")
        result = (await SyntheticRuntime().invoke(self.store.task(stale))).output
        self.store.db.execute("UPDATE jobs SET expires=0 WHERE id=?", (stale["id"],))
        self.store.recover("run")
        self.assertIsNone(self.store.claim("run", "labeler_2", "new"))
        self.assertFalse(self.store.complete(stale, result))
        self.assertEqual(self.store.retry_unknown("run"), 1)
        fresh = self.store.claim("run", "labeler_2", "new")
        self.assertGreater(fresh["fence"], stale["fence"])
        self.assertFalse(self.store.complete(stale, result))

    async def test_invalid_citation_is_failure_not_uncertain(self):
        self.imported(1)
        await Pipeline(self.store, self.collector, SyntheticRuntime()).run("run", collect_only=True)
        job = self.store.claim("run", "labeler_1", "owner")
        task = self.store.task(job)
        output = (await SyntheticRuntime().invoke(task)).output
        output["citations"] = [
            {
                "bundle_id": task["bundle_id"],
                "page_id": "invented",
                "element_id": "invented",
                "excerpt": "invented",
                "claim": "identity",
            }
        ]
        with self.assertRaises(ValueError):
            self.store.complete(job, output)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM labels").fetchone()[0], 0)

    async def test_missing_blob_blocks_resume_and_reporting(self):
        self.imported(1)
        await Pipeline(self.store, self.collector, SyntheticRuntime()).run("run")
        key = self.store.db.execute("SELECT bundle FROM rounds LIMIT 1").fetchone()[0]
        self.store.artifacts.blobs.joinpath(key).write_bytes(b"corrupt")
        with self.assertRaises(ValueError):
            summary(self.store, "run")
        with self.assertRaises(ValueError):
            await Pipeline(self.store, self.collector, SyntheticRuntime()).run("run")

    async def test_empty_cancel_and_frozen_manifest(self):
        self.imported(0)
        state = await Pipeline(self.store, self.collector, SyntheticRuntime()).run("run")
        self.assertEqual(state, "empty")
        self.assertIsNone(summary(self.store, "run")["end_to_end_coverage"])
        with self.assertRaises(ValueError):
            self.store.import_cases("run", synthetic_cases(1), self.config)

    def test_finalization_reports_cancellation_with_pending_work(self):
        self.imported(3)
        self.store.cancel("run")
        self.assertEqual(self.store.finish_run("run"), "cancelled")
        self.assertEqual(self.store.run("run")["state"], "cancelled")

    async def test_failed_role_preserves_partial_denominator_and_attempts(self):
        class InvalidRuntime(SyntheticRuntime):
            async def invoke(self, task):
                result = await super().invoke(task)
                if task["role"] == "labeler_2":
                    result.output["bundle_id"] = "wrong"
                return result

        self.imported(3)
        state = await Pipeline(self.store, self.collector, InvalidRuntime()).run("run")
        self.assertEqual(state, "partial")
        report = summary(self.store, "run")
        self.assertEqual(report["accepted_cases"], 3)
        self.assertEqual(report["completed_cases"], 0)
        self.assertEqual(report["invocation_attempts"], 12)
        self.assertEqual(
            self.store.db.execute("SELECT count(*) FROM jobs WHERE role='judge'").fetchone()[0], 0
        )

    async def test_warm_cache_pinned_resume_and_consumer_separation(self):
        self.imported(2)
        runtime = SyntheticRuntime()
        await Pipeline(self.store, self.collector, runtime).run("run")
        self.store.import_cases("second", synthetic_cases(2), self.config)
        await Pipeline(self.store, self.collector, runtime).run("second")
        self.assertEqual(self.collector.calls, 1)
        self.assertEqual(runtime.calls, 16)
        self.store.db.execute("UPDATE cache SET expires=0")
        await Pipeline(self.store, self.collector, runtime).run("run")
        self.assertEqual(self.collector.calls, 1)
        other = Store(self.temp.name, "consumer_b")
        try:
            other.import_cases("run", synthetic_cases(2), self.config)
            collector = SyntheticCollector(other.artifacts, self.config["collection"])
            await Pipeline(other, collector, SyntheticRuntime()).run("run")
            self.assertEqual(collector.calls, 1)
            self.assertNotEqual(other.root, self.store.root)
        finally:
            other.close()

    def test_runtime_capability_rejection(self):
        runtime = SyntheticRuntime()
        runtime.capabilities = Capabilities(
            "synthetic-v1", True, 3, False, False, False, False, True
        )
        self.assertFalse(preflight(runtime, self.config)["ready"])

    def test_sqlite_fix_versions(self):
        self.assertFalse(sqlite_supported((3, 45, 1)))
        for version in ((3, 51, 3), (3, 50, 7), (3, 44, 6), (3, 52, 0)):
            self.assertTrue(sqlite_supported(version))

    async def test_supplemental_round_relabels_all_roles_and_preserves_history(self):
        from pramana.contracts import digest

        class SupplementalCollector(SyntheticCollector):
            async def collect(
                self,
                url,
                predecessor=None,
                supplemental=False,
                on_attempt=None,
                budget_seconds=None,
            ):
                bundle = await super().collect(url, predecessor, supplemental)
                if supplemental:
                    bundle["pages"][0]["elements"].append(
                        {
                            "element_id": "additional_identity",
                            "type": "heading",
                            "value": "Additional operator identity from the About page",
                        }
                    )
                bundle["pages"][0]["links"] = [
                    {"category": "about", "url": "https://example-0.test/about"}
                ]
                bundle.pop("bundle_id")
                bundle["bundle_id"] = digest(bundle)
                return bundle

        class RequestingRuntime(SyntheticRuntime):
            async def invoke(self, task):
                result = await super().invoke(task)
                if task["role"] == "judge":
                    result.output.update(
                        disposition="request_evidence",
                        collection_request={
                            "missing_fact": "operator_identity",
                            "category": "about",
                            "rationale": "Need operator identity",
                        },
                    )
                return result

        self.imported(1)
        collector = SupplementalCollector(self.store.artifacts, self.config["collection"])
        runtime = RequestingRuntime()
        state = await Pipeline(self.store, collector, runtime).run("run")
        self.assertEqual(state, "completed")
        self.assertEqual(runtime.calls, 8)
        self.assertEqual(collector.calls, 2)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM labels").fetchone()[0], 6)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM rounds").fetchone()[0], 2)
        report = summary(self.store, "run")
        self.assertEqual(report["verdicts"], {"uncertain": 1})
        self.assertEqual(report["invocation_attempts"], 8)

    async def test_late_usage_reconciles_without_accepting_stale_result(self):
        self.imported(1)
        await Pipeline(self.store, self.collector, SyntheticRuntime()).run("run", collect_only=True)
        job = self.store.claim("run", "labeler_1", "owner")
        output = (await SyntheticRuntime().invoke(self.store.task(job))).output
        self.store.db.execute("UPDATE jobs SET expires=0 WHERE id=?", (job["id"],))
        self.store.recover("run")
        usage = {
            **unavailable_usage(),
            "usage_status": "reported",
            "input_tokens": 17,
            "output_tokens": 9,
        }
        self.assertFalse(self.store.complete(job, output, usage))
        self.assertFalse(self.store.complete(job, output, usage))
        self.assertEqual(
            self.store.db.execute("SELECT count(*) FROM reconciliations").fetchone()[0], 1
        )
        report = summary(self.store, "run")
        self.assertEqual(report["known_tokens"]["input_tokens"], 17)
        self.assertEqual(report["invocation_attempts"], 1)

    async def test_cancelled_calls_are_quarantined_and_resume_is_explicit(self):
        self.imported(4)
        runtime = SyntheticRuntime(delay=10)
        task = asyncio.create_task(Pipeline(self.store, self.collector, runtime).run("run"))
        while runtime.calls < 3:
            await asyncio.sleep(0.01)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(self.store.run("run")["state"], "cancelled")
        unknown = self.store.db.execute(
            "SELECT count(*) FROM jobs WHERE state='execution_unknown'"
        ).fetchone()[0]
        self.assertEqual(unknown, 3)
        self.store.resume("run")
        self.store.retry_unknown("run")
        state = await Pipeline(self.store, self.collector, SyntheticRuntime()).run("run")
        self.assertEqual(state, "completed")
        self.assertEqual(summary(self.store, "run")["invocation_attempts"], 19)
