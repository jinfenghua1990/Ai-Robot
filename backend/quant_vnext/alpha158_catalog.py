"""Research-only mapping from Qlib Alpha158 to the local factor contract.

These definitions are deliberately kept outside :func:`default_registry`.
They document candidates for validation, but cannot enter the live scoring
pipeline until they pass the local IC, stability, and leakage checks.
"""

from __future__ import annotations

from .contracts import FactorDefinition


ALPHA158_RESEARCH_FACTORS: tuple[FactorDefinition, ...] = (
    FactorDefinition(
        "qlib_roc_5d",
        "momentum",
        "qlib_alpha158",
        "Ref($close, 5)/$close",
        ("close",),
        5,
        -1,
    ),
    FactorDefinition(
        "qlib_roc_20d",
        "momentum",
        "qlib_alpha158",
        "Ref($close, 20)/$close",
        ("close",),
        20,
        -1,
    ),
    FactorDefinition(
        "qlib_ma_gap_20d",
        "trend",
        "qlib_alpha158",
        "Mean($close, 20)/$close",
        ("close",),
        20,
        -1,
    ),
    FactorDefinition(
        "qlib_beta_20d",
        "trend",
        "qlib_alpha158",
        "Slope($close, 20)/$close",
        ("close",),
        20,
        1,
    ),
    FactorDefinition(
        "qlib_rsqr_20d",
        "trend",
        "qlib_alpha158",
        "Rsquare($close, 20)",
        ("close",),
        20,
        1,
    ),
    FactorDefinition(
        "qlib_rsv_20d",
        "position",
        "qlib_alpha158",
        "($close-Min($low, 20))/(Max($high, 20)-Min($low, 20)+1e-12)",
        ("close", "high", "low"),
        20,
        1,
    ),
    FactorDefinition(
        "qlib_std_20d",
        "volatility",
        "qlib_alpha158",
        "Std($close, 20)/$close",
        ("close",),
        20,
        -1,
    ),
    FactorDefinition(
        "qlib_corr_price_volume_20d",
        "volume_price",
        "qlib_alpha158",
        "Corr($close, Log($volume+1), 20)",
        ("close", "volume"),
        20,
        1,
    ),
    FactorDefinition(
        "qlib_cntd_20d",
        "momentum",
        "qlib_alpha158",
        "Mean($close>Ref($close, 1), 20)-Mean($close<Ref($close, 1), 20)",
        ("close",),
        20,
        1,
    ),
    FactorDefinition(
        "qlib_sump_20d",
        "momentum",
        "qlib_alpha158",
        "Sum(Greater($close-Ref($close, 1), 0), 20)/(Sum(Abs($close-Ref($close, 1)), 20)+1e-12)",
        ("close",),
        20,
        1,
    ),
    FactorDefinition(
        "qlib_vma_20d",
        "volume_price",
        "qlib_alpha158",
        "Mean($volume, 20)/($volume+1e-12)",
        ("volume",),
        20,
        -1,
    ),
    FactorDefinition(
        "qlib_vstd_20d",
        "volatility",
        "qlib_alpha158",
        "Std($volume, 20)/($volume+1e-12)",
        ("volume",),
        20,
        -1,
    ),
    FactorDefinition(
        "qlib_wvma_20d",
        "volume_price",
        "qlib_alpha158",
        "Std(Abs($close/Ref($close, 1)-1)*$volume, 20)/(Mean(Abs($close/Ref($close, 1)-1)*$volume, 20)+1e-12)",
        ("close", "volume"),
        20,
        -1,
    ),
)


def alpha158_research_registry() -> list[FactorDefinition]:
    """Return a copy so callers cannot mutate the catalog accidentally."""

    return list(ALPHA158_RESEARCH_FACTORS)
