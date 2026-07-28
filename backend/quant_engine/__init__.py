"""Ai-Robot Quant Engine V1 public API.

The package is intentionally isolated from the legacy strategy and analyzer
modules.  Integrations should depend on the contracts exported here.
"""

from .contracts import (
    Factor,
    Ranker,
    RegimeDetector,
    ResearchRunner,
    ResonanceDetector,
    SignalGenerator,
)
from .factors import (
    DuplicateFactorError,
    FactorMetadata,
    FactorRegistry,
    FactorResult,
    FactorStatus,
    UnknownFactorError,
)

__all__ = [
    "DuplicateFactorError",
    "Factor",
    "FactorMetadata",
    "FactorRegistry",
    "FactorResult",
    "FactorStatus",
    "Ranker",
    "RegimeDetector",
    "ResearchRunner",
    "ResonanceDetector",
    "SignalGenerator",
    "UnknownFactorError",
]
