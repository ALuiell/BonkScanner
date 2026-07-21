"""Builder for `TemplateRuntimeFilters`.

Same contract as `compare_runs.py` and `player_stats.py`: call the component's
**real** constructor with explicit fakes. Adding a constructor argument breaks
every call site here loudly.

Added by step 22b, the step that introduced the service -- the migration order
`test_componentization_inventory.py`'s header states.

`attach()` is the one addition the other builders do not need. `active_templates`
and `template_stats` are delegating properties on `MegabonkApp` now, and an
`object.__new__` double has no owner behind them: it silently falls back to its
own `__dict__`, which is the affordance `ScannerMixin.client` established. A
double that also calls `_sync_runtime_filters` needs the real owner, and needs
its pre-set state carried *into* it rather than stranded in the fallback slots.
"""

from __future__ import annotations

from app.template_filters import TemplateRuntimeFilters
from ui.shared import _read_bool


def build_template_filters(**overrides) -> TemplateRuntimeFilters:
    """A real `TemplateRuntimeFilters` with its four ports faked."""
    defaults = {
        "selected_template_names": list,
        "refresh_stats": lambda: None,
        "log": lambda _message: None,
        "is_scanning": lambda: False,
    }
    unknown = set(overrides) - set(defaults)
    assert not unknown, f"not TemplateRuntimeFilters arguments: {sorted(unknown)}"
    defaults.update(overrides)
    return TemplateRuntimeFilters(**defaults)


def attach(app, **overrides) -> TemplateRuntimeFilters:
    """Install a real owner on `app`, wired the way `MegabonkApp.__init__` wires it.

    The four default ports are copies of the production lambdas, reading the
    same attributes off the double. That is deliberate: a builder whose ports
    are stubs proves the service runs, not that the app hands it the right
    things. `refresh_stats` keeps the app-side "are the stats widgets built"
    guard for the same reason.

    Order matters: the double's `app.active_templates = [...]` lines run before
    this and land in the `__dict__` fallback, so they are read back out and
    handed to the owner. Attaching first and assigning after works too -- this
    way round is supported so the existing doubles keep reading top-to-bottom.
    """
    defaults = {
        "selected_template_names": lambda: [
            name for name, cb in getattr(app, "checkboxes", {}).items() if _read_bool(cb)
        ],
        "refresh_stats": lambda: (
            app.refresh_stats_ui()
            if hasattr(app, "stats_avg_labels") and hasattr(app, "stats_avg_layout")
            else None
        ),
        "log": lambda message: app.log(message),
        "is_scanning": lambda: (
            app.scanner_thread is not None and app.scanner_thread.is_alive()
        ),
    }
    defaults.update(overrides)
    carried_templates = app.active_templates
    carried_stats = app.template_stats
    owner = build_template_filters(**defaults)
    owner.active_templates = carried_templates
    owner.template_stats = carried_stats
    app._template_filters = owner
    return owner
