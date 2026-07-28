"""Stable component contracts for Quant Engine V1."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Mapping, Sequence

from .factors.result import FactorResult

Record = Mapping[str, Any]


class Factor(ABC):
    """Compute one named factor for a universe at an observation time."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the unique registry name."""

    @abstractmethod
    def compute(self, records: Sequence[Record]) -> Sequence[FactorResult]:
        """Return one result per evaluated instrument."""


class Ranker(ABC):
    """Rank comparable factor results without generating trade signals."""

    @abstractmethod
    def rank(self, results: Sequence[FactorResult]) -> Sequence[Record]:
        """Return ordered ranking records."""


class ResonanceDetector(ABC):
    """Detect agreement across independent factor dimensions."""

    @abstractmethod
    def detect(self, ranked_factors: Mapping[str, Sequence[Record]]) -> Record:
        """Return a resonance assessment."""


class RegimeDetector(ABC):
    """Classify the market regime used to gate downstream signals."""

    @abstractmethod
    def detect(self, market_data: Sequence[Record]) -> Record:
        """Return the current regime assessment."""


class SignalGenerator(ABC):
    """Create an auditable signal from rankings, resonance, and regime."""

    @abstractmethod
    def generate(self, context: Record) -> Record:
        """Return a signal record; implementations must not place orders."""


class ResearchRunner(ABC):
    """Evaluate factors and engine policies in an offline workflow."""

    @abstractmethod
    def run(self, specification: Record) -> Record:
        """Run one reproducible research specification."""
