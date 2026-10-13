import copy
import unittest

from pramana.assessment_prompt import (
    PROMPT_VERSION,
    instructions,
    output_schema,
    prompt_hash,
)
from pramana.codex_runtime import subscription_config
from pramana.contracts import ContractError, validate_config
from pramana.decision import decide
from pramana.evidence import catalog
from pramana.validation import validate_assessment

V3 = "codex-evidence-v3"
V3_HASH = "fd0ab2c9e1d6c51e13a97186f2fefcba1493e33e5fc9bad36d3b87f3ba3da9fe"


def fixture(field="phones", value="+1 555 010 1234", dependence="independent"):
    task = {
        "case_id": "case",
        "round_id": 0,
        "role": "labeler_1",
        "invocation_id": "invocation",
        "company_snapshot_hash": "snapshot",
        "bundle_id": "bundle_strict",
        "rubric_version": "rubric-v2",
        "relationship_policy_version": "conservative-v1",
        "assessment_version": "pramana.v2",
        "prompt_version": PROMPT_VERSION,
        "company": {
            "fields": {"name": "Example Workshop", field: [value]},
            "limitations": {field: {"dependence": dependence}},
        },
        "bundle": {
            "bundle_id": "bundle_strict",
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
                            "value": f"Contact Example Workshop: {value}",
                        },
                    ],
                }
            ],
        },
    }
    pages, passages = catalog(task["bundle"])
    ids = list(passages)
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
        verdict="match",
        website_page_id=next(iter(pages)),
        reason_codes=["identity_supported"],
        rationale="Operating identity and supplied contact agree.",
        citations=[{"passage_id": p, "claim": "Identity or contact agreement"} for p in ids],
        relationship=None,
        missing_evidence=[],
        conflicting_evidence=[],
        collection_request=None,
        corroboration={"field": field, "value_index": 0, "passage_id": ids[1]},
    )
    return task, output


