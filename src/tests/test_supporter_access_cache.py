from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from infra import supporter_access_cache


class SupporterAccessCacheStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.active = self.root / "legacy" / "supporter_access_cache.json"
        self.shared = self.root / "local" / "BonkScanner" / "supporter_access_cache.json"
        self.active.parent.mkdir(parents=True)
        self.shared.parent.mkdir(parents=True)

    def test_legacy_profile_reads_existing_shared_cache_when_active_cache_is_absent(self) -> None:
        payload = {"allowed": True, "supporter_id": "synthetic"}
        self.shared.write_text(json.dumps(payload), encoding="utf-8")
        with patch.object(
            supporter_access_cache, "default_cache_path", return_value=self.active
        ), patch.object(
            supporter_access_cache,
            "_legacy_shared_cache_path",
            return_value=self.shared,
        ):
            self.assertEqual(payload, supporter_access_cache.read_access_cache())

    def test_active_legacy_cache_wins_over_old_shared_cache(self) -> None:
        self.active.write_text('{"source":"active"}', encoding="utf-8")
        self.shared.write_text('{"source":"shared"}', encoding="utf-8")
        with patch.object(
            supporter_access_cache, "default_cache_path", return_value=self.active
        ), patch.object(
            supporter_access_cache,
            "_legacy_shared_cache_path",
            return_value=self.shared,
        ):
            self.assertEqual(
                {"source": "active"}, supporter_access_cache.read_access_cache()
            )

    def test_default_delete_removes_active_and_legacy_shared_cache(self) -> None:
        self.active.write_text("{}", encoding="utf-8")
        self.shared.write_text("{}", encoding="utf-8")
        with patch.object(
            supporter_access_cache, "default_cache_path", return_value=self.active
        ), patch.object(
            supporter_access_cache,
            "_legacy_shared_cache_path",
            return_value=self.shared,
        ):
            supporter_access_cache.delete_access_cache()
        self.assertFalse(self.active.exists())
        self.assertFalse(self.shared.exists())


if __name__ == "__main__":
    unittest.main()
