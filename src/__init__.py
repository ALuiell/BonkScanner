from __future__ import annotations

import sys
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parent
src_path = str(SRC_DIR)

if src_path not in sys.path:
    sys.path.insert(0, src_path)