"""Builder for `TemplatesPanel`.

Same contract as `compare_runs.py`, `player_stats.py` and `template_filters.py`:
call the component's **real** constructor with explicit fakes, rather than
borrowing `MegabonkApp`'s MRO through `object.__new__`. Adding a constructor
argument breaks every call site here loudly; `object.__new__` absorbs it
silently and surfaces it as an `AttributeError` at the first read.

Added by step 22c, the step that converted the panel -- the migration order the
plan in `test_componentization_inventory.py` states.

`build()` is **not** called by default: it needs real offscreen Qt. Tests that
need widgets assign the private ones they assert on, and the *built* panel is
driven by `tools/step22_templates_trace.py` across its scenarios.

`sync_filters` defaults to a **real** `TemplateRuntimeFilters` rather than a
stub, for the reason `compare_runs.build_compare_runs_tab` defaults `vod_library`
to a real `VodLibrary`: the panel-to-filters seam is the thing step 22 exists to
introduce, and a test that stubs it proves nothing about the wiring.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.template_filters import TemplateRuntimeFilters
from ui.tabs.templates import TemplatesPanel


class RecordingDialog:
    """A dialog that records `exec()` and returns a fixed result."""

    def __init__(self, result=0, result_payload=None) -> None:
        self.result = result
        self.result_payload = result_payload
        self.exec_calls = 0

    def exec(self):
        self.exec_calls += 1
        return self.result


def _refuse(name):
    def factory(*_args, **_kwargs):
        raise AssertionError(f"{name} should not have been opened")

    return factory


def build_templates_panel(**overrides) -> TemplatesPanel:
    """A real `TemplatesPanel` with its nine collaborators faked.

    Every dialog factory defaults to one that *fails* rather than one that
    returns a harmless stub. A test asserting "cancelling writes no config" is
    worthless if some other dialog opened instead and nobody noticed.
    """
    filters = TemplateRuntimeFilters(
        selected_template_names=list,
        refresh_stats=lambda: None,
        log=lambda _message: None,
        is_scanning=lambda: False,
    )
    defaults = {
        "left_tabview": None,
        "window": lambda: SimpleNamespace(),
        "sync_filters": filters.sync,
        "template_dialog": _refuse("TemplateDialog"),
        "template_manager_dialog": _refuse("TemplateManagerDialog"),
        "delete_dialog": _refuse("DeleteDialog"),
        "scores_settings_dialog": _refuse("ScoresSettingsDialog"),
        "scores_help_dialog": _refuse("ScoresHelpDialog"),
        "no_custom_templates_message": _refuse("the no-custom-templates message"),
    }
    unknown = set(overrides) - set(defaults)
    assert not unknown, f"not TemplatesPanel constructor arguments: {sorted(unknown)}"
    defaults.update(overrides)
    panel = TemplatesPanel(**defaults)
    panel._filters_for_tests = filters
    return panel
