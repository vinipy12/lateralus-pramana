import json
import tempfile
import unittest

from pramana.agents import SyntheticRuntime
from pramana.cli import synthetic_cases
from pramana.collection import SyntheticCollector
from pramana.contracts import ContractError, default_config, validate_reference_label
from pramana.orchestration import Pipeline
from pramana.reporting import export, summary
from pramana.review import review_packets
from pramana.storage import Store


def label(case_id="case_00000000", verdict="match", reviewer="reviewer_a", **overrides):
    return {
        "case_id": case_id,
        "verdict": verdict,
        "reviewer": reviewer,
        "origin": "independent_human",
        "blind": True,
        "rationale": "Reviewed the frozen evidence independently.",
        "recorded": "2026-09-22T00:00:00+00:00",
        "evidence_scope": "packet",
        **overrides,
    }


class ReferenceLabelContractTests(unittest.TestCase):
    ids = {"case_00000000"}

    def test_the_reviewer_supplies_when_the_label_was_produced(self):
        stored = validate_reference_label(label(), self.ids)
        self.assertEqual(stored["recorded"], "2026-09-22T00:00:00+00:00")
        self.assertEqual(stored["verdict"], "match")
        missing = label()
        del missing["recorded"]
        with self.assertRaises(ContractError):
            validate_reference_label(missing, self.ids)

    def test_invalid_labels_are_rejected(self):
        for broken in (
            {"verdict": "invented"},
            {"origin": "intended_negative"},
            {"blind": "yes"},
            {"reviewer": "  "},
            {"rationale": ""},
            {"case_id": "case_99999999"},
            {"recorded": "not-a-date"},
            {"origin": "owner_review", "blind": True},
            {"evidence_scope": "google"},
            {"evidence_scope": None},
        ):
            with self.subTest(broken=broken), self.assertRaises(ContractError):
                validate_reference_label(label(**broken), self.ids)
        with self.assertRaises(ContractError):
            validate_reference_label({**label(), "extra": 1}, self.ids)
        missing = label()
        del missing["blind"]
        with self.assertRaises(ContractError):
            validate_reference_label(missing, self.ids)

    def test_a_sighted_owner_review_is_accepted(self):
        stored = validate_reference_label(label(origin="owner_review", blind=False), self.ids)
        self.assertEqual(stored["origin"], "owner_review")


class ReferenceReportingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name, "synthetic")
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.store.close)
        config = default_config()
        self.store.import_cases("run", synthetic_cases(4), config)
        collector = SyntheticCollector(self.store.artifacts, config["collection"])
        await Pipeline(self.store, collector, SyntheticRuntime(0.01)).run("run")

    def test_labels_append_and_repeated_imports_are_idempotent(self):
        first = self.store.import_reference_labels("run", [label(), label("case_00000001")])
        self.assertEqual(first, {"accepted": 2, "duplicates": 0})
        again = self.store.import_reference_labels("run", [label()])
        self.assertEqual(again, {"accepted": 0, "duplicates": 1})
        changed = self.store.import_reference_labels("run", [label(verdict="uncertain")])
        self.assertEqual(changed, {"accepted": 1, "duplicates": 0})
        rows = [r for r in self.store.reference_labels("run") if r["case_id"] == "case_00000000"]
        self.assertEqual([r["sequence"] for r in rows], [1, 2])
        self.assertEqual([r["verdict"] for r in rows], ["match", "uncertain"])
        self.assertTrue(self.store.verify("run"))

    def test_recorded_labels_are_immutable(self):
        self.store.import_reference_labels("run", [label()])
        with self.assertRaises(Exception):
            self.store.db.execute("UPDATE reference_labels SET verdict='match'")

    def test_a_run_without_labels_keeps_its_report_version(self):
        report = summary(self.store, "run")
        self.assertEqual(report["report_version"], "v4")
        self.assertNotIn("reference_agreement", report)

    def test_only_blind_independent_labels_reach_the_baseline(self):
        self.store.import_reference_labels(
            "run",
            [
                label(verdict="match"),
                label("case_00000001", "uncertain", "reviewer_b"),
                label("case_00000002", "match", "reviewer_c", origin="owner_review", blind=False),
                label("case_00000003", "match", "reviewer_d", evidence_scope="open_web"),
            ],
        )
        report = summary(self.store, "run")
        block = report["reference_agreement"]
        self.assertEqual(report["report_version"], "v6")
        self.assertEqual(report["reference_origin"], "independent_human")
        self.assertEqual(block["baseline_labels"], 3)
        self.assertEqual(block["reviewers"], 4)
        self.assertEqual(
            block["label_counts"],
            {
                "blind": 3,
                "origin:independent_human": 3,
                "origin:owner_review": 1,
                "scope:open_web": 1,
                "scope:packet": 3,
                "sighted": 1,
            },
        )
        packet, open_web = block["scopes"]["packet"], block["scopes"]["open_web"]
        self.assertEqual((packet["baseline_labels"], open_web["baseline_labels"]), (2, 1))
        # Every synthetic case derives uncertain, so one reviewer agrees and one does not.
        self.assertEqual(packet["confusion_matrix"]["match"]["uncertain"], 1)
        self.assertEqual(packet["confusion_matrix"]["uncertain"]["uncertain"], 1)
        self.assertEqual(open_web["confusion_matrix"]["match"]["uncertain"], 1)
        self.assertEqual(packet["confusion_matrix"]["match"]["match"], 0)
        self.assertEqual(
            packet["false_rejection_rate"], {"numerator": 0, "denominator": 1, "value": 0.0}
        )
        self.assertEqual(packet["decisive_coverage"]["value"], 0.0)
        self.assertEqual(block["blind_labels_recorded_after_run_ended"], 0)
        late = summary(self.store, "run")
        self.store.import_reference_labels(
            "run",
            [label("case_00000001", "match", "reviewer_d", recorded="2099-01-01T00:00:00+00:00")],
        )
        self.assertEqual(
            summary(self.store, "run")["reference_agreement"][
                "blind_labels_recorded_after_run_ended"
            ],
            1,
        )
        self.assertEqual(late["reference_agreement"]["blind_labels_recorded_after_run_ended"], 0)

    def test_export_is_reproducible_and_versioned_alongside_the_earlier_one(self):
        before, root = export(self.store, "run")
        self.store.import_reference_labels("run", [label()])
        after, _ = export(self.store, "run")
        self.assertEqual(before["report_version"], "v4")
        self.assertEqual(after["report_version"], "v6")
        self.assertEqual(after, export(self.store, "run")[0])
        self.assertTrue(list(root.glob("summary-v4-*.json")))
        self.assertTrue(list(root.glob("summary-v6-*.json")))
        markdown = next(root.glob("report-v6-*.md")).read_text()
        self.assertIn("Reference baseline", markdown)
        self.assertIn("not real-world accuracy", markdown)
        self.assertIn("Scopes are never pooled", markdown)

    def test_labels_for_unassessed_cases_stay_out_of_the_matrix(self):
        self.store.db.execute(
            "UPDATE cases SET state='not_assessed',final=NULL WHERE id=?", ("case_00000000",)
        )
        self.store.db.commit()
        self.store.import_reference_labels("run", [label(verdict="parked")])
        block = summary(self.store, "run")["reference_agreement"]
        self.assertEqual(block["baseline_labels"], 0)
        self.assertEqual(block["labels_without_derived_verdict"], 1)
        self.assertIsNone(block["scopes"]["packet"]["false_match_rate"]["value"])


