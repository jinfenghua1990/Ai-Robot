"""Serializable factor result schema."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from math import isfinite
from typing import Any, Mapping, Optional


class FactorStatus(str, Enum):
    VALID = "valid"
    MISSING = "missing"
    INVALID = "invalid"
    ERROR = "error"


@dataclass(frozen=True)
class FactorMetadata:
    """Immutable information used to discover and govern a factor."""

    name: str
    version: str
    description: str
    category: str
    higher_is_better: bool = True
    required_fields: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("factor name must not be empty")
        if not self.version or not self.version.strip():
            raise ValueError("factor version must not be empty")


@dataclass(frozen=True)
class FactorResult:
    """One factor observation for one instrument and timestamp."""

    factor_name: str
    instrument: str
    observed_at: datetime
    value: Optional[float]
    status: FactorStatus = FactorStatus.VALID
    reason: Optional[str] = None
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.factor_name:
            raise ValueError("factor_name must not be empty")
        if not self.instrument:
            raise ValueError("instrument must not be empty")
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")
        if self.status is FactorStatus.VALID:
            if self.value is None or not isfinite(self.value):
                raise ValueError("valid factor result requires a finite value")
        elif self.value is not None and not isfinite(self.value):
            raise ValueError("factor value must be finite when provided")
        if self.status is not FactorStatus.VALID and not self.reason:
            raise ValueError("non-valid factor result requires a reason")

    @classmethod
    def valid(
        cls,
        *,
        factor_name: str,
        instrument: str,
        value: float,
        observed_at: Optional[datetime] = None,
        attributes: Optional[Mapping[str, Any]] = None,
    ) -> "FactorResult":
        return cls(
            factor_name=factor_name,
            instrument=instrument,
            observed_at=observed_at or datetime.now(timezone.utc),
            value=value,
            attributes=attributes or {},
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["observed_at"] = self.observed_at.isoformat()
        payload["status"] = self.status.value
        return payload