class CorroborationTests(unittest.TestCase):
    def test_name_only_cannot_pass_as_match(self):
        task, output = fixture()
        task["company"]["fields"].pop("phones")
        with self.assertRaises(ContractError):
            validate_assessment(output, task)
        output.update(
            verdict="uncertain",
            website_page_id=None,
            corroboration=None,
            reason_codes=["insufficient_evidence"],
        )
        final = validate_assessment(output, task)
        self.assertIsNone(final["verified_company_domain"])
        self.assertIsNone(final["corroboration"])

    def test_selected_phone_address_and_independent_social_are_preserved(self):
        for field, value in [
            ("phones", "+1 555 010 1234"),
            ("locations", "12 Example Street, Example City"),
            ("social_urls", "https://social.example/workshop"),
        ]:
            with self.subTest(field=field):
                task, output = fixture(field, value)
                final = validate_assessment(output, task)
                self.assertEqual(final["verified_company_domain"], "example.test")
                self.assertEqual(final["corroboration"]["supplied_value"], value)
                self.assertIn(value, final["corroboration"]["citation"]["excerpt"])

    def test_missing_fabricated_or_uncited_corroboration_is_invalid(self):
        task, output = fixture()
        for selection in [
            None,
            {"field": "name", "value_index": 0, "passage_id": "bundle_stric:p1"},
            {"field": "phones", "value_index": 2, "passage_id": "bundle_stric:p2"},
            {"field": "phones", "value_index": True, "passage_id": "bundle_stric:p2"},
            {"field": "phones", "value_index": 0, "passage_id": "different:p1"},
        ]:
            with self.subTest(selection=selection), self.assertRaises(ContractError):
                validate_assessment({**output, "corroboration": selection}, task)
        missing = copy.deepcopy(output)
        del missing["corroboration"]
        with self.assertRaises(ContractError):
            validate_assessment(missing, task)
        uncited = copy.deepcopy(output)
        uncited["citations"] = uncited["citations"][:1]
        with self.assertRaises(ContractError):
            validate_assessment(uncited, task)

    def test_dependence_is_not_silently_promoted(self):
        task, output = fixture(dependence="unknown")
        self.assertEqual(
            validate_assessment(output, task)["corroboration"]["dependence"], "unknown"
        )
        task["company"]["limitations"]["phones"]["dependence"] = "website_derived"
        with self.assertRaises(ContractError):
            validate_assessment(output, task)
        task, output = fixture("social_urls", "https://social.example/workshop", "unknown")
        with self.assertRaises(ContractError):
            validate_assessment(output, task)

    def test_judge_also_requires_second_identifier(self):
        task, output = fixture()
        task.update(role="judge", label_ids=["one", "two", "three"])
        output.update(
            role="judge",
            label_reviews=dict.fromkeys(("a", "b", "c"), "Reviewed"),
            disposition="accept",
        )
        self.assertEqual(validate_assessment(output, task)["label_ids"], task["label_ids"])
        output["corroboration"] = None
        with self.assertRaises(ContractError):
            validate_assessment(output, task)

    def test_prompt_contract_and_legacy_versions_are_distinct(self):
        cfg = subscription_config()
        self.assertEqual(cfg["rubric_version"], "rubric-v3")
        self.assertEqual(cfg["prompt_version"], "codex-evidence-v4")
        validate_config(cfg)
        self.assertIn("Name-only evidence must remain uncertain", instructions(V3))
        self.assertIn("corroboration", output_schema(version=V3)["required"])
        self.assertNotIn("corroboration", output_schema()["properties"])
        self.assertIn("identifier_findings", output_schema()["required"])
        self.assertNotIn("corroboration", output_schema(version="codex-evidence-v2")["properties"])
        self.assertIn("Apply rubric-v1", instructions("codex-evidence-v2"))
        self.assertNotEqual(prompt_hash(PROMPT_VERSION), prompt_hash(V3))
        self.assertEqual(prompt_hash(V3), V3_HASH)
        previous = {
            **cfg,
            "rubric_version": "rubric-v2",
            "prompt_version": V3,
            "relationship_policy_version": "conservative-v1",
            "decision_version": "none",
        }
        validate_config(previous)
        for broken in (
            {"prompt_version": "codex-evidence-v2"},
            {"rubric_version": "rubric-v2"},
            {"relationship_policy_version": "conservative-v1"},
            {"decision_version": "none"},
            {"decision_version": "decision-v3"},
            {**previous, "decision_version": "decision-v1"},
        ):
            with self.subTest(broken=broken), self.assertRaises(ContractError):
                validate_config({**cfg, **broken})

    def test_old_name_only_match_remains_readable(self):
        task, output = fixture()
        task.update(rubric_version="rubric-v1", prompt_version="codex-evidence-v2")
        output["rubric_version"] = "rubric-v1"
        del output["corroboration"]
        task["company"]["fields"].pop("phones")
        final = validate_assessment(output, task)
        self.assertEqual(final["verdict"], "match")
        self.assertNotIn("corroboration", final)


def directional(field="phones", value="+1 555 010 1234", dependence="independent"):
    task, output = fixture(field, value, dependence)
    task.update(
        rubric_version="rubric-v3",
        relationship_policy_version="evidence-directional-v1",
        prompt_version=PROMPT_VERSION,
    )
    ids = list(catalog(task["bundle"])[1])
    del output["corroboration"]
    output.update(
        rubric_version="rubric-v3",
        relationship_policy_version="evidence-directional-v1",
        site_substance={"value": "substantive", "passage_id": ids[0]},
        operator_identity={"value": "matches_supplied", "passage_id": ids[0]},
        identifier_findings=[
            {"field": field, "value_index": 0, "outcome": "agree", "passage_id": ids[1]}
        ],
    )
    return task, output, ids


