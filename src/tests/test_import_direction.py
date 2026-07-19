"""Enforces the layer table from §2 of the refactor roadmap.

Five packages, imports point downward only. Review does not catch drift here --
the ``infra -> projections`` edge below sat unnoticed inside a method body
through a step that explicitly grepped for layering violations.

Three outcomes are kept apart on purpose:

* **Violation** -- a runtime edge the §2 table forbids, not in any allowlist.
  Fails.
* **Debt** -- a known bad edge, listed in ``KNOWN_VIOLATIONS`` or
  ``TOPLEVEL_DEBT`` with what will remove it. Does not fail while it matches
  reality; fails once the entry goes stale.
* **Type-checking edge** -- forbidden by the table but inside
  ``if TYPE_CHECKING:``, so it does not exist at runtime. Listed in
  ``TYPE_CHECKING_DEBT``, same staleness rule.

Every allowlist here shrinks and never grows: an entry that no longer
corresponds to a real import fails the suite, so paying a debt down forces the
record to be updated with it.
"""

from __future__ import annotations

import src

import ast
import sys
import unittest
from pathlib import Path
from typing import Dict, Iterable, List, NamedTuple, Optional, Set, Tuple


SRC_DIR = Path(src.__file__).resolve().parent

# §2 of docs/updates/architecture_updates/refactor_roadmap.md. Each package maps
# to the set of *other* layered packages it may import. Imports within a package
# are always allowed; stdlib and third-party imports are not edges at all.
LAYER_RULES: Dict[str, Set[str]] = {
    "core": set(),
    "infra": {"core"},
    "projections": {"core"},
    "app": {"core", "infra", "projections"},
    "ui": {"app", "projections", "core"},
}

# Top-level modules under src/ that predate the layer split. Importing one is
# neither allowed nor forbidden by §2 -- the table does not describe them. They
# are treated as a pseudo-zone so that the checker covers the whole tree rather
# than reporting green over a third of the codebase; every existing edge into
# the zone is listed in TOPLEVEL_DEBT and every new one fails.
UNLAYERED_ZONE = "<top-level>"

# Not a layer. Tests legitimately import across every boundary.
EXCLUDED_DIRS = {"tests", "__pycache__", "chaos_validation_runs", "media"}


class Edge(NamedTuple):
    """One import from a layered module to another local module."""

    source_layer: str
    source_path: str  # posix, relative to src/
    lineno: int
    target_module: str  # fully dotted, as written
    target_root: str  # first component -- the layer or top-level module
    type_checking: bool

    def describe(self) -> str:
        return "src/{path}:{line}: {layer} -> {root} (imports {module})".format(
            path=self.source_path,
            line=self.lineno,
            layer=self.source_layer,
            root=self.target_root,
            module=self.target_module,
        )


# --------------------------------------------------------------------------
# Allowlists. Each key is (source path relative to src/, imported root module).
# Each value says where the edge came from and what removes it.
# --------------------------------------------------------------------------

# Runtime edges that the §2 table forbids outright. This is not a parking lot:
# an entry here is an open bug, not an accepted shape.
# Empty since step 17b, and it should stay that way. The one entry this list
# ever held -- infra/overlay_server.py importing the private
# projections.obs._widget_config_by_id from inside a method body -- was paid off
# by moving the normalization down to core/overlay_config.py, where both the
# projection and the server may import it. It is the only violation this checker
# has ever found, and it was found on its first run.
KNOWN_VIOLATIONS: Dict[Tuple[str, str], str] = {}

# Layered package -> unlayered top-level module. Debt, not violation: the target
# has no layer yet, so no direction can be assigned to the edge.
TOPLEVEL_DEBT: Dict[Tuple[str, str], str] = {
    ("app/coordinator.py", "live_run_tracker"): (
        "The tracker's own module file is still top-level: step 13 split its "
        "internals into core/tracker/ but moving live_run_tracker.py would "
        "touch ~117 import sites. Removed when the module file lands in "
        "core/, making this app -> core."
    ),
    ("app/player_stats_refresh.py", "live_run_tracker"): (
        "Same as app/coordinator.py -> live_run_tracker."
    ),
    ("ui/tabs/player_stats/recordings.py", "gui_dialogs"): (
        "Removed when gui_dialogs.py moves to ui/dialogs/ (§2 placement "
        "table), making this a within-ui import."
    ),
    ("ui/tabs/player_stats/live_stats.py", "gui_layout"): (
        "Removed when gui_layout.py moves to ui/layout.py."
    ),
    ("ui/tabs/player_stats/recordings.py", "gui_layout"): (
        "Removed when gui_layout.py moves to ui/layout.py."
    ),
}

