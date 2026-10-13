import json
import tempfile
import unittest

from pramana.agents import SyntheticRuntime
from pramana.assessment_prompt import LINEAGE, PROMPT_VERSION, evidence_input, output_schema
from pramana.cli import synthetic_cases
from pramana.collection import SyntheticCollector
from pramana.contracts import ContractError, blinded_company, default_config, digest, validate_case
from pramana.evidence import catalog
from pramana.orchestration import Pipeline
from pramana.reporting import export, summary
from pramana.results import case_result, iter_results
from pramana.storage import Store
from pramana.validation import validate_assessment


def legacy_case():
    case = next(synthetic_cases(1))
    case["company"]["provenance"]["name"] = {
        "source": "synthetic_fixture",
        "observed_at": None,
        "website_derived": True,
    }
    return case


class ProvenanceTests(unittest.TestCase):
    def test_unknown_is_not_reinterpreted_as_website_derived(self):
        raw = next(synthetic_cases(1))
        raw["company"]["provenance"]["name"]["dependence"] = "unknown"
        case = validate_case(raw)
        limits = blinded_company(case["company"])["limitations"]["name"]
        self.assertEqual(limits, {"dependence": "unknown", "observed_at": None})
        raw["company"]["provenance"]["name"]["website_derived"] = True
        with self.assertRaises(ContractError):
            validate_case(raw)

    def test_legacy_dependence_and_hash_are_preserved(self):
        case = validate_case(legacy_case(), "pramana.v1")
        self.assertEqual(case["schema_version"], "pramana.v1")
        self.assertEqual(
            blinded_company(case["company"])["limitations"]["name"]["website_derived"], True
        )
        self.assertNotIn("dependence", case["company"]["provenance"]["name"])
        import hashlib

        self.assertEqual(
            digest("example"),
            hashlib.sha256(b'{"schema":"pramana.v1","value":"example"}').hexdigest(),
        )
        with self.assertRaises(ContractError):
            validate_case(legacy_case(), "pramana.v2")


class ResultWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name, "synthetic")
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.store.close)
        self.config = {
            **default_config(),
            "rubric_version": "rubric-v1",
            "relationship_policy_version": "conservative-v1",
            "decision_version": "none",
        }  # Frozen v2 compatibility fixtures.
        self.collector = SyntheticCollector(self.store.artifacts, self.config["collection"])

    async def assessment(self):
        self.store.import_cases("case", synthetic_cases(1), self.config)
        await Pipeline(self.store, self.collector, SyntheticRuntime()).run(
            "case", collect_only=True
        )
        job = self.store.claim("case", "labeler_1", "test")
        task = self.store.task(job)
        output = (await SyntheticRuntime().invoke(task)).output
        return task, output

    async def test_passages_reconstruct_exact_quotes_and_redirect_domain(self):
        task, output = await self.assessment()
        page = task["bundle"]["pages"][0]
        page["final_url"] = "https://division.example.test/about"
        pages, passages = catalog(task["bundle"])
        selected = next(iter(passages))
        output.update(
            verdict="match",
            reason_codes=["identity_supported"],
            website_page_id=next(iter(pages)),
            citations=[{"passage_id": selected, "claim": "Operating company identity"}],
        )
        validated = validate_assessment(output, task)
        self.assertEqual(validated["citations"][0]["excerpt"], passages[selected]["excerpt"])
        self.assertEqual(validated["verified_company_domain"], "division.example.test")
        case = validate_case(next(synthetic_cases(1)))
        result = case_result(case, "completed", task["bundle"], validated)
        self.assertEqual(result["candidate_domain"], "example-0.test")
        self.assertEqual(result["resolved_url"], "https://division.example.test/about")
        self.assertEqual(result["verified_company_domain"], "division.example.test")
        self.assertEqual(result["assessment_status"], "assessed")

    async def test_invented_wrong_round_and_model_written_quotes_are_rejected(self):
        task, output = await self.assessment()
        _, passages = catalog(task["bundle"])
        for selection in (
            {"passage_id": "unknown", "claim": "identity"},
            {"passage_id": "other_bundle:p1", "claim": "identity"},
            {"passage_id": [], "claim": "identity"},
            {"passage_id": next(iter(passages)), "claim": "identity", "excerpt": "rewritten"},
        ):
            with self.subTest(selection=selection), self.assertRaises(ContractError):
                validate_assessment({**output, "citations": [selection]}, task)
        with self.assertRaises(ContractError):
            validate_assessment({**output, "round_id": 44}, task)

    async def test_canonical_url_is_not_a_verified_website(self):
        task, output = await self.assessment()
        page = task["bundle"]["pages"][0]
        page["elements"] = [
            {"element_id": "canonical", "type": "canonical", "value": "https://other.test/"}
        ]
        pages, passages = catalog(task["bundle"])
        output.update(
            verdict="match",
            website_page_id=next(iter(pages)),
            citations=[{"passage_id": next(iter(passages)), "claim": "identity"}],
        )
        with self.assertRaises(ContractError):
            validate_assessment(output, task)
        output["website_page_id"] = "https://other.test/"
        with self.assertRaises(ContractError):
            validate_assessment(output, task)

    async def test_nonmatches_cannot_publish_verified_domains(self):
        task, output = await self.assessment()
        pages, passages = catalog(task["bundle"])
        for verdict in ("mismatch", "parked", "uncertain"):
            selected = {
                **output,
                "verdict": verdict,
                "website_page_id": None,
                "citations": [{"passage_id": next(iter(passages)), "claim": "Evidence"}],
                "verified_company_domain": "invented.test",
            }
            result = validate_assessment(selected, task)
            self.assertIsNone(result["verified_company_domain"])
            with self.assertRaises(ContractError):
                validate_assessment({**selected, "website_page_id": next(iter(pages))}, task)

    async def test_judge_reviews_all_three_slots_without_copying_ids(self):
        task, output = await self.assessment()
        task.update(
            role="judge",
            labels=[{"assessment_id": str(i), "verdict": "uncertain"} for i in range(3)],
            label_ids=["0", "1", "2"],
            prompt_version="codex-evidence-v2",
        )
        output.update(
            role="judge",
            disposition="uncertain",
            label_reviews={"a": "Checked", "b": "Checked", "c": "Checked"},
        )
        result = validate_assessment(output, task)
        self.assertEqual(result["label_ids"], ["0", "1", "2"])
        payload = json.loads(evidence_input(task))
        self.assertEqual(set(payload["labels"]), {"a", "b", "c"})
        self.assertNotIn("label_ids", payload)
        self.assertNotIn("assessment_id", str(payload["labels"]))
        self.assertNotIn(
            "excerpt", output_schema(True)["properties"]["citations"]["items"]["properties"]
        )
        del output["label_reviews"]["b"]
        with self.assertRaises(ContractError):
            validate_assessment(output, task)

    async def test_empty_bundle_skips_models_survives_resume_and_stays_in_denominator(self):
        class EmptyCollector(SyntheticCollector):
            async def collect(self, *args, **kwargs):
                bundle = await super().collect(*args, **kwargs)
                bundle.update(
                    pages=[], outcome="unavailable", failures=[{"outcome": "robots_denied"}]
                )
                bundle.pop("bundle_id")
                bundle["bundle_id"] = digest(bundle)
                return bundle

        self.store.import_cases("empty", synthetic_cases(3), self.config)
        runtime = SyntheticRuntime()
        collector = EmptyCollector(self.store.artifacts, self.config["collection"])
        pipeline = Pipeline(self.store, collector, runtime)
        self.assertEqual(await pipeline.run("empty"), "partial")
        before = summary(self.store, "empty")
        self.assertEqual(runtime.calls, 0)
        self.assertEqual(before["not_assessed_cases"], 3)
        self.assertEqual(before["end_to_end_coverage"], 0)
        self.assertEqual(before["verdicts"], {})
        await pipeline.run("empty")
        self.assertEqual(before, summary(self.store, "empty"))
        report, root = export(self.store, "empty")
        results = [
            json.loads(line) for line in next(root.glob("cases-*.jsonl")).read_text().splitlines()
        ]
        self.assertEqual(len(results), report["accepted_cases"])
        for result in results:
            self.assertEqual(result["assessment_status"], "not_assessed")
            self.assertIsNone(result["verdict"])
            self.assertIsNone(result["verified_company_domain"])
        self.assertEqual(export(self.store, "empty")[0], report)

    async def test_legacy_run_retains_empty_bundle_assessment_and_export(self):
        config = {**self.config, "schema_version": "pramana.v1"}
        self.store.import_cases("legacy", [legacy_case()], config)
        runtime = SyntheticRuntime()
        await Pipeline(self.store, self.collector, runtime).run("legacy")
        before = summary(self.store, "legacy")
        self.assertEqual(runtime.calls, 4)
        self.assertEqual(before["report_version"], "v2")
        result = next(iter_results(self.store, "legacy"))
        self.assertEqual(result["domain_status"], "legacy_not_recorded")
        self.assertIsNone(result["verified_company_domain"])
        self.store.import_cases("legacy", [legacy_case()], config)
        await Pipeline(self.store, self.collector, runtime).run("legacy")
        self.assertEqual(before, summary(self.store, "legacy"))

    async def test_queue_priority_aligns_roles(self):
        self.store.import_cases("priority", synthetic_cases(4), self.config)
        await Pipeline(self.store, self.collector, SyntheticRuntime()).run(
            "priority", collect_only=True
        )
        cases = [
            self.store.claim("priority", role, "owner")["case_id"]
            for role in ("labeler_1", "labeler_2", "labeler_3")
        ]
        self.assertEqual(len(set(cases)), 1)

    async def test_match_flows_through_three_labels_judge_and_case_export(self):
        class MatchingRuntime(SyntheticRuntime):
            async def invoke(self, task):
                result = await super().invoke(task)
                pages, passages = catalog(task["bundle"])
                result.output.update(
                    verdict="match",
                    website_page_id=next(iter(pages)),
                    reason_codes=["identity_supported"],
                    citations=[{"passage_id": next(iter(passages)), "claim": "Fixture identity"}],
                )
                if task["role"] == "judge":
                    result.output["disposition"] = "accept"
                return result

        self.store.import_cases("matching", synthetic_cases(2), self.config)
        runtime = MatchingRuntime()
        await Pipeline(self.store, self.collector, runtime).run("matching")
        report, root = export(self.store, "matching")
        self.assertEqual(report["verified_domain_cases"], 2)
        self.assertEqual(report["verdicts"], {"match": 2})
        for result in iter_results(self.store, "matching"):
            self.assertEqual(result["verified_company_domain"], "example-0.test")
            self.assertTrue(result["citations"][0]["excerpt"])
            self.assertTrue(result["configuration_hash"])
        await Pipeline(self.store, self.collector, runtime).run("matching")
        self.assertEqual(runtime.calls, 8)
        self.assertEqual(export(self.store, "matching")[0], report)
        next(root.glob("cases-*.jsonl")).write_text("corrupted")
        with self.assertRaisesRegex(ValueError, "collision"):
            export(self.store, "matching")

    async def test_supplemental_without_new_evidence_does_not_relabel(self):
        class LinkedCollector(SyntheticCollector):
            async def collect(self, *args, **kwargs):
                bundle = await super().collect(*args, **kwargs)
                bundle["pages"][0]["links"] = [
                    {"category": "about", "url": "https://example-0.test/about"}
                ]
                bundle.pop("bundle_id")
                bundle["bundle_id"] = digest(bundle)
                return bundle

        class RequestRuntime(SyntheticRuntime):
            async def invoke(self, task):
                result = await super().invoke(task)
                if task["role"] == "judge":
                    result.output.update(
                        disposition="request_evidence",
                        collection_request={
                            "missing_fact": "operator_identity",
                            "category": "about",
                            "rationale": "Need identity",
                        },
                    )
                return result

        self.store.import_cases("same", synthetic_cases(1), self.config)
        runtime = RequestRuntime()
        collector = LinkedCollector(self.store.artifacts, self.config["collection"])
        await Pipeline(self.store, collector, runtime).run("same")
        self.assertEqual(runtime.calls, 4)
        self.assertEqual(collector.calls, 2)
        self.assertEqual(summary(self.store, "same")["verdicts"], {"uncertain": 1})
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM rounds").fetchone()[0], 1)

    async def test_unsupported_page_without_passages_is_not_assessed(self):
        class UnsupportedCollector(SyntheticCollector):
            async def collect(self, *args, **kwargs):
                bundle = await super().collect(*args, **kwargs)
                bundle["pages"][0].update(elements=[], unsupported_media=True)
                bundle.pop("bundle_id")
                bundle["bundle_id"] = digest(bundle)
                return bundle

        self.store.import_cases("unsupported", synthetic_cases(1), self.config)
        runtime = SyntheticRuntime()
        await Pipeline(
            self.store,
            UnsupportedCollector(self.store.artifacts, self.config["collection"]),
            runtime,
        ).run("unsupported")
        self.assertEqual(runtime.calls, 0)
        self.assertEqual(summary(self.store, "unsupported")["not_assessed_cases"], 1)


