import unittest

from pramana.decision import DECISION_VERSION, decide
from pramana.validation import REASONS


def finding(outcome, field="phones", value_index=0, passage="bundle:p2"):
    return {
        "field": field,
        "value_index": value_index,
        "outcome": outcome,
        "passage_id": passage if outcome in ("agree", "conflict") else None,
    }


def facts(substance="substantive", operator="matches_supplied", direction=None, findings=()):
    relationship = None
    if direction is not None:
        relationship = {
            "type": "continuity",
            "direction": direction,
            "citations": [{"passage_id": "bundle:p1", "claim": "Relationship evidence"}],
        }
    return {
        "site_substance": {"value": substance, "passage_id": "bundle:p1"},
        "operator_identity": {"value": operator, "passage_id": "bundle:p1"},
        "relationship": relationship,
        "identifier_findings": list(findings),
    }


class Stage0Tests(unittest.TestCase):
    def test_corroborated_parking_and_placeholder_both_reach_parked(self):
        for substance in ("parked", "placeholder"):
            with self.subTest(substance=substance):
                verdict, reasons, trace = decide(facts(substance=substance))
                self.assertEqual(verdict, "parked")
                self.assertEqual(reasons, ["parking_supported"])
                self.assertEqual(trace, "stage0:" + substance)

    def test_substantive_and_indeterminate_substance_continue(self):
        for substance in ("substantive", "indeterminate"):
            with self.subTest(substance=substance):
                verdict, _, trace = decide(facts(substance=substance, findings=[finding("agree")]))
                self.assertEqual(verdict, "match")
                self.assertEqual(trace, "stage3:agreement")

    def test_placeholder_outranks_an_agreeing_identifier(self):
        verdict, _, trace = decide(facts(substance="placeholder", findings=[finding("agree")]))
        self.assertEqual((verdict, trace), ("parked", "stage0:placeholder"))


class OperatorAndRelationshipTests(unittest.TestCase):
    def test_matching_operator_continues_to_identifiers(self):
        verdict, _, trace = decide(facts(findings=[finding("agree")]))
        self.assertEqual((verdict, trace), ("match", "stage3:agreement"))

    def test_evidenced_continuity_continues_to_identifiers(self):
        verdict, _, trace = decide(
            facts(
                operator="different_operator",
                direction="evidenced_continuity",
                findings=[finding("agree")],
            )
        )
        self.assertEqual((verdict, trace), ("match", "stage3:agreement"))

    def test_evidenced_unrelated_is_the_only_path_to_mismatch(self):
        verdict, reasons, trace = decide(
            facts(operator="different_operator", direction="evidenced_unrelated")
        )
        self.assertEqual(verdict, "mismatch")
        self.assertEqual(reasons, ["conflicting_identity"])
        self.assertEqual(trace, "stage2:different_operator/evidenced_unrelated")

    def test_different_operator_without_continuity_evidence_is_uncertain(self):
        """The regression for the three flagged overconfident mismatches."""
        verdict, reasons, trace = decide(
            facts(
                operator="different_operator",
                direction="no_evidence",
                findings=[finding("agree")],
            )
        )
        self.assertEqual(verdict, "uncertain")
        self.assertEqual(reasons, ["relationship_unresolved"])
        self.assertEqual(trace, "stage2:different_operator/no_evidence")

    def test_a_missing_direction_is_never_read_as_disproof(self):
        for relationship in (None, {"type": "continuity", "citations": []}):
            with self.subTest(relationship=relationship):
                fact_set = facts(operator="different_operator")
                fact_set["relationship"] = relationship
                verdict, _, trace = decide(fact_set)
                self.assertEqual(verdict, "uncertain")
                self.assertEqual(trace, "stage2:different_operator/no_evidence")

    def test_indeterminate_operator_is_uncertain_whatever_the_identifiers(self):
        for findings in ([], [finding("agree")], [finding("conflict")]):
            with self.subTest(findings=findings):
                verdict, reasons, trace = decide(facts(operator="indeterminate", findings=findings))
                self.assertEqual(verdict, "uncertain")
                self.assertEqual(reasons, ["insufficient_evidence"])
                self.assertEqual(trace, "stage1:indeterminate")


