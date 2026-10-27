"""Read-only benchmark of the game's existing pause flag."""
import json
from pathlib import Path
import statistics
import sys
import time
from _paths import DIAGNOSTICS_ROOT

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from infra.memory.game_data_client import GameDataClient

client = GameDataClient('Megabonk.exe')
try:
    fields = client._read_static_fields_cached(client.MY_TIME_TYPE_INFO_OFFSET)
    if not fields:
        raise RuntimeError('MyTime static fields unavailable')
    durations = []
    values = []
    for _ in range(200):
        start = time.perf_counter()
        value = client.memory.read_u8(fields + client.MY_TIME_PAUSED_OFFSET)
        durations.append((time.perf_counter() - start) * 1000)
        if value not in (0, 1):
            raise RuntimeError('Pause flag is invalid')
        values.append(value)
        time.sleep(.005)
    result = {'samples': len(values), 'paused_samples': sum(values),
              'read_ms_median': statistics.median(durations),
              'read_ms_p95': sorted(durations)[189],
              'read_ms_max': max(durations), 'bytes_per_sample': 1}
    DIAGNOSTICS_ROOT.mkdir(parents=True, exist_ok=True)
    (DIAGNOSTICS_ROOT / 'pause-probe-result.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result))
finally:
    client.close()