class DirectionalFactTests(unittest.TestCase):
    def test_the_host_resolves_facts_and_derives_the_verdict(self):
        task, output, ids = directional()
        final = validate_assessment(output, task)
        self.assertEqual(final["identity_domain"], "example.test")
        self.assertNotIn("verified_company_domain", final)
        self.assertNotIn("corroboration", final)
        finding = final["identifier_findings"][0]
        self.assertEqual(finding["supplied_value"], "+1 555 010 1234")
        self.assertEqual(finding["dependence"], "independent")
        self.assertIn("+1 555 010 1234", finding["citation"]["excerpt"])
        self.assertEqual(decide(final), ("match", ["identity_supported"], "stage3:agreement"))

    def test_a_different_operator_must_state_one_relationship_direction(self):
        task, output, ids = directional()
        output["operator_identity"] = {"value": "different_operator", "passage_id": ids[0]}
        with self.assertRaises(ContractError):
            validate_assessment(output, task)
        output["relationship"] = {"type": None, "direction": "no_evidence", "citations": []}
        final = validate_assessment(output, task)
        self.assertEqual(decide(final)[0], "uncertain")
        output["relationship"] = {"type": None, "direction": "invented", "citations": []}
        with self.assertRaises(ContractError):
            validate_assessment(output, task)
        output["operator_identity"] = {"value": "matches_supplied", "passage_id": ids[0]}
        output["relationship"] = {"type": None, "direction": "no_evidence", "citations": []}
        with self.assertRaises(ContractError):
            validate_assessment(output, task)

    def test_absent_continuity_evidence_cannot_carry_a_relationship_claim(self):
        task, output, ids = directional()
        output["operator_identity"] = {"value": "different_operator", "passage_id": ids[0]}
        output["relationship"] = {
            "type": "rebrand",
            "direction": "no_evidence",
            "citations": [{"passage_id": ids[0], "claim": "Former name"}],
        }
        with self.assertRaises(ContractError):
            validate_assessment(output, task)
        output["relationship"]["direction"] = "evidenced_continuity"
        final = validate_assessment(output, task)
        self.assertEqual(decide(final)[0], "match")

    def test_agreement_and_conflict_must_cite_a_resolvable_passage(self):
        task, output, ids = directional()
        for finding in (
            {"field": "phones", "value_index": 0, "outcome": "agree", "passage_id": None},
            {"field": "phones", "value_index": 0, "outcome": "agree", "passage_id": "other:p1"},
            {"field": "phones", "value_index": 0, "outcome": "conflict", "passage_id": None},
            {"field": "phones", "value_index": 0, "outcome": "absent", "passage_id": ids[1]},
            {"field": "phones", "value_index": 3, "outcome": "agree", "passage_id": ids[1]},
            {"field": "name", "value_index": 0, "outcome": "agree", "passage_id": ids[1]},
            {"field": "phones", "value_index": 0, "outcome": "invented", "passage_id": ids[1]},
        ):
            with self.subTest(finding=finding), self.assertRaises(ContractError):
                validate_assessment({**output, "identifier_findings": [finding]}, task)

    def test_one_supplied_identifier_cannot_carry_two_findings(self):
        task, output, ids = directional()
        output["identifier_findings"] = [
            {"field": "phones", "value_index": 0, "outcome": "agree", "passage_id": ids[1]},
            {"field": "phones", "value_index": 0, "outcome": "conflict", "passage_id": ids[1]},
        ]
        with self.assertRaises(ContractError):
            validate_assessment(output, task)

    def test_provenance_still_restricts_agreement(self):
        task, output, _ = directional(dependence="unknown")
        self.assertEqual(
            validate_assessment(output, task)["identifier_findings"][0]["dependence"], "unknown"
        )
        task["company"]["limitations"]["phones"]["dependence"] = "website_derived"
        with self.assertRaises(ContractError):
            validate_assessment(output, task)
        task, output, _ = directional("social_urls", "https://social.example/workshop", "unknown")
        with self.assertRaises(ContractError):
            validate_assessment(output, task)

    def test_a_non_substantive_substance_requires_a_cited_passage(self):
        task, output, ids = directional()
        output["site_substance"] = {"value": "placeholder", "passage_id": None}
        with self.assertRaises(ContractError):
            validate_assessment(output, task)
        output["site_substance"] = {"value": "placeholder", "passage_id": ids[0]}
        output["website_page_id"] = None
        final = validate_assessment(output, task)
        self.assertIsNone(final["identity_domain"])
        self.assertEqual(decide(final), ("parked", ["parking_supported"], "stage0:placeholder"))
        output["site_substance"] = {"value": "unknown", "passage_id": ids[0]}
        with self.assertRaises(ContractError):
            validate_assessment(output, task)

    def test_an_unidentified_site_cannot_select_a_website(self):
        task, output, ids = directional()
        output["operator_identity"] = {"value": "indeterminate", "passage_id": None}
        with self.assertRaises(ContractError):
            validate_assessment(output, task)
        output["website_page_id"] = None
        output["identifier_findings"] = []
        final = validate_assessment(output, task)
        self.assertIsNone(final["identity_domain"])
        self.assertEqual(decide(final)[2], "stage1:indeterminate")
