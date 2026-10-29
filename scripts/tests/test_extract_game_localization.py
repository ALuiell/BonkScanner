"""Offline checks for extraction fidelity and the checked-in catalogs."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("extract_game_localization", ROOT / "scripts/extract_game_localization.py")
extractor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(extractor)


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.entry_id = 9007199254740993  # Must survive JavaScript consumers exactly.
        self.shared, self.paths = extractor.extract_shared([(7, {
            "m_TableCollectionName": "Stats",
            "m_TableCollectionNameGuidString": "test-guid",
            "m_Entries": [
                {"m_Id": self.entry_id, "m_Key": "Damage_NAME"},
                {"m_Id": 2, "m_Key": "EMPTY"},
                {"m_Id": 3, "m_Key": "MISSING"},
            ],
        })])
        self.data = {
            "m_Name": "Stats_uk",
            "m_LocaleId": {"m_Code": "uk"},
            "m_SharedData": {"m_PathID": 7},
            "m_Metadata": {"m_Items": [{"rid": 100}]},
            "references": {"RefIds": [{
                "rid": 100,
                "type": {
                    "class": "SmartFormatTag",
                    "ns": "UnityEngine.Localization.Metadata",
                    "asm": "Unity.Localization",
                },
                "data": {"m_Entries": [self.entry_id]},
            }]},
            "m_TableData": [
                {"m_Id": self.entry_id, "m_Localized": " Шкода {value1}\n<b>é</b> ", "m_Metadata": {"m_Items": []}},
                {"m_Id": 2, "m_Localized": "", "m_Metadata": {"m_Items": []}},
            ],
        }

    def extract(self, data=None):
        return extractor.extract_locale([(1, data or self.data)], "uk", self.shared, self.paths)

    def test_preserves_unicode_whitespace_markup_placeholders_and_large_ids(self):
        entries = self.extract()["tables"]["Stats"]["entries"]
        self.assertEqual(entries["Damage_NAME"]["text"], " Шкода {value1}\n<b>é</b> ")
        self.assertEqual(entries["Damage_NAME"]["id"], str(self.entry_id))
        self.assertEqual(json.loads(extractor._json_bytes(self.extract())), self.extract())

    def test_keeps_empty_and_absent_entries_distinct_without_fallback(self):
        catalog = self.extract()
        entries = catalog["tables"]["Stats"]["entries"]
        self.assertEqual(entries["EMPTY"]["text"], "")
        self.assertNotIn("MISSING", entries)
        report = extractor.coverage(catalog, self.shared)
        self.assertEqual([entry["key"] for entry in report["missing_entries"]], ["MISSING"])
        self.assertEqual([entry["key"] for entry in report["empty_entries"]], ["EMPTY"])

    def test_table_smart_tag_applies_only_to_listed_entries(self):
        entries = self.extract()["tables"]["Stats"]["entries"]
        self.assertTrue(entries["Damage_NAME"]["smart"])
        self.assertFalse(entries["EMPTY"]["smart"])

    def test_entry_smart_tag_is_also_preserved(self):
        data = deepcopy(self.data)
        data["m_Metadata"]["m_Items"] = []
        data["m_TableData"][0]["m_Metadata"]["m_Items"] = [{"rid": 100}]
        self.assertTrue(self.extract(data)["tables"]["Stats"]["entries"]["Damage_NAME"]["smart"])

    def test_rejects_wrong_locale_and_wrong_shared_table(self):
        for field, value in (("m_LocaleId", {"m_Code": "ru"}), ("m_Name", "Weapons_uk")):
            with self.subTest(field=field):
                data = deepcopy(self.data)
                data[field] = value
                with self.assertRaises(ValueError):
                    self.extract(data)

    def test_rejects_duplicate_or_unknown_ids_instead_of_overwriting(self):
        duplicate = deepcopy(self.data)
        duplicate["m_TableData"].append(duplicate["m_TableData"][0])
        with self.assertRaises(ValueError):
            self.extract(duplicate)
        unknown = deepcopy(self.data)
        unknown["m_TableData"][0]["m_Id"] = 999
        with self.assertRaises(KeyError):
            self.extract(unknown)

    def test_rejects_unsupported_metadata_and_missing_tables(self):
        data = deepcopy(self.data)
        data["references"]["RefIds"][0]["type"]["class"] = "UnknownTag"
        with self.assertRaises(ValueError):
            self.extract(data)
        with self.assertRaises(ValueError):
            extractor.extract_locale([], "uk", self.shared, self.paths)


class ExportedCatalogTests(unittest.TestCase):
    def test_all_seven_catalogs_match_manifest_hashes_keys_and_coverage(self):
        directory = ROOT / "src/media/localization/game"
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        shared = json.loads((directory / "shared.json").read_text(encoding="utf-8"))["tables"]
        self.assertEqual(set(manifest["locales"]), set(extractor.LANGUAGES))
        for name, record in manifest["outputs"].items():
            with self.subTest(file=name):
                data = (directory / name).read_bytes()
                self.assertEqual(len(data), record["bytes"])
                self.assertEqual(hashlib.sha256(data).hexdigest(), record["sha256"])
        for code in extractor.LANGUAGES:
            with self.subTest(locale=code):
                catalog = json.loads((directory / f"{code}.json").read_text(encoding="utf-8"))
                self.assertEqual(catalog["locale"], code)
                self.assertEqual(set(catalog["tables"]), set(shared))
                for name, table in catalog["tables"].items():
                    self.assertEqual(table["collection_guid"], shared[name]["collection_guid"])
                    for key, entry in table["entries"].items():
                        self.assertEqual(entry["id"], shared[name]["entries"][key])
                for key, value in extractor.coverage(catalog, shared).items():
                    self.assertEqual(manifest["locales"][code][key], value)


if __name__ == "__main__":
    unittest.main()