PHONE = "+1 555 010 1234"


def directional():
    """A rubric-v3 labeler task and its structured facts, kept local to this file."""
    task = {
        "case_id": "case",
        "round_id": 0,
        "role": "labeler_1",
        "invocation_id": "invocation",
        "company_snapshot_hash": "snapshot",
        "bundle_id": "bundle_directional",
        "rubric_version": "rubric-v3",
        "relationship_policy_version": "evidence-directional-v1",
        "assessment_version": "pramana.v2",
        "prompt_version": PROMPT_VERSION,
        "company": {
            "fields": {"name": "Example Workshop", "phones": [PHONE]},
            "limitations": {"phones": {"dependence": "independent"}},
        },
        "bundle": {
            "bundle_id": "bundle_directional",
            "outcome": "available",
            "pages": [
                {
                    "page_id": "page",
                    "final_url": "https://example.test/",
                    "elements": [
                        {"element_id": "identity", "type": "heading", "value": "Example Workshop"},
                        {
                            "element_id": "contact",
                            "type": "body",
                            "value": f"Contact Example Workshop: {PHONE}",
                        },
                    ],
                }
            ],
        },
    }
    pages, passages = catalog(task["bundle"])
    ids = list(passages)
    output = {key: task[key] for key in LINEAGE if key in task}
    output.update(
        verdict="match",
        website_page_id=next(iter(pages)),
        reason_codes=["identity_supported"],
        rationale="Operating identity and supplied contact agree.",
        citations=[{"passage_id": p, "claim": "Identity or contact agreement"} for p in ids],
        relationship=None,
        missing_evidence=[],
        conflicting_evidence=[],
        collection_request=None,
        site_substance={"value": "substantive", "passage_id": ids[0]},
        operator_identity={"value": "matches_supplied", "passage_id": ids[0]},
        identifier_findings=[
            {"field": "phones", "value_index": 0, "outcome": "agree", "passage_id": ids[1]}
        ],
    )
    return task, output, ids


