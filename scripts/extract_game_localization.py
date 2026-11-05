"""Extract the seven selected MegaBonk locales without changing game files.

This maintainer tool needs UnityPy; the application does not. Original text,
collection GUIDs, entry IDs, keys and SmartFormat flags are preserved. Missing
entries stay missing, and empty strings stay empty. See the shared docs'
development/game_localization_extraction.md for the format and refresh command.
"""

from __future__ import annotations

import argparse
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import re


LANGUAGES = {
    "en": "english",
    "uk": "ukrainian",
    "ru": "russian",
    "fr": "french",
    "es": "spanish",
    "de": "german",
    "pt": "portuguese",
}
BUNDLE_DIRECTORY = Path("Megabonk_Data/StreamingAssets/aa/StandaloneWindows64")
SHARED_BUNDLE = "localization-assets-shared_assets_all.bundle"
LOCALES_BUNDLE = "localization-locales_assets_all.bundle"
SCHEMA_VERSION = 1


def _objects(path: Path):
    import UnityPy

    for obj in UnityPy.load(str(path)).objects:
        if obj.type.name == "MonoBehaviour":
            # A parse failure must stop extraction instead of losing a table.
            yield obj.path_id, obj.read_typetree()


def _unique(target: dict, key, value, context: str) -> None:
    if key in target:
        raise ValueError(f"Duplicate {context}: {key}")
    target[key] = value


def extract_shared(objects) -> tuple[dict, dict]:
    tables: dict = {}
    names_by_path_id: dict = {}
    guids: set[str] = set()
    for path_id, data in objects:
        if "m_Entries" not in data:
            continue
        name = data["m_TableCollectionName"]
        guid = data["m_TableCollectionNameGuidString"]
        if guid in guids:
            raise ValueError(f"Duplicate collection GUID: {guid}")
        guids.add(guid)
        entries: dict = {}
        ids: set[str] = set()
        for entry in data["m_Entries"]:
            entry_id = str(entry["m_Id"])
            if entry_id in ids:
                raise ValueError(f"Duplicate entry ID in {name}: {entry_id}")
            ids.add(entry_id)
            _unique(entries, entry["m_Key"], entry_id, f"key in {name}")
        _unique(tables, name, {"collection_guid": guid, "entries": entries}, "shared table")
        _unique(names_by_path_id, path_id, name, "shared asset path ID")
    if not tables:
        raise ValueError("No shared localization tables found")
    return tables, names_by_path_id


def _smart_metadata(data: dict) -> tuple[set[int], set[str]]:
    references: dict[int, set[str]] = {}
    for reference in data.get("references", {}).get("RefIds", []):
        kind = reference["type"]
        if kind != {
            "class": "SmartFormatTag",
            "ns": "UnityEngine.Localization.Metadata",
            "asm": "Unity.Localization",
        }:
            raise ValueError(f"Unsupported localization metadata: {kind}")
        references[reference["rid"]] = {str(value) for value in reference["data"]["m_Entries"]}
    table_smart_entries: set[str] = set()
    for item in data.get("m_Metadata", {}).get("m_Items", []):
        # Unity can store a shared SmartFormatTag on the table, containing
        # the specific entry IDs it applies to, as well as entry-level tags.
        table_smart_entries.update(references[item["rid"]])
    return set(references), table_smart_entries


def extract_locale(objects, locale: str, shared: dict, names_by_path_id: dict) -> dict:
    tables: dict = {}
    for _, data in objects:
        if "m_TableData" not in data:
            continue
        if data["m_LocaleId"]["m_Code"] != locale:
            raise ValueError(f"Unexpected locale in {data['m_Name']}")
        # Resolve the actual shared-data pointer, not just the table's display name.
        name = names_by_path_id[data["m_SharedData"]["m_PathID"]]
        if data["m_Name"] != f"{name}_{locale}":
            raise ValueError(f"Table name/shared-data mismatch: {data['m_Name']}")
        keys_by_id = {value: key for key, value in shared[name]["entries"].items()}
        smart_references, table_smart_entries = _smart_metadata(data)
        entries: dict = {}
        for entry in data["m_TableData"]:
            entry_id = str(entry["m_Id"])
            key = keys_by_id[entry_id]
            text = entry["m_Localized"]
            if not isinstance(text, str):
                raise ValueError(f"Non-string text in {locale}/{name}/{key}")
            metadata = entry.get("m_Metadata", {}).get("m_Items", [])
            if any(item["rid"] not in smart_references for item in metadata):
                raise ValueError(f"Unknown metadata in {locale}/{name}/{key}")
            _unique(entries, key, {
                "id": entry_id,
                "text": text,
                "smart": bool(metadata) or entry_id in table_smart_entries,
            }, f"entry in {locale}/{name}")
        _unique(tables, name, {
            "collection_guid": shared[name]["collection_guid"],
            "entries": entries,
        }, f"table in {locale}")
    if set(tables) != set(shared):
        raise ValueError(f"Table coverage mismatch for {locale}: {set(shared) ^ set(tables)}")
    return {"schema_version": SCHEMA_VERSION, "locale": locale, "tables": tables}


