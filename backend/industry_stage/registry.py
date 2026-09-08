"""Single source of truth for A-share SW2021 industry membership.

The legacy ``sector`` columns are kept as compatibility fields in older tables,
but every new write and every historical rebuild should resolve them through
this module.  It deliberately performs database reads only; Tushare syncing
belongs to :mod:`industry_stage.collector`.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import and_, or_

from industry_stage.models import TAXONOMY_VERSION, IndustryStageMembership


def normalize_ts_code(value: str | None) -> str:
    """Return an uppercase Tushare code with an exchange suffix when possible."""
    raw = str(value or "").strip().upper()
    if not raw:
        return ""
    if "." in raw:
        code, suffix = raw.rsplit(".", 1)
        return f"{code}.{suffix}" if suffix in {"SH", "SZ", "BJ"} else raw
    if not raw.isdigit() or len(raw) != 6:
        return raw
    # 北交所 92/83/87/88 代码要先于通用的 9/8 判断。
    if raw.startswith(("4", "8", "92", "83", "87", "88")):
        suffix = "BJ"
    elif raw.startswith(("5", "6", "9")):
        suffix = "SH"
    else:
        suffix = "SZ"
    return f"{raw}.{suffix}"


def _effective_filter(as_of: date):
    return and_(
        or_(IndustryStageMembership.in_date.is_(None), IndustryStageMembership.in_date <= as_of),
        or_(IndustryStageMembership.out_date.is_(None), IndustryStageMembership.out_date >= as_of),
    )


def load_membership_map(db, as_of: date | None = None) -> dict[str, dict]:
    """Load one SW2021 L1/L2/L3 membership row per stock.

    With no date, only rows marked ``is_current`` are considered.  With an
    effective date, the row with the latest ``in_date`` is selected, which
    preserves historical industry changes without applying future membership.
    """
    query = db.query(IndustryStageMembership).filter(
        IndustryStageMembership.version == TAXONOMY_VERSION,
    )
    if as_of is None:
        query = query.filter(IndustryStageMembership.is_current.is_(True))
    else:
        query = query.filter(_effective_filter(as_of))
    rows = query.order_by(
        IndustryStageMembership.ts_code,
        IndustryStageMembership.in_date.desc().nullslast(),
        IndustryStageMembership.id.desc(),
    ).all()

    result: dict[str, dict] = {}
    for row in rows:
        ts_code = normalize_ts_code(row.ts_code)
        if not ts_code or ts_code in result:
            continue
        result[ts_code] = {
            "ts_code": ts_code,
            "stock_name": row.stock_name or "",
            "l1_code": row.l1_code or "",
            "l1_name": row.l1_name or "",
            "l2_code": row.l2_code or "",
            "l2_name": row.l2_name or "",
            "l3_code": row.l3_code or "",
            "l3_name": row.l3_name or "",
            "in_date": row.in_date,
            "out_date": row.out_date,
        }
    return result


def load_sector_map(db, as_of: date | None = None, level: str = "L2") -> dict[str, str]:
    """Return ``ts_code -> SW2021 industry name`` for L1/L2/L3."""
    level = str(level or "L2").upper()
    if level not in {"L1", "L2", "L3"}:
        raise ValueError("level must be L1, L2 or L3")
    field = f"{level.lower()}_name"
    return {
        ts_code: str(row.get(field) or "")
        for ts_code, row in load_membership_map(db, as_of=as_of).items()
        if row.get(field)
    }


def canonical_sector(row_or_code, sector_map: dict[str, str]) -> str:
    """Resolve a row/code to the canonical SW2021 L2 name.

    ``row_or_code`` may be a SQLAlchemy row with ``ts_code`` or a plain code.
    An empty string signals that no SW2021 membership was available; callers
    may then apply an explicit legacy fallback rather than silently guessing.
    """
    code = getattr(row_or_code, "ts_code", row_or_code)
    return sector_map.get(normalize_ts_code(code), "")


def taxonomy_metadata() -> dict:
    """Stable metadata exposed by compatibility APIs and migration reports."""
    return {
        "name": "申万行业分类 2021",
        "version": TAXONOMY_VERSION,
        "source": "Tushare index_classify/index_member_all",
        "industry_level": "L2",
    }