if __name__ == "__main__":
    unittest.main()


class ReviewPacketTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name, "synthetic")
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.store.close)
        self.config = default_config()
        self.store.import_cases("run", synthetic_cases(4), self.config)
        collector = SyntheticCollector(self.store.artifacts, self.config["collection"])
        await Pipeline(self.store, collector, SyntheticRuntime(0.01)).run("run", collect_only=True)

    def test_packets_carry_evidence_and_withhold_every_answer(self):
        root, count = review_packets(self.store, "run", "reviewer_a")
        self.assertEqual(count, 4)
        packets = [json.loads(line) for line in (root / "packets.jsonl").read_text().splitlines()]
        self.assertEqual(len(packets), 4)
        for entry in packets:
            self.assertEqual(
                set(entry),
                {
                    "packet_version",
                    "case_id",
                    "candidate_url",
                    "bundle_id",
                    "company",
                    "evidence",
                    "withheld",
                    "verdict_guide",
                },
            )
            body = {k: v for k, v in entry.items() if k not in ("withheld", "verdict_guide")}
            raw = json.dumps(body)
            for leak in (
                "stratum",
                "synthetic_mismatch",
                "source_record_reference",
                "partition",
                "reason_codes",
                "rationale",
                "assessment",
                "corroboration",
                "identifier_findings",
            ):
                self.assertNotIn(leak, raw)
            self.assertNotIn("verdict", raw)
            self.assertTrue(entry["evidence"]["passages"])
            self.assertEqual(set(entry["company"]), {"fields", "limitations"})
            self.assertIn("Absence of evidence is uncertain", entry["verdict_guide"])

    def test_packets_are_written_before_any_assessment_exists(self):
        self.assertEqual(
            [
                r[0]
                for r in self.store.db.execute("SELECT DISTINCT state FROM cases WHERE run='run'")
            ],
            ["labeling"],
        )
        review_packets(self.store, "run", "reviewer_a")
        self.assertFalse(
            self.store.db.execute("SELECT count(*) FROM labels WHERE run='run'").fetchone()[0]
        )

    def test_the_template_imports_once_filled_in(self):
        root, _ = review_packets(self.store, "run", "reviewer_a")
        rows = [
            json.loads(line) for line in (root / "labels-template.jsonl").read_text().splitlines()
        ]
        self.assertTrue(
            all(
                r["blind"]
                and r["origin"] == "independent_human"
                and r["evidence_scope"] == "packet"
                for r in rows
            )
        )
        with self.assertRaises(ContractError):
            self.store.import_reference_labels("run", rows[:1])
        filled = [
            {
                **row,
                "verdict": "uncertain",
                "rationale": "No operator evidence.",
                "recorded": "2026-09-22T00:00:00+00:00",
            }
            for row in rows
        ]
        self.assertEqual(
            self.store.import_reference_labels("run", filled), {"accepted": 4, "duplicates": 0}
        )

    def test_packet_order_is_seeded_and_stable(self):
        root, _ = review_packets(self.store, "run", "reviewer_a")
        first = (root / "packets.jsonl").read_text()
        self.assertEqual(review_packets(self.store, "run", "reviewer_a")[0], root)
        self.assertEqual((root / "packets.jsonl").read_text(), first)
        ids = [json.loads(line)["case_id"] for line in first.splitlines()]
        self.assertNotEqual(ids, sorted(ids))