class IdentifierTests(unittest.TestCase):
    def test_one_agreement_is_sufficient(self):
        verdict, reasons, trace = decide(facts(findings=[finding("agree")]))
        self.assertEqual(verdict, "match")
        self.assertEqual(reasons, ["identity_supported"])
        self.assertEqual(trace, "stage3:agreement")

    def test_agreement_outranks_conflict(self):
        verdict, _, trace = decide(
            facts(
                findings=[
                    finding("agree", "locations", 0, "bundle:p2"),
                    finding("conflict", "phones", 0, "bundle:p3"),
                ]
            )
        )
        self.assertEqual((verdict, trace), ("match", "stage3:agreement"))

    def test_conflict_alone_is_uncertain_not_mismatch(self):
        verdict, reasons, trace = decide(facts(findings=[finding("conflict")]))
        self.assertEqual(verdict, "uncertain")
        self.assertEqual(reasons, ["conflicting_identity", "insufficient_evidence"])
        self.assertEqual(trace, "stage3:conflict_only")

    def test_no_identifier_evidence_keeps_name_only_matches_out(self):
        for findings in ([], [finding("absent")], [finding("insufficient_granularity")]):
            with self.subTest(findings=findings):
                verdict, reasons, trace = decide(facts(findings=findings))
                self.assertEqual(verdict, "uncertain")
                self.assertEqual(reasons, ["insufficient_evidence"])
                self.assertEqual(trace, "stage3:no_identifier")

    def test_city_only_address_does_not_agree_and_does_not_conflict(self):
        street = decide(facts(findings=[finding("agree", "locations")]))
        city_only = decide(facts(findings=[finding("insufficient_granularity", "locations")]))
        self.assertEqual(street[0], "match")
        self.assertEqual(city_only[0], "uncertain")
        self.assertEqual(city_only[2], "stage3:no_identifier")

    def test_formatted_equivalent_phone_agreement_is_credited(self):
        verdict, _, trace = decide(facts(findings=[finding("agree", "phones")]))
        self.assertEqual((verdict, trace), ("match", "stage3:agreement"))

    def test_phone_differing_only_in_digits_conflicts(self):
        verdict, _, trace = decide(facts(findings=[finding("conflict", "phones")]))
        self.assertEqual((verdict, trace), ("uncertain", "stage3:conflict_only"))

    def test_former_name_continuity_with_agreeing_identifiers_matches(self):
        verdict, reasons, trace = decide(
            facts(
                operator="different_operator",
                direction="evidenced_continuity",
                findings=[
                    finding("agree", "phones", 0, "bundle:p2"),
                    finding("agree", "locations", 0, "bundle:p3"),
                ],
            )
        )
        self.assertEqual(verdict, "match")
        self.assertEqual(reasons, ["identity_supported"])
        self.assertEqual(trace, "stage3:agreement")


class TraceTests(unittest.TestCase):
    def test_every_reason_code_stays_inside_the_frozen_vocabulary(self):
        traces = set()
        for fact_set in (
            facts(substance="parked"),
            facts(substance="placeholder"),
            facts(operator="indeterminate"),
            facts(operator="different_operator", direction="evidenced_unrelated"),
            facts(operator="different_operator", direction="no_evidence"),
            facts(findings=[finding("agree")]),
            facts(findings=[finding("conflict")]),
            facts(),
        ):
            verdict, reasons, trace = decide(fact_set)
            self.assertIn(verdict, ("match", "mismatch", "parked", "uncertain"))
            self.assertTrue(reasons and not set(reasons) - REASONS)
            self.assertEqual(reasons, sorted(reasons))
            traces.add(trace)
        self.assertEqual(len(traces), 8)

    def test_derivation_is_deterministic_and_versioned(self):
        fact_set = facts(findings=[finding("agree")])
        self.assertEqual(decide(fact_set), decide(dict(fact_set)))
        self.assertEqual(DECISION_VERSION, "decision-v2")