# Edges under `if TYPE_CHECKING:`. Not runtime dependencies -- the import never
# executes -- but they still record a direction the table forbids, so they are
# named rather than silently skipped.
TYPE_CHECKING_DEBT: Dict[Tuple[str, str], str] = {
    ("core/run_control.py", "infra"): (
        "Deliberate, from step 10c: the port needs the client type for "
        "annotations only. Removed when the annotation is expressed against a "
        "core-owned protocol instead of the concrete infra client."
    ),
    ("projections/obs.py", "live_run_tracker"): (
        "Snapshot type annotation. Removed when live_run_tracker.py moves to "
        "core/, making this projections -> core -- which is allowed."
    ),
}


# --------------------------------------------------------------------------
# Analysis
# --------------------------------------------------------------------------


def local_module_roots() -> Set[str]:
    """Names importable as top-level modules from src/.

    An imported root is a local module only if src/<name>.py or src/<name>/
    exists. Maintaining a list of third-party packages instead would go stale;
    pymem and win32cred are not local just because they are not stdlib.
    """

    roots: Set[str] = set()
    for entry in SRC_DIR.iterdir():
        if entry.is_dir() and (entry / "__init__.py").is_file():
            roots.add(entry.name)
        elif entry.suffix == ".py" and entry.stem != "__init__":
            roots.add(entry.stem)
    return roots