def coverage(catalog: dict, shared: dict) -> dict:
    missing = []
    empty = []
    entry_count = 0
    smart_count = 0
    for name, table in sorted(shared.items()):
        entries = catalog["tables"][name]["entries"]
        entry_count += len(entries)
        smart_count += sum(entry["smart"] for entry in entries.values())
        for key, entry_id in sorted(table["entries"].items()):
            reference = {"table": name, "key": key, "id": entry_id}
            if key not in entries:
                missing.append(reference)
            elif not entries[key]["text"]:
                empty.append(reference)
    return {
        "table_count": len(catalog["tables"]),
        "entry_count": entry_count,
        "smart_entry_count": smart_count,
        "missing_entries": missing,
        "empty_entries": empty,
    }


def _json_bytes(data: dict) -> bytes:
    return (json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _file_record(data: bytes) -> dict:
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def build_export(game_root: Path) -> dict[str, bytes]:
    bundle_directory = game_root / BUNDLE_DIRECTORY
    sources: dict = {}

    def read_bundle(filename: str):
        path = bundle_directory / filename
        before = path.read_bytes()
        objects = list(_objects(path))
        if path.read_bytes() != before:
            raise ValueError(f"Game resources changed during extraction: {filename}")
        sources[(BUNDLE_DIRECTORY / filename).as_posix()] = _file_record(before)
        return objects

    shared, names_by_path_id = extract_shared(read_bundle(SHARED_BUNDLE))
    locale_metadata: dict = {}
    for _, data in read_bundle(LOCALES_BUNDLE):
        code = data.get("m_Identifier", {}).get("m_Code")
        if code in LANGUAGES:
            _unique(locale_metadata, code, {
                "game_locale_name": data["m_LocaleName"],
                "game_locale_code": code,
                "custom_format_culture_code": data["m_CustomFormatCultureCode"],
                "use_custom_formatter": bool(data["m_UseCustomFormatter"]),
            }, "locale definition")
    if set(locale_metadata) != set(LANGUAGES):
        raise ValueError("Missing selected locale definitions")
    outputs = {"shared.json": _json_bytes({"schema_version": SCHEMA_VERSION, "tables": shared})}
    for code, language in LANGUAGES.items():
        filename = f"localization-string-tables-{language}({code})_assets_all.bundle"
        catalog = extract_locale(read_bundle(filename), code, shared, names_by_path_id)
        locale_metadata[code].update(coverage(catalog, shared))
        outputs[f"{code}.json"] = _json_bytes(catalog)

    # Only retain public build identification, never Steam account/owner fields.
    steam_build_id = None
    manifest_path = game_root.parent.parent / "appmanifest_3405340.acf"
    if manifest_path.is_file():
        match = re.search(r'"buildid"\s+"(\d+)"', manifest_path.read_text(encoding="utf-8"))
        if match:
            steam_build_id = match[1]
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "game": "MegaBonk",
        "steam_app_id": "3405340",
        "steam_build_id": steam_build_id,
        "extractor": "scripts/extract_game_localization.py",
        "unitypy_version": version("UnityPy"),
        "shared_table_count": len(shared),
        "shared_entry_count": sum(len(table["entries"]) for table in shared.values()),
        "locales": locale_metadata,
        "sources": sources,
        "outputs": {name: _file_record(data) for name, data in outputs.items()},
    }
    outputs["manifest.json"] = _json_bytes(manifest)
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game_root", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--check", action="store_true", help="Compare with a fresh extraction; write nothing")
    args = parser.parse_args()
    outputs = build_export(args.game_root)
    if args.check:
        mismatched = [
            name for name, data in outputs.items()
            if not (args.output / name).is_file() or (args.output / name).read_bytes() != data
        ]
        if mismatched:
            parser.exit(1, f"Localization export differs: {', '.join(mismatched)}\n")
        print(f"Verified {len(outputs)} exported files against game resources.")
    else:
        # Parse and validate every input before writing any catalog.
        args.output.mkdir(parents=True, exist_ok=True)
        for name, data in outputs.items():
            (args.output / name).write_bytes(data)
        print(f"Exported {len(LANGUAGES)} locales to {args.output}")
    manifest = json.loads(outputs["manifest.json"])
    for locale, details in manifest["locales"].items():
        print(f"{locale}: {details['table_count']} tables, {details['entry_count']} entries, "
              f"{len(details['missing_entries'])} missing, {len(details['empty_entries'])} empty")


if __name__ == "__main__":
    main()