if __name__ == "__main__":
    unittest.main()


class ConflictingIdentifierTests(unittest.TestCase):
    """decision-v2: cited contradictions on two distinct fields are positive evidence."""

    def different(self, findings, version="decision-v2"):
        return decide(
            facts(operator="different_operator", direction="no_evidence", findings=findings),
            version,
        )

    def test_conflicts_on_two_fields_reach_mismatch(self):
        verdict, reasons, trace = self.different(
            [finding("conflict", "phones"), finding("conflict", "locations", 0, "bundle:p3")]
        )
        self.assertEqual(verdict, "mismatch")
        self.assertEqual(reasons, ["conflicting_identity"])
        self.assertEqual(trace, "stage2:different_operator/conflicting_identifiers")

    def test_one_conflict_or_two_on_the_same_field_stay_uncertain(self):
        for findings in (
            [finding("conflict", "phones")],
            [finding("conflict", "phones", 0), finding("conflict", "phones", 1, "bundle:p3")],
            [finding("conflict", "phones"), finding("absent", "locations")],
        ):
            with self.subTest(findings=findings):
                verdict, _, trace = self.different(findings)
                self.assertEqual(verdict, "uncertain")
                self.assertEqual(trace, "stage2:different_operator/no_evidence")

    def test_website_derived_conflicts_do_not_count(self):
        derived = {
            **finding("conflict", "locations", 0, "bundle:p3"),
            "dependence": "website_derived",
        }
        verdict, _, trace = self.different([finding("conflict", "phones"), derived])
        self.assertEqual((verdict, trace), ("uncertain", "stage2:different_operator/no_evidence"))
        unknown = {**derived, "dependence": "unknown"}
        self.assertEqual(self.different([finding("conflict", "phones"), unknown])[0], "mismatch")

    def test_any_agreement_defers_to_stage_three(self):
        verdict, _, trace = self.different(
            [
                finding("conflict", "phones"),
                finding("conflict", "locations", 0, "bundle:p3"),
                finding("agree", "social_urls", 0, "bundle:p4"),
            ]
        )
        self.assertEqual((verdict, trace), ("uncertain", "stage2:different_operator/no_evidence"))

    def test_evidenced_continuity_still_short_circuits(self):
        verdict, _, trace = decide(
            facts(
                operator="different_operator",
                direction="evidenced_continuity",
                findings=[
                    finding("conflict", "phones"),
                    finding("conflict", "locations", 0, "bundle:p3"),
                ],
            ),
            "decision-v2",
        )
        self.assertEqual((verdict, trace), ("uncertain", "stage3:conflict_only"))

    def test_decision_v1_keeps_its_behavior(self):
        findings = [finding("conflict", "phones"), finding("conflict", "locations", 0, "bundle:p3")]
        verdict, _, trace = self.different(findings, "decision-v1")
        self.assertEqual((verdict, trace), ("uncertain", "stage2:different_operator/no_evidence"))
        with self.assertRaises(ValueError):
            decide(facts(), "decision-v3")

    def test_other_rows_are_identical_across_revisions(self):
        for fact_set in (
            facts(substance="parked"),
            facts(operator="indeterminate"),
            facts(operator="different_operator", direction="evidenced_unrelated"),
            facts(operator="different_operator", direction="no_evidence"),
            facts(findings=[finding("agree")]),
            facts(findings=[finding("conflict")]),
            facts(),
        ):
            self.assertEqual(decide(fact_set, "decision-v1"), decide(fact_set, "decision-v2"))
