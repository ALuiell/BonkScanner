"""Optional integration with the independently maintained Validator package."""


def create_validator_controller():
    try:
        from bonkscanner_validator.controller import ValidatorController
    except ModuleNotFoundError as exc:
        # A missing optional package is supported. A broken installation or
        # missing transitive dependency must remain visible, not be disguised.
        if exc.name == 'bonkscanner_validator':
            return None
        raise
    from app.version import CURRENT_VERSION
    return ValidatorController(scanner_version=CURRENT_VERSION)
