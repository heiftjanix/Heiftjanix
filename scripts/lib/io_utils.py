"""JSON-State und Config lesen/schreiben — reine Stdlib."""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = ROOT / "state"
CONFIG_PATH = ROOT / "config" / "config.json"


def load_config(path: str | os.PathLike | None = None) -> dict:
    with open(path or CONFIG_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def read_json(path: str | os.PathLike):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: str | os.PathLike, data) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2, default=str)
    return p


def read_state(name: str):
    return read_json(STATE_DIR / name)


def write_state(name: str, data) -> Path:
    return write_json(STATE_DIR / name, data)
