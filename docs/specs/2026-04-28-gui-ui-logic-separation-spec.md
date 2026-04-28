# GUI UI-Logic Separation Spec

## Refined Goal

Refactor `gui.py` so that UI code is separated from non-UI logic while preserving current behavior.

## Task Type

Refactor

## Target Surface

`gui.py`

## Current Behavior

`gui.py` currently contains both UI code and logic that the user wants separated.

## Expected Behavior

`gui.py` should primarily contain UI concerns, while non-UI logic should be separated out. The refactor may include limited cleanup, but it should not introduce user-visible behavior changes.

## Inputs and Outputs

Inputs: existing app workflows that currently go through `gui.py`.

Outputs: the same user-visible behavior as before, with clearer separation between UI responsibilities and non-UI logic in code structure.

## Constraints

- Preserve existing behavior.
- Cleanup is allowed if it stays local to the refactor.
- The separation target is "UI only view": UI stays in `gui.py`, while logic is moved out of the UI layer.

## Acceptance Criteria

- `gui.py` is focused on UI responsibilities.
- Non-UI logic is separated from the UI layer.
- Existing user-visible behavior remains unchanged after the refactor.
- Any cleanup included in the refactor does not expand scope into UX or feature changes.

## Out of Scope

- New features.
- User-visible UX or behavior changes beyond preserving current behavior.
- Broader architectural changes outside the refactor needed to separate UI and logic in `gui.py`.

## Assumptions

- The user wants this to be a structural refactor, not a functional rewrite.
- "Cleanup" means limited local improvements such as reducing obvious duplication or clarifying code, without changing behavior.

## Open Questions

Not specified

## User-Stated Context

- The user wants to refactor `gui.py`.
- The goal is to separate UI and logic.
- The desired scope is "separation + cleanup".
- The desired boundary is "UI only view".
