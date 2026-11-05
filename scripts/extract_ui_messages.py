"""Check or add explicit UI messages without overwriting reviewed translations.

Run from the repository root. With --check, no files are modified. Missing
messages fail the check; unused keys are retained for dynamic presentation
terms and compatibility with already captured statuses.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODES = ("en", "uk", "ru", "fr", "es", "de", "pt")


def message_key(source):
    return "app." + hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]


def extract_messages():
    sources = {}
    for path in (ROOT / "src").rglob("*.py"):
        if "tests" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and node.args:
                function = node.func
                explicit = (
                    isinstance(function, ast.Attribute)
                    and isinstance(function.value, ast.Name)
                    and function.value.id == "l10n" and function.attr == "tr"
                ) or (
                    isinstance(function, ast.Name)
                    and (function.id == "_lt" or function.id == "tr" and path.name == "i18n.py")
                )
                if explicit and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    source = node.args[0].value
                    sources[message_key(source)] = source
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id in {"DISPLAY_TERMS", "OBS_MESSAGES"}
                for target in node.targets
            ):
                for source in ast.literal_eval(node.value):
                    sources[message_key(source)] = source
    return sources


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    messages = extract_messages()
    missing = []
    for code in CODES:
        path = ROOT / "src/media/localization/ui" / f"{code}.json"
        catalog = json.loads(path.read_text(encoding="utf-8"))
        absent = {key: value for key, value in messages.items() if key not in catalog}
        if absent:
            missing.append(f"{code}: {len(absent)}")
            if not args.check:
                catalog.update(absent)
                path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.check and missing:
        parser.exit(1, "Missing UI messages: " + ", ".join(missing) + "\n")
    print(f"Checked {len(messages)} explicit messages across {len(CODES)} catalogs.")
    if missing:
        print("Added English drafts; translate and review them before release: " + ", ".join(missing))


if __name__ == "__main__":
    main()
