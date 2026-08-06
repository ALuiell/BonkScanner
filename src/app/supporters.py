"""Who is thanked in the footer, and how that list is fetched.

Separate from `app.update_flow` despite both being GitHub reads the footer
shows, because they answer to different rules: the update check is only
meaningful for a packaged build and returns early without one, while the
supporters list is the same for every copy of the application including a run
from source.

Lives here rather than beside the strip that displays it for the same reason
`update_flow` does: `ui/` may not import `infra/`, and this is the half that
talks to the network. The widget half stays in `ui/dialogs/update_prompt.py`.
"""
from __future__ import annotations

from typing import Callable

from infra import updater

#: Called with the supporters list, on the thread this ran on.
ReportCallback = Callable[[list], None]


def load_supporters(report: ReportCallback) -> None:
    """Fetch the published list and hand it over, or say nothing at all.

    **Every failure ends as silence, and that is the whole design.** No network,
    GitHub down, a half-saved edit to `supporters.json`, or a list that is
    simply empty because nobody has subscribed yet: none of them call `report`,
    so the footer keeps the plain `♥ Support` card it ships with. There is no
    state between "no list" and "a list" -- no error to show, no empty heading,
    no `♥ 0 supporters` -- and nothing to retry, since the next launch asks
    again.

    Runs on whatever thread the caller provides, so a `report` that touches
    widgets has to hop threads itself. `start_supporters_load` does.
    """
    try:
        supporters = updater.fetch_supporters()
    except Exception as error:
        print(f"Failed to fetch supporters: {error}")
        return
    if not supporters:
        return
    report(supporters)