def directional_case():
    raw = next(synthetic_cases(1))
    raw["company"]["name"] = "Example Workshop"
    raw["company"]["phones"] = [PHONE]
    raw["company"]["provenance"]["phones"] = {
        "source": "synthetic_fixture",
        "observed_at": None,
        "dependence": "independent",
    }
    return validate_case(raw)


class DerivedVerdictTests(unittest.TestCase):
    def assessed(self, **overrides):
        task, output, ids = directional()
        output.update(overrides)
        return validate_assessment(output, task), task["bundle"]

    def test_the_derived_verdict_replaces_the_assessor_verdict(self):
        final, bundle = self.assessed(verdict="uncertain", reason_codes=["insufficient_evidence"])
        with self.assertRaises(ContractError):
            case_result(directional_case(), "completed", bundle, final)
        result = case_result(directional_case(), "completed", bundle, final, "decision-v1")
        self.assertEqual(result["result_version"], "pramana.result.v3")
        self.assertEqual(result["verdict"], "match")
        self.assertEqual(result["assessor_verdict"], "uncertain")
        self.assertTrue(result["verdict_divergence"])
        self.assertEqual(result["reason_codes"], ["identity_supported"])
        self.assertEqual(result["rule_trace"], "stage3:agreement")
        self.assertEqual(result["decision_version"], "decision-v1")
        self.assertEqual(result["verified_company_domain"], "example.test")
        self.assertEqual(result["domain_status"], "verified")
        self.assertNotIn("corroboration", result)
        self.assertEqual(result["identifier_findings"][0]["outcome"], "agree")

    def test_an_agreeing_verdict_records_no_divergence(self):
        final, bundle = self.assessed()
        result = case_result(directional_case(), "completed", bundle, final, "decision-v2")
        self.assertEqual(result["result_version"], "pramana.result.v4")
        self.assertEqual(result["decision_version"], "decision-v2")
        self.assertEqual((result["verdict"], result["assessor_verdict"]), ("match", "match"))
        self.assertFalse(result["verdict_divergence"])

    def test_a_derived_nonmatch_withholds_the_identified_domain(self):
        final, bundle = self.assessed(
            identifier_findings=[],
            verdict="match",
        )
        result = case_result(directional_case(), "completed", bundle, final, "decision-v2")
        self.assertEqual(result["verdict"], "uncertain")
        self.assertEqual(result["rule_trace"], "stage3:no_identifier")
        self.assertEqual(final["identity_domain"], "example.test")
        self.assertIsNone(result["verified_company_domain"])
        self.assertIsNone(result["verified_company_url"])
        self.assertEqual(result["domain_status"], "unverified")
        self.assertTrue(result["verdict_divergence"])

    def test_absence_of_continuity_evidence_never_derives_mismatch(self):
        task, output, ids = directional()
        output.update(
            verdict="mismatch",
            reason_codes=["conflicting_identity"],
            operator_identity={"value": "different_operator", "passage_id": ids[0]},
            relationship={"type": None, "direction": "no_evidence", "citations": []},
        )
        final = validate_assessment(output, task)
        for version in ("decision-v1", "decision-v2"):
            result = case_result(directional_case(), "completed", task["bundle"], final, version)
            self.assertEqual(result["verdict"], "uncertain")
            self.assertEqual(result["reason_codes"], ["relationship_unresolved"])
        self.assertEqual(result["rule_trace"], "stage2:different_operator/no_evidence")
        self.assertEqual(result["assessor_verdict"], "mismatch")
