# Ai-Robot Quant Engine V1 Design

## Status and scope

This document defines the Phase 1 architecture contract. The phase establishes
package boundaries, base interfaces, the factor registry, and the factor result
schema. It does not switch production traffic or implement trading policies.

## Legacy boundary

The following modules remain supported legacy code and are deliberately
unchanged in Phase 1:

- `backend/strategies/`
- `backend/analyzers/`
- `backend/analyzers/stock_scores.py`

New code must not add dependencies from `backend/quant_engine` to these modules.
During later migration phases, adapters may call legacy modules from outside the
new package. This keeps rollback possible and prevents new domain contracts from
being coupled to historical response shapes.

`backend/quant_vnext` is an earlier experimental implementation. It is not
deleted or modified by this phase and is not part of the V1 public API.

## Architecture

The processing direction is:

```text
market data
    -> factors
    -> ranking
    -> resonance + regime
    -> signal

historical data -> research -> factor/policy evidence
```

Package responsibilities:

| Package | Responsibility |
| --- | --- |
| `factors` | Factor computation contracts, metadata, results, discovery |
| `ranking` | Comparable scores and deterministic ordering |
| `resonance` | Agreement across independent factor dimensions |
| `regime` | Market-state classification and risk gating context |
| `signal` | Auditable signal decisions; never order execution |
| `research` | Offline validation, experiments, and reproducibility |

## Contracts

`backend.quant_engine.contracts` contains abstract interfaces. Boundaries accept
plain mappings and sequences for now so implementations can be introduced
without forcing a dataframe or database dependency. More specific immutable
schemas should replace mapping outputs as each subsystem reaches implementation.

The engine separates evidence from decisions:

1. A `Factor` produces `FactorResult` observations.
2. A `Ranker` compares valid observations.
3. `ResonanceDetector` measures cross-dimension agreement.
4. `RegimeDetector` describes the market environment.
5. `SignalGenerator` combines that context into an auditable decision.
6. `ResearchRunner` evaluates the same contracts against historical data.

Signal generation is not order placement. Execution and portfolio mutation stay
outside this package.

## Factor registry

Factors are registered explicitly as an instance plus immutable
`FactorMetadata`. Registration enforces:

- a unique stable name;
- equality between the implementation name and metadata name;
- explicit replacement when intentional;
- deterministic name ordering;
- discovery by category or tag;
- an error for unknown factors.

There is no import-time global registry. Application composition owns registry
lifetime, which makes tests deterministic and avoids plugin import side effects.

## Factor result schema

Each `FactorResult` identifies:

- factor name and instrument;
- timezone-aware observation timestamp;
- finite numeric value when valid;
- status: `valid`, `missing`, `invalid`, or `error`;
- mandatory reason for non-valid results;
- optional structured attributes for lineage and diagnostics.

The schema rejects naive timestamps and non-finite valid values. `to_dict()`
produces JSON-ready enum and timestamp values.

## Compatibility and migration rules

1. Phase 1 does not modify or redirect legacy imports.
2. New components depend only on `backend.quant_engine` contracts.
3. Legacy integration is implemented through adapters, never imports from the
   new core into legacy modules.
4. Production cutover requires side-by-side output comparison and an explicit
   rollback path.
5. Each later phase must be independently committed and validated.

## Planned phases

- Phase 2: concrete core factors, normalization, and ranking schemas.
- Phase 3: resonance and regime policies with deterministic fixtures.
- Phase 4: signal orchestration and legacy adapters in shadow mode.
- Phase 5: research/backtest parity, observability, and controlled cutover.
