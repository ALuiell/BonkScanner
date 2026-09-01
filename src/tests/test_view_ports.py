from __future__ import annotations

import ast
from pathlib import Path
import unittest

import src  # noqa: F401

from app.player_stats_view import OverlayView, PlayerStatsView, RecordingsListView


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_RESOLVERS = {
    "player_stats_memory",
    "run_lifecycle",
    "vod_capture",
    "refresh_tasks",
    "player_stats_refresh",
    "live_snapshot_store",
    "player_stats_view",
    "overlay_view",
    "recordings_list_view",
    "ensure_refresh_coordinator",
}


def _operations(protocol) -> set[str]:
    return {
        name
        for name, value in vars(protocol).items()
        if callable(value) and not name.startswith("__")
    }


class ViewPortRoutingTests(unittest.TestCase):
    def test_view_protocols_partition_the_declared_surface(self) -> None:
        union: set[str] = set()
        for protocol in (PlayerStatsView, OverlayView, RecordingsListView):
            operations = _operations(protocol)
            self.assertFalse(union & operations)
            union |= operations
        self.assertEqual(len(union), 19)

    def test_production_has_no_owner_based_service_resolvers(self) -> None:
        found = []
        for path in sorted((ROOT / "app").glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in FORBIDDEN_RESOLVERS:
                    found.append(f"{path.name}:{node.lineno}:{node.name}")
        self.assertEqual(found, [])

    def test_megabonk_app_has_no_dynamic_attribute_forwarding(self) -> None:
        path = ROOT / "gui_app.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        app = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "MegabonkApp")
        methods = {node.name for node in app.body if isinstance(node, ast.FunctionDef)}
        self.assertNotIn("__getattr__", methods)

    def test_runtime_is_the_only_production_service_composition_root(self) -> None:
        runtime_source = (ROOT / "app" / "runtime.py").read_text(encoding="utf-8")
        for constructor in (
            "PlayerStatsMemory(",
            "RunLifecycle(",
            "VodCapture(",
            "RefreshTasks(",
            "PlayerStatsRefresh(",
            "VodLibrary(",
        ):
            self.assertIn(constructor, runtime_source)

        coordinator_constructors = []
        for path in sorted(ROOT.rglob("*.py")):
            if "tests" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "AppCoordinator"
                ):
                    coordinator_constructors.append(path.relative_to(ROOT).as_posix())
        self.assertEqual(coordinator_constructors, ["app/runtime.py"])

    def test_vod_storage_has_no_module_global_settings_repository(self) -> None:
        path = ROOT / "infra" / "vod_storage.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        forbidden = {"_settings", "use_settings"}
        found = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in forbidden:
                found.append(node.name)
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
                found.extend(
                    target.id
                    for target in targets
                    if isinstance(target, ast.Name) and target.id in forbidden
                )
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
