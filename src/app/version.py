from __future__ import annotations


CURRENT_VERSION = "2.1.7"


def parse_version(v):
    return tuple(map(int, v.split(".")))
