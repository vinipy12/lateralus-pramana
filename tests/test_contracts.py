import copy
import unittest

from pramana.cli import synthetic_cases
from pramana.contracts import (
    ContractError,
    blinded_company,
    default_config,
    digest,
    normalize_url,
    validate_case,
    validate_config,
)


class ContractTests(unittest.TestCase):
    def test_canonical_hash(self):
        self.assertEqual(digest({"á": 2, "a": 1}), digest({"a": 1, "á": 2}))
        with self.assertRaises(ValueError):
            digest(float("nan"))

    def test_provenance_required_and_hidden(self):
        raw = next(synthetic_cases(1))
        case = validate_case(raw)
        blinded = blinded_company(case["company"])
        self.assertNotIn("source", str(blinded))
        del raw["company"]["provenance"]["name"]
        with self.assertRaises(ContractError):
            validate_case(raw)

    def test_url_identity_preserves_semantics(self):
        self.assertEqual(
            normalize_url("BÜCHER.example/a?q=X#fragment"), "https://xn--bcher-kva.example/a?q=X"
        )
        self.assertNotEqual(normalize_url("example.test/a"), normalize_url("example.test/b"))
        for url in (
            "http://127.0.0.1",
            "http://169.254.169.254/",
            "https://user:pass@example.test/",
            "ftp://example.test",
            "http://[::1]",
            "http://example.test:8080",
            "https://localhost",
        ):
            with self.subTest(url=url), self.assertRaises(ContractError):
                normalize_url(url)

    def test_configuration_rejects_silent_changes(self):
        config = default_config()
        validate_config(config)
        changed = copy.deepcopy(config)
        changed["concurrency"]["judge"] = 0
        with self.assertRaises(ContractError):
            validate_config(changed)
