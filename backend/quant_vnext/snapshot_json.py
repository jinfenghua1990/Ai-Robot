from __future__ import annotations

import json
from dataclasses import asdict

from .contracts import SignalSnapshot


def dumps(snapshot: SignalSnapshot) -> str:
    """Stable JSON representation for resonance_snapshot/outcome pipelines."""
    return json.dumps(asdict(snapshot), ensure_ascii=False, default=str, sort_keys=True)
