import unittest
from decimal import Decimal

from pramana.cli import synthetic_cases
from pramana.contracts import validate_case
from pramana.evaluation import grouped_split, reference_metrics
from pramana.measurement import api_equivalent_cost, unavailable_usage, validate_usage


class MeasurementTests(unittest.TestCase):
    def test_inclusive_counters_and_missingness(self):
        prices = {
            "version": "synthetic-v1",
            "effective_date": "2026-09-21",
            "source_url": "https://example.test/prices",
            "currency": "USD",
            "model": "synthetic",
            "provider": "synthetic",
            "input_per_million": 2,
            "cached_per_million": 1,
            "output_per_million": 3,
        }
        usage = {
            **unavailable_usage(),
            "usage_status": "reported",
            "input_tokens": 100,
            "cached_input_tokens": 40,
            "output_tokens": 30,
            "reasoning_tokens": 20,
            "cached_in_input": True,
            "reasoning_in_output": True,
        }
        self.assertEqual(api_equivalent_cost(usage, prices), Decimal("0.00025"))
        self.assertIsNone(api_equivalent_cost(unavailable_usage(), prices))
        usage["cached_input_tokens"] = 101
        with self.assertRaises(ValueError):
            validate_usage(usage)

    def test_metrics_keep_failures_and_uncertain_separate(self):
        result = reference_metrics(
            [("mismatch", "match"), ("match", "uncertain"), ("uncertain", "uncertain")], 4
        )
        self.assertEqual(result["false_match_rate"]["value"], 1)
        self.assertEqual(result["false_rejection_rate"]["value"], 0)
        self.assertEqual(result["end_to_end_coverage"]["value"], 0.75)
        self.assertEqual(result["failure_rate"]["value"], 0.25)
        self.assertIsNone(reference_metrics([], 0)["end_to_end_coverage"]["value"])

    def test_connected_families_and_synthetic_pairs_never_leak(self):
        cases = [validate_case(c) for c in synthetic_cases(6)]
        cases[1]["corporate_families"] = ["family_a"]
        cases[2]["corporate_families"] = ["family_a"]
        cases[4]["synthetic_source_company_ids"] = [cases[2]["company"]["company_id"]]
        result = grouped_split(cases)
        self.assertEqual(len(set(result["assignments"].values())), 1)
        self.assertEqual(result["assignments"], grouped_split(reversed(cases))["assignments"])
