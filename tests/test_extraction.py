import unittest
from pathlib import Path

from pramana.contracts import default_config
from pramana.extraction import extract


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.policy = default_config()["collection"]
        self.body = (Path(__file__).parent / "fixtures/company.html").read_bytes()

    def test_deterministic_rich_evidence(self):
        page = extract(self.body, "https://example.test/", self.policy)
        self.assertEqual(page, extract(self.body, "https://example.test/", self.policy))
        values = [e["value"] for e in page["elements"]]
        self.assertFalse(any("Ignore all" in v for v in values))
        self.assertTrue(any("Other Example Corporation" in v for v in values))
        self.assertEqual(
            {v["source_type"] for v in page["logos"]}, {"icon", "header_logo", "organization_logo"}
        )
        self.assertFalse(any("generic-preview" in str(v) for v in page["logos"]))
        self.assertIn(
            {"category": "about", "url": "https://example.test/business/about"}, page["links"]
        )
        self.assertTrue(all(e["page_id"] == page["page_id"] for e in page["elements"]))

    def test_caps_malformed_and_unsupported(self):
        page = extract(
            b"<h1>" + b"x" * 1000, "https://example.test/", {**self.policy, "page_chars": 40}
        )
        self.assertLessEqual(page["retained_characters"], 40)
        self.assertTrue(page["truncated"])
        self.assertTrue(
            extract(b"%PDF", "https://example.test/", self.policy, "application/pdf")[
                "unsupported_media"
            ]
        )

    def test_logo_dedup_cap_and_no_image_fetch(self):
        body = b'<link rel="icon" href="/a"><link rel="icon" href="/a"><link rel="icon" href="/b">'
        page = extract(body, "https://example.test/", {**self.policy, "page_logos": 1})
        self.assertEqual(len(page["logos"]), 1)
        self.assertEqual(page["counts"]["logo"]["truncated"], 1)
