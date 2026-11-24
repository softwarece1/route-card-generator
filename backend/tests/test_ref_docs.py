"""Unit tests for reference-document normalize / extract / filename rules."""

import unittest

from fastapi import HTTPException

from app.route_card.ref_docs import (
    extract_candidate_codes,
    normalize_doc_code,
    normalize_folder_code,
    parse_upload_filename,
)


class TestNormalize(unittest.TestCase):
    def test_folder_code(self):
        self.assertEqual(normalize_folder_code("ps"), "PS")
        self.assertEqual(normalize_folder_code(" DS "), "DS")
        self.assertEqual(normalize_folder_code("sop1"), "SOP")
        self.assertEqual(normalize_folder_code(""), "")

    def test_doc_code_variants(self):
        self.assertEqual(normalize_doc_code("PS", "PS200"), "PS200")
        self.assertEqual(normalize_doc_code("PS", "ps 200"), "PS200")
        self.assertEqual(normalize_doc_code("PS", "PS-0200"), "PS200")
        self.assertEqual(normalize_doc_code("PS", "PS0200.pdf"), "PS200")
        self.assertEqual(normalize_doc_code("PS", "200"), "PS200")
        self.assertIsNone(normalize_doc_code("PS", "DS200"))
        self.assertIsNone(normalize_doc_code("PS", "ITEM28"))


class TestExtract(unittest.TestCase):
    def test_extract_known_folders_only(self):
        text = (
            "INSTALLATION TORQUE AS PER PS902. "
            "CLEAN SURFACES. See SS 10 and ITEM 28. Also as per ps-200."
        )
        codes = extract_candidate_codes(text, {"PS", "SS"})
        self.assertEqual(codes, ["PS902", "SS10", "PS200"])

    def test_no_folders_yields_empty(self):
        self.assertEqual(extract_candidate_codes("as per PS200", []), [])


class TestFilename(unittest.TestCase):
    def test_accept_pdf(self):
        self.assertEqual(parse_upload_filename("PS", "PS200.pdf"), "PS200")
        self.assertEqual(parse_upload_filename("PS", "ps-0200.PDF"), "PS200")

    def test_reject_non_pdf(self):
        with self.assertRaises(HTTPException) as ctx:
            parse_upload_filename("PS", "PS200.docx")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_reject_wrong_prefix(self):
        with self.assertRaises(HTTPException) as ctx:
            parse_upload_filename("PS", "DS200.pdf")
        self.assertEqual(ctx.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
