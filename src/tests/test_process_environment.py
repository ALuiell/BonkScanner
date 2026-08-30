from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import src  # noqa: F401 -- path bootstrap

from core.run_verifier import environment_digest
from infra.process_environment import scan_process_environment


class _FakeMemory:
    def __init__(self, modules, regions=()) -> None:
        self._modules = tuple(modules)
        self._regions = tuple(regions)

    def loaded_modules(self):
        return self._modules

    def private_executable_regions(self):
        return self._regions


class ProcessEnvironmentTests(unittest.TestCase):
    def test_empty_module_scan_is_unavailable_instead_of_clean(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "returned no modules"):
            scan_process_environment(_FakeMemory(()))

    def test_scan_finds_loaders_and_does_not_serialize_absolute_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            game = root / "Megabonk.exe"
            assembly = root / "GameAssembly.dll"
            proxy = root / "winhttp.dll"
            plugin = root / "BepInEx" / "plugins" / "SamplePlugin.dll"
            plugin.parent.mkdir(parents=True)
            game.write_bytes(b"game")
            assembly.write_bytes(b"assembly")
            proxy.write_bytes(b"proxy loader")
            plugin.write_bytes(b"managed plugin")
            modules = (
                SimpleNamespace(
                    name=game.name,
                    filename=str(game),
                    base_address=0x140000000,
                    size=game.stat().st_size,
                ),
                SimpleNamespace(
                    name=assembly.name,
                    filename=str(assembly),
                    base_address=0x180000000,
                    size=assembly.stat().st_size,
                ),
                SimpleNamespace(
                    name=proxy.name,
                    filename=str(proxy),
                    base_address=0x190000000,
                    size=proxy.stat().st_size,
                ),
            )

            snapshot = scan_process_environment(_FakeMemory(modules))

            by_name = {module["name"]: module for module in snapshot["modules"]}
            self.assertEqual(by_name["Megabonk.exe"]["classification"], "game")
            self.assertEqual(by_name["GameAssembly.dll"]["classification"], "game")
            self.assertEqual(by_name["winhttp.dll"]["classification"], "mod_loader")
            artifact_paths = {artifact["path"] for artifact in snapshot["artifacts"]}
            self.assertIn("winhttp.dll", artifact_paths)
            self.assertIn("BepInEx", artifact_paths)
            self.assertIn("BepInEx/plugins/SamplePlugin.dll", artifact_paths)
            self.assertEqual(
                snapshot["digest"],
                environment_digest(
                    snapshot["modules"],
                    snapshot["artifacts"],
                    snapshot["private_executable_regions"],
                ),
            )
            serialized = json.dumps(snapshot)
            self.assertNotIn(str(root), serialized)
            self.assertNotIn(str(root).replace("\\", "/"), serialized)

    def test_known_overlay_is_not_classified_as_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            game = root / "Game" / "Megabonk.exe"
            overlay = root / "Overlay" / "gameoverlayrenderer64.dll"
            game.parent.mkdir()
            overlay.parent.mkdir()
            game.write_bytes(b"game")
            overlay.write_bytes(b"overlay")
            with patch.dict(os.environ, {"ProgramFiles": str(root)}):
                snapshot = scan_process_environment(
                    _FakeMemory(
                        (
                            SimpleNamespace(
                                name=game.name,
                                filename=str(game),
                                base_address=1,
                                size=4,
                            ),
                            SimpleNamespace(
                                name=overlay.name,
                                filename=str(overlay),
                                base_address=2,
                                size=7,
                            ),
                        )
                    )
                )

        overlay_row = next(
            module for module in snapshot["modules"] if module["name"] == overlay.name
        )
        self.assertEqual(overlay_row["classification"], "known_overlay")
        self.assertIsNone(overlay_row["sha256"])

    def test_observed_stock_game_and_platform_modules_are_not_reported_as_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            game_dir = root / "Game"
            runtime_dir = root / "Runtime"
            game_dir.mkdir()
            runtime_dir.mkdir()
            paths = (
                game_dir / "Megabonk.exe",
                game_dir / "discord_game_sdk.dll",
                game_dir / "Rewired_WindowsGamingInput.dll",
                runtime_dir / "steamclient64.dll",
                runtime_dir / "tier0_s64.dll",
                runtime_dir / "vstdlib_s64.dll",
                runtime_dir / "MpOav.dll",
                runtime_dir / "OWExplorer.dll",
                runtime_dir / "OWUtils.dll",
            )
            for path in paths:
                path.write_bytes(path.name.encode("ascii"))
            snapshot = scan_process_environment(
                _FakeMemory(
                    tuple(
                        SimpleNamespace(
                            name=path.name,
                            filename=str(path),
                            base_address=index + 1,
                            size=path.stat().st_size,
                        )
                        for index, path in enumerate(paths)
                    )
                )
            )

        by_name = {module["name"]: module for module in snapshot["modules"]}
        self.assertEqual(by_name["discord_game_sdk.dll"]["classification"], "game")
        self.assertEqual(
            by_name["Rewired_WindowsGamingInput.dll"]["classification"], "game"
        )
        for name in (
            "steamclient64.dll",
            "tier0_s64.dll",
            "vstdlib_s64.dll",
            "OWExplorer.dll",
            "OWUtils.dll",
        ):
            self.assertEqual(by_name[name]["classification"], "known_overlay")
            self.assertIsNone(by_name[name]["sha256"])
        self.assertEqual(by_name["MpOav.dll"]["classification"], "system")
        self.assertIsNone(by_name["MpOav.dll"]["sha256"])

    def test_overlay_name_inside_game_directory_is_not_implicitly_trusted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            game = root / "Megabonk.exe"
            spoof = root / "gameoverlayrenderer64.dll"
            game.write_bytes(b"game")
            spoof.write_bytes(b"spoof")
            snapshot = scan_process_environment(
                _FakeMemory(
                    (
                        SimpleNamespace(
                            name=game.name,
                            filename=str(game),
                            base_address=1,
                            size=4,
                        ),
                        SimpleNamespace(
                            name=spoof.name,
                            filename=str(spoof),
                            base_address=2,
                            size=5,
                        ),
                    )
                )
            )

        spoof_row = next(
            module for module in snapshot["modules"] if module["name"] == spoof.name
        )
        self.assertEqual(spoof_row["classification"], "unknown")
        self.assertIsNotNone(spoof_row["sha256"])

    def test_total_hash_budget_bounds_work_for_many_suspicious_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            game = root / "Megabonk.exe"
            proxy = root / "winhttp.dll"
            game.write_bytes(b"game")
            proxy.write_bytes(b"larger than the test budget")
            modules = (
                SimpleNamespace(
                    name=game.name,
                    filename=str(game),
                    base_address=1,
                    size=4,
                ),
                SimpleNamespace(
                    name=proxy.name,
                    filename=str(proxy),
                    base_address=2,
                    size=proxy.stat().st_size,
                ),
            )

            with patch("infra.process_environment.MAX_TOTAL_HASH_BYTES", 4):
                snapshot = scan_process_environment(_FakeMemory(modules))

        proxy_module = next(
            module for module in snapshot["modules"] if module["name"] == proxy.name
        )
        proxy_artifact = next(
            artifact for artifact in snapshot["artifacts"] if artifact["path"] == proxy.name
        )
        self.assertIsNone(proxy_module["sha256"])
        self.assertIsNone(proxy_artifact["sha256"])

    def test_hash_cache_does_not_change_which_files_fit_the_budget(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            game = root / "Megabonk.exe"
            proxy = root / "winhttp.dll"
            plugin = root / "BepInEx" / "plugins" / "Later.dll"
            plugin.parent.mkdir(parents=True)
            game.write_bytes(b"game")
            proxy.write_bytes(b"load")
            plugin.write_bytes(b"plug")
            modules = (
                SimpleNamespace(
                    name=game.name,
                    filename=str(game),
                    base_address=1,
                    size=4,
                ),
                SimpleNamespace(
                    name=proxy.name,
                    filename=str(proxy),
                    base_address=2,
                    size=4,
                ),
            )

            with patch("infra.process_environment.MAX_TOTAL_HASH_BYTES", 4):
                first = scan_process_environment(_FakeMemory(modules))
                second = scan_process_environment(_FakeMemory(modules))

        self.assertEqual(first["digest"], second["digest"])
        first_plugin = next(
            artifact for artifact in first["artifacts"] if artifact["path"].endswith("Later.dll")
        )
        second_plugin = next(
            artifact for artifact in second["artifacts"] if artifact["path"].endswith("Later.dll")
        )
        self.assertIsNone(first_plugin["sha256"])
        self.assertIsNone(second_plugin["sha256"])

    def test_private_executable_region_is_portable_and_has_no_raw_address(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            game = Path(directory) / "Megabonk.exe"
            game.write_bytes(b"game")
            snapshot = scan_process_environment(
                _FakeMemory(
                    (
                        SimpleNamespace(
                            name=game.name,
                            filename=str(game),
                            base_address=0x140000000,
                            size=4,
                        ),
                    ),
                    regions=(
                        SimpleNamespace(
                            base_address=0x12345000,
                            allocation_base=0x12340000,
                            size=0x3000,
                            protection=0x140,
                        ),
                    ),
                )
            )

        self.assertEqual(len(snapshot["private_executable_regions"]), 1)
        row = snapshot["private_executable_regions"][0]
        self.assertEqual(row["size"], 0x3000)
        self.assertEqual(row["protection"], 0x40)
        self.assertTrue(row["writable"])
        self.assertTrue(row["guarded"])
        serialized = json.dumps(snapshot)
        self.assertNotIn("12345000", serialized)
        self.assertNotIn("12340000", serialized)


if __name__ == "__main__":
    unittest.main()