def module_parts(path: Path) -> List[str]:
    """Dotted-name components of the module at ``path``, as imported from src/."""

    parts = list(path.relative_to(SRC_DIR).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return parts


def resolve_relative(node: ast.ImportFrom, path: Path) -> Optional[str]:
    """Absolute dotted name for a relative import, or None if it escapes src/.

    ``level`` counts upward from the module's own *package*: level 1 is the
    containing package, level 2 its parent, and so on. For a package's
    ``__init__.py`` the module name is already the package.
    """

    package = module_parts(path)
    if path.name != "__init__.py":
        package = package[:-1]
    ascend = node.level - 1
    if ascend > len(package):
        return None
    base = package[: len(package) - ascend] if ascend else package
    return ".".join(base + ([node.module] if node.module else []))


def imported_modules(node: ast.AST, path: Path) -> Iterable[str]:
    """Dotted names imported by one Import/ImportFrom node."""

    if isinstance(node, ast.Import):
        for alias in node.names:
            yield alias.name
    elif isinstance(node, ast.ImportFrom):
        if node.level:
            resolved = resolve_relative(node, path)
            if resolved:
                yield resolved
        elif node.module:
            yield node.module


def type_checking_nodes(tree: ast.AST) -> Set[int]:
    """ids of every node inside an ``if TYPE_CHECKING:`` body."""

    guarded: Set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        name = None
        if isinstance(test, ast.Name):
            name = test.id
        elif isinstance(test, ast.Attribute):
            name = test.attr
        if name != "TYPE_CHECKING":
            continue
        for statement in node.body:
            for child in ast.walk(statement):
                guarded.add(id(child))
    return guarded


def layered_source_files() -> List[Tuple[str, Path]]:
    """(layer, path) for every module inside a layered package."""

    found: List[Tuple[str, Path]] = []
    for layer in sorted(LAYER_RULES):
        package = SRC_DIR / layer
        for path in sorted(package.rglob("*.py")):
            if EXCLUDED_DIRS.intersection(path.parts):
                continue
            found.append((layer, path))
    return found


def collect_edges() -> List[Edge]:
    """Every import from a layered module to another local module.

    Walks the whole tree, not the file header: the one violation this checker
    was written to find lives inside a method body.
    """

    roots = local_module_roots()
    edges: List[Edge] = []
    for layer, path in layered_source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        guarded = type_checking_nodes(tree)
        relative = path.relative_to(SRC_DIR).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            for module in imported_modules(node, path):
                root = module.split(".")[0]
                if root in sys.stdlib_module_names or root not in roots:
                    continue  # stdlib or third-party -- not a layer edge
                if root == layer:
                    continue  # within the package, always allowed
                edges.append(
                    Edge(
                        source_layer=layer,
                        source_path=relative,
                        lineno=node.lineno,
                        target_module=module,
                        target_root=root,
                        type_checking=id(node) in guarded,
                    )
                )
    return edges


def classify(edge: Edge) -> str:
    """One of: 'allowed', 'type_checking', 'toplevel', 'violation'."""

    if edge.target_root in LAYER_RULES[edge.source_layer]:
        return "allowed"
    # TYPE_CHECKING is decided before the target zone: an annotation-only import
    # of an unlayered module is still annotation-only, and reporting it as
    # runtime debt would misstate what it costs.
    if edge.type_checking:
        return "type_checking"
    if edge.target_root not in LAYER_RULES:
        return "toplevel"
    return "violation"


class ImportDirectionTests(unittest.TestCase):
    """§2's layer table, checked rather than reviewed."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.edges = collect_edges()

    def test_layer_table_is_not_violated(self) -> None:
        """No runtime edge against §2 beyond the ones recorded as bugs."""

        unexpected = [
            edge
            for edge in self.edges
            if classify(edge) == "violation"
            and (edge.source_path, edge.target_root) not in KNOWN_VIOLATIONS
        ]
        if unexpected:
            allowed = sorted(LAYER_RULES[unexpected[0].source_layer])
            self.fail(
                "Import direction violates the §2 layer table:\n"
                + "\n".join("  " + edge.describe() for edge in unexpected)
                + "\n\n{layer}/ may import: {allowed}\n".format(
                    layer=unexpected[0].source_layer,
                    allowed=", ".join(allowed) or "nothing but stdlib",
                )
                + "Move the code or invert the dependency. Do not add it to "
                "KNOWN_VIOLATIONS without recording why it cannot be fixed."
            )

    def test_no_new_edges_into_unlayered_modules(self) -> None:
        """Every import of a pre-split top-level module is a recorded debt."""

        unexpected = [
            edge
            for edge in self.edges
            if classify(edge) == "toplevel"
            and (edge.source_path, edge.target_root) not in TOPLEVEL_DEBT
        ]
        if unexpected:
            self.fail(
                "New import into an unlayered top-level module:\n"
                + "\n".join("  " + edge.describe() for edge in unexpected)
                + "\n\nThese modules predate the layer split and belong to no "
                "layer, so §2 cannot say whether the direction is legal. "
                "Either import from a layered package instead, or add the "
                "edge to TOPLEVEL_DEBT with what will remove it."
            )

    def test_type_checking_edges_are_declared(self) -> None:
        """Annotation-only edges are named rather than silently skipped."""

        unexpected = [
            edge
            for edge in self.edges
            if classify(edge) == "type_checking"
            and (edge.source_path, edge.target_root) not in TYPE_CHECKING_DEBT
        ]
        if unexpected:
            self.fail(
                "Undeclared TYPE_CHECKING import across a layer boundary:\n"
                + "\n".join("  " + edge.describe() for edge in unexpected)
                + "\n\nThis is not a runtime dependency, so it does not break "
                "the layering -- but it still records a direction §2 does not "
                "allow. Add it to TYPE_CHECKING_DEBT with what removes it, or "
                "annotate against a type the source layer owns."
            )

    def test_allowlists_do_not_outlive_their_debt(self) -> None:
        """Every allowlist entry still corresponds to a real import.

        Without this the lists only grow, and a checker whose allowlist is a
        junk drawer asserts nothing. Same rule as patch_everywhere in
        test_gui_run_control.py, which fails when a patched name is gone.
        """

        observed = {
            "KNOWN_VIOLATIONS": set(),
            "TOPLEVEL_DEBT": set(),
            "TYPE_CHECKING_DEBT": set(),
        }
        registry = {
            "violation": ("KNOWN_VIOLATIONS", KNOWN_VIOLATIONS),
            "toplevel": ("TOPLEVEL_DEBT", TOPLEVEL_DEBT),
            "type_checking": ("TYPE_CHECKING_DEBT", TYPE_CHECKING_DEBT),
        }
        for edge in self.edges:
            entry = registry.get(classify(edge))
            if not entry:
                continue
            name, allowlist = entry
            key = (edge.source_path, edge.target_root)
            if key in allowlist:
                observed[name].add(key)

        stale = []
        for name, allowlist in (
            ("KNOWN_VIOLATIONS", KNOWN_VIOLATIONS),
            ("TOPLEVEL_DEBT", TOPLEVEL_DEBT),
            ("TYPE_CHECKING_DEBT", TYPE_CHECKING_DEBT),
        ):
            for key in sorted(set(allowlist) - observed[name]):
                stale.append(
                    "  {name}[{path!r}, {root!r}] -- no such import\n"
                    "      recorded as: {why}".format(
                        name=name, path=key[0], root=key[1], why=allowlist[key]
                    )
                )
        if stale:
            self.fail(
                "Allowlist entry outlived the debt it records:\n"
                + "\n".join(stale)
                + "\n\nThe debt is paid or the file moved. Delete the entry -- "
                "these lists shrink, never grow."
            )

    def test_core_imports_no_other_layer(self) -> None:
        """The rule §2 calls the one most worth protecting, stated on its own.

        core/ is what makes the domain testable without a game, a window or a
        socket, so a regression here should name itself rather than arrive as
        one line in a general layering report. Runtime edges into another
        *layer* only -- core's remaining top-level debt (gui_styles) is
        TOPLEVEL_DEBT's business, and its annotation-only edge into infra is
        TYPE_CHECKING_DEBT's.
        """

        offenders = [
            edge
            for edge in self.edges
            if edge.source_layer == "core"
            and edge.target_root in LAYER_RULES
            and not edge.type_checking
        ]
        if offenders:
            self.fail(
                "core/ must import nothing but stdlib and other core "
                "modules:\n"
                + "\n".join("  " + edge.describe() for edge in offenders)
            )

    def test_scan_reaches_the_whole_tree(self) -> None:
        """The checker must actually enter every layer.

        A green run over an empty edge list proves nothing; step 13 shipped a
        harness that reported success without once entering its subject.
        """

        self.assertEqual(
            set(LAYER_RULES),
            {layer for layer, _ in layered_source_files()},
            "a layered package produced no source files",
        )
        scanned = {edge.source_layer for edge in self.edges}
        self.assertEqual(
            set(LAYER_RULES),
            scanned,
            "no cross-module imports found for some layer -- the walk is "
            "probably not reaching it",
        )
        self.assertGreater(len(self.edges), 50, "implausibly few edges found")


class ImportResolutionTests(unittest.TestCase):
    """Unit checks for the resolution rules, which src/ cannot exercise.

    src/ currently contains no relative imports at all, so resolve_relative has
    no live sample. Left untested it would be dead code that silently mis-scores
    the first relative import anyone writes.
    """

    def _parse(self, source: str) -> ast.ImportFrom:
        node = ast.parse(source).body[0]
        assert isinstance(node, ast.ImportFrom)
        return node

    def test_bare_relative_import_resolves_to_the_containing_package(self) -> None:
        """``from . import x`` binds x as a name; the module part is the package.

        Only the module part is resolved, which is enough: the root component
        is what decides the layer either way.
        """

        path = SRC_DIR / "ui" / "tabs" / "player_stats" / "cards.py"
        node = self._parse("from . import live_stats")
        self.assertEqual("ui.tabs.player_stats", resolve_relative(node, path))

    def test_relative_import_from_package_init_resolves_against_itself(self) -> None:
        path = SRC_DIR / "ui" / "tabs" / "player_stats" / "__init__.py"
        node = self._parse("from .cards import PlayerStatsCardsMixin")
        self.assertEqual("ui.tabs.player_stats.cards", resolve_relative(node, path))

    def test_parent_relative_import_ascends_one_package(self) -> None:
        path = SRC_DIR / "ui" / "tabs" / "player_stats" / "cards.py"
        node = self._parse("from ..compare_runs import tab")
        self.assertEqual("ui.tabs.compare_runs", resolve_relative(node, path))

    def test_third_party_roots_are_not_treated_as_local(self) -> None:
        roots = local_module_roots()
        for name in ("pymem", "win32cred", "PySide6", "requests"):
            self.assertNotIn(name, roots)

    def test_top_level_modules_are_local(self) -> None:
        roots = local_module_roots()
        # gui_shared and gui_styles dropped from this list in step 17a: they are
        # now ui/shared.py and ui/styles.py, so "ui" covers them and asserting
        # the old names would pin files that no longer exist.
        for name in ("gui_layout", "live_run_tracker", "twitch_bot"):
            self.assertIn(name, roots)

    def test_imports_below_the_module_header_are_collected(self) -> None:
        """The walk must not stop at the module header.

        Its original fixture was the real thing: infra/overlay_server.py hid a
        projections import inside a method body, which is exactly how it
        survived a review that grepped for it. Step 17b paid that debt off, so
        the assertion is now made against the nested imports that remain --
        the TYPE_CHECKING-guarded ones, which are also not module-level
        statements and which step 16's mutation table already records as being
        lost when `ast.walk(tree)` is downgraded to `tree.body`.

        Retargeted rather than deleted: this is the property that made the
        checker find anything at all, and it must outlive the single edge that
        motivated it.
        """

        module_level_linenos = set()
        for _layer, path in layered_source_files():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in tree.body:
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    module_level_linenos.add((path.relative_to(SRC_DIR).as_posix(), node.lineno))

        nested = [
            edge
            for edge in collect_edges()
            if (edge.source_path, edge.lineno) not in module_level_linenos
        ]
        self.assertTrue(
            nested,
            "no import below a module header was collected -- the walk is "
            "reading file headers, not the whole AST",
        )


if __name__ == "__main__":
    unittest.main()
