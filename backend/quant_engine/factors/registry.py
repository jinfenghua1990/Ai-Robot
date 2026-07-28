"""Explicit, deterministic factor registration."""

from __future__ import annotations

from collections.abc import Iterator
from threading import RLock
from typing import TYPE_CHECKING, Optional

from .result import FactorMetadata

if TYPE_CHECKING:
    from ..contracts import Factor


class DuplicateFactorError(ValueError):
    """Raised when a factor name is registered more than once."""


class UnknownFactorError(KeyError):
    """Raised when a requested factor has not been registered."""


class FactorRegistry:
    """Thread-safe registry that owns factor instances and metadata."""

    def __init__(self) -> None:
        self._factors: dict[str, "Factor"] = {}
        self._metadata: dict[str, FactorMetadata] = {}
        self._lock = RLock()

    def register(
        self,
        factor: "Factor",
        metadata: FactorMetadata,
        *,
        replace: bool = False,
    ) -> None:
        if factor.name != metadata.name:
            raise ValueError(
                f"factor name {factor.name!r} does not match metadata "
                f"name {metadata.name!r}"
            )
        with self._lock:
            if factor.name in self._factors and not replace:
                raise DuplicateFactorError(f"factor already registered: {factor.name}")
            self._factors[factor.name] = factor
            self._metadata[factor.name] = metadata

    def unregister(self, name: str) -> None:
        with self._lock:
            if name not in self._factors:
                raise UnknownFactorError(name)
            del self._factors[name]
            del self._metadata[name]

    def get(self, name: str) -> "Factor":
        try:
            return self._factors[name]
        except KeyError as exc:
            raise UnknownFactorError(name) from exc

    def metadata(self, name: str) -> FactorMetadata:
        try:
            return self._metadata[name]
        except KeyError as exc:
            raise UnknownFactorError(name) from exc

    def names(
        self,
        *,
        category: Optional[str] = None,
        tag: Optional[str] = None,
    ) -> tuple[str, ...]:
        names = (
            name
            for name, metadata in self._metadata.items()
            if (category is None or metadata.category == category)
            and (tag is None or tag in metadata.tags)
        )
        return tuple(sorted(names))

    def __contains__(self, name: object) -> bool:
        return name in self._factors

    def __iter__(self) -> Iterator["Factor"]:
        for name in self.names():
            yield self._factors[name]

    def __len__(self) -> int:
        return len(self._factors)
