from __future__ import annotations


CURRENT_VERSION = "3.0.0"


def parse_version(v):
    return tuple(map(int, v.split(".")))
