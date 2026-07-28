from datetime import datetime, timezone
import unittest

from backend.quant_engine import (
    DuplicateFactorError,
    Factor,
    FactorMetadata,
    FactorRegistry,
    FactorResult,
    FactorStatus,
    UnknownFactorError,
)


class CloseFactor(Factor):
    @property
    def name(self) -> str:
        return "close"

    def compute(self, records):
        return [
            FactorResult.valid(
                factor_name=self.name,
                instrument=record["instrument"],
                value=float(record["close"]),
            )
            for record in records
        ]


class FactorContractTests(unittest.TestCase):
    def test_registry_registers_and_filters_factor(self) -> None:
        registry = FactorRegistry()
        factor = CloseFactor()
        metadata = FactorMetadata(
            name="close",
            version="1.0.0",
            description="Raw close for contract testing",
            category="price",
            required_fields=("close",),
            tags=("baseline",),
        )

        registry.register(factor, metadata)

        self.assertIs(registry.get("close"), factor)
        self.assertEqual(registry.names(category="price"), ("close",))
        self.assertEqual(registry.names(tag="baseline"), ("close",))

    def test_registry_rejects_duplicate_and_unknown_factor(self) -> None:
        registry = FactorRegistry()
        metadata = FactorMetadata("close", "1.0.0", "close", "price")
        registry.register(CloseFactor(), metadata)

        with self.assertRaises(DuplicateFactorError):
            registry.register(CloseFactor(), metadata)
        with self.assertRaises(UnknownFactorError):
            registry.get("missing")

    def test_factor_result_serializes_contract_values(self) -> None:
        observed_at = datetime(2026, 7, 28, tzinfo=timezone.utc)
        result = FactorResult.valid(
            factor_name="close",
            instrument="000001.SZ",
            observed_at=observed_at,
            value=12.5,
        )

        self.assertEqual(
            result.to_dict(),
            {
                "factor_name": "close",
                "instrument": "000001.SZ",
                "observed_at": "2026-07-28T00:00:00+00:00",
                "value": 12.5,
                "status": "valid",
                "reason": None,
                "attributes": {},
            },
        )

    def test_invalid_result_requires_reason(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires a reason"):
            FactorResult(
                factor_name="close",
                instrument="000001.SZ",
                observed_at=datetime.now(timezone.utc),
                value=None,
                status=FactorStatus.MISSING,
            )


if __name__ == "__main__":
    unittest.main()
