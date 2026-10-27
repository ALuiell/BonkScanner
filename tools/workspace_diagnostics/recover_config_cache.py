"""Read-only search of IDE cached content for BonkScanner config backups."""

# Resolve this checkout and keep diagnostic output separate from source/evidence.
import sys as _diag_sys
from pathlib import Path as _DiagPath
for _diag_parent in _DiagPath(__file__).resolve().parents:
    if (_diag_parent / "workspace_paths.py").is_file():
        _diag_sys.path.insert(0, str(_diag_parent))
        break
from workspace_paths import (REPO_ROOT, CODE_ROOT, output_path, output_directory,
                             session_directory, local_asset_path, stage_recording_fixtures)
_diag_sys.path[:0] = [str(REPO_ROOT), str(REPO_ROOT / "src"), str(REPO_ROOT / "src/tests")]
from pathlib import Path
import zlib, json, re, hashlib
source = Path('C:/Users/heave/AppData/Local/JetBrains/PyCharm2026.1/caches/content.dat')
data = source.read_bytes()
out = output_directory("recovered-config-candidates")
found = set()
for match in re.finditer(b'\x78[\x01\x5e\x9c\xda]', data):
    try:
        dec = zlib.decompressobj()
        raw = dec.decompress(memoryview(data)[match.start():], 2000000)
    except zlib.error:
        continue
    if b'"TWITCH_BOT"' not in raw or b'"IN_GAME_OVERLAY"' not in raw:
        continue
    try:
        obj = json.loads(raw.decode('utf-8-sig'))
    except (ValueError, UnicodeError):
        continue
    digest = hashlib.sha256(raw).hexdigest()
    if digest in found: continue
    found.add(digest)
    out.mkdir(exist_ok=True)
    target = out / (str(match.start()) + '.json')
    target.write_bytes(raw)
    print(target.name, len(raw), 'bytes', len(obj), 'keys', digest)
decoder = json.JSONDecoder()
for marker in re.finditer(b'"IN_GAME_OVERLAY"', data):
    lower = max(0, marker.start() - 200000)
    for brace in reversed(list(re.finditer(rb'\{', data[lower:marker.start()]))):
        offset = lower + brace.start()
        try:
            text = data[offset:offset + 500000].decode('utf-8', errors='replace')
            obj, length = decoder.raw_decode(text)
        except ValueError:
            continue
        if not isinstance(obj, dict) or 'TWITCH_BOT' not in obj or 'IN_GAME_OVERLAY' not in obj:
            continue
        raw = text[:length].encode('utf-8')
        digest = hashlib.sha256(raw).hexdigest()
        if digest not in found:
            found.add(digest)
            out.mkdir(exist_ok=True)
            target = out / (str(offset) + '.json')
            target.write_bytes(raw)
            print(target.name, len(raw), 'bytes', len(obj), 'keys', digest)
        break
print('Candidates:', len(found))
