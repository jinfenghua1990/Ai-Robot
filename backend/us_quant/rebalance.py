"""
US Quant System — 股票池自动再平衡引擎

V2.2 架构冻结: 按配置驱动，自动填充池到目标数量。

策略:
- US_CORE_A: 按市值排名的 Top 300
- US_CORE_B: 按市值排名的 301-800
- US_RESEARCH: 剩余活跃美股（去重后）
- 支持 dry-run 模式预览变更
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)


def _db_conn():
    try:
        from db.session import SessionLocal
        s = SessionLocal()
        return s, s.close
    except Exception:
        return None, None


def get_universe_definitions() -> list[dict]:
    """从数据库读取所有池定义"""
    s, close = _db_conn()
    if not s:
        logger.warning("[rebalance] 无法连接数据库")
        return []
    try:
        rows = s.execute(text("""
            SELECT universe_code, name, target_count, rebalance_frequency, tier, rules
            FROM universe_definitions WHERE is_active ORDER BY sort_order NULLS LAST, universe_code
        """)).fetchall()
        result = []
        for r in rows:
            cnt = s.execute(
                text("SELECT COUNT(*) FROM universe_memberships WHERE universe_code=:c AND effective_to IS NULL"),
                {"c": r[0]}
            ).scalar()
            result.append({
                "code": r[0], "name": r[1], "target_count": r[2],
                "rebalance_frequency": r[3], "tier": r[4], "rules": r[5] or {},
                "current_count": cnt or 0,
            })
        return result
    except Exception as e:
        logger.error(f"[rebalance] 读取定义失败: {e}")
        return []
    finally:
        close()


def get_all_us_instruments() -> list[dict]:
    """获取所有活跃美股（按市值降序）"""
    s, close = _db_conn()
    if not s:
        return []
    try:
        rows = s.execute(text("""
            SELECT id, symbol, name, market_cap, sector, industry
            FROM instruments
            WHERE market = 'US' AND is_active = true
            ORDER BY market_cap DESC NULLS LAST
        """)).fetchall()
        return [
            {"id": r[0], "symbol": r[1], "name": r[2],
             "market_cap": float(r[3]) if r[3] else 0,
             "sector": r[4], "industry": r[5]}
            for r in rows
        ]
    except Exception as e:
        logger.error(f"[rebalance] 读取美股列表失败: {e}")
        return []
    finally:
        close()


def get_current_members(code: str) -> set[int]:
    """获取池当前成员（instrument_id 集合）"""
    s, close = _db_conn()
    if not s:
        return set()
    try:
        rows = s.execute(
            text("SELECT instrument_id FROM universe_memberships WHERE universe_code=:c AND effective_to IS NULL"),
            {"c": code}
        ).fetchall()
        return {r[0] for r in rows}
    except Exception as e:
        logger.error(f"[rebalance] 读取 {code} 成员失败: {e}")
        return set()
    finally:
        close()


def assign_pools(
    instruments: list[dict],
    existing: dict[str, set[int]],
    definitions: list[dict],
) -> dict[str, list[int]]:
    """按配置分配股票到各池

    Args:
        instruments: 所有美股（按市值降序）
        existing: 各池现有成员 {pool_code: set(instrument_ids)}
        definitions: 池定义列表

    Returns:
        {pool_code: [instrument_ids to add]}
    """
    # 构建池层级
    tiers = {"core_a": [], "core_b": [], "research": [], "other": []}
    for d in definitions:
        if d["code"] == "US_CORE_A":
            tiers["core_a"].append(d)
        elif d["code"] == "US_CORE_B":
            tiers["core_b"].append(d)
        elif d["code"] == "US_RESEARCH":
            tiers["research"].append(d)
        else:
            tiers["other"].append(d)

    # 按市值分配到各池
    used_ids: set[int] = set()
    result: dict[str, list[int]] = {}

    for pool_list in [tiers["core_a"], tiers["core_b"], tiers["research"], tiers["other"]]:
        for d in pool_list:
            target = d["target_count"]
            if target is None:
                continue
            existing_ids = existing.get(d["code"], set())
            current = len(existing_ids)
            need = max(0, target - current)

            # 从未分配且未使用的股票中选取
            available = [inst for inst in instruments if inst["id"] not in used_ids]
            to_add = [inst["id"] for inst in available[:need]]

            result[d["code"]] = to_add
            used_ids.update(to_add)

    return result


def apply_rebalance(
    assignments: dict[str, list[int]],
    definitions: list[dict],
    dry_run: bool = True,
) -> dict:
    """执行再平衡

    Args:
        assignments: {pool_code: [instrument_ids to add]}
        definitions: 池定义列表
        dry_run: True = 只预览，False = 写入数据库

    Returns:
        rebalance 报告
    """
    s, close = _db_conn()
    if not s:
        return {"status": "error", "message": "无法连接数据库"}

    report = {
        "status": "dry_run" if dry_run else "applied",
        "timestamp": datetime.now().isoformat(),
        "pools": [],
        "total_added": 0,
    }

    try:
        for d in definitions:
            code = d["code"]
            to_add = assignments.get(code, [])
            if not to_add:
                report["pools"].append({
                    "code": code, "name": d["name"],
                    "target": d["target_count"],
                    "current": d["current_count"],
                    "added": 0, "message": "已达标",
                })
                continue

            if not dry_run:
                rank_start = d["current_count"] + 1
                for i, inst_id in enumerate(to_add):
                    s.execute(
                        text("""
                            INSERT INTO universe_memberships (universe_code, instrument_id, rank, effective_from, created_at)
                            VALUES (:code, :inst_id, :rank, :eff_date, NOW())
                            ON CONFLICT (universe_code, instrument_id, effective_to) DO NOTHING
                        """),
                        {
                            "code": code, "inst_id": inst_id,
                            "rank": rank_start + i,
                            "eff_date": date.today(),
                        }
                    )
                s.commit()
                logger.info(f"[rebalance] {code}: 添加 {len(to_add)} 只")

            report["pools"].append({
                "code": code, "name": d["name"],
                "target": d["target_count"],
                "current": d["current_count"],
                "added": len(to_add),
                "new_total": d["current_count"] + len(to_add),
                "message": f"需添加 {len(to_add)} 只" if len(to_add) > 0 else "已达标",
            })
            report["total_added"] += len(to_add)

        if not dry_run:
            s.commit()

    except Exception as e:
        s.rollback()
        logger.error(f"[rebalance] 执行失败: {e}")
        report["status"] = "error"
        report["message"] = str(e)
    finally:
        close()

    return report


def run_rebalance(dry_run: bool = True) -> dict:
    """运行完整再平衡流程

    Args:
        dry_run: True = 预览，False = 执行

    Returns:
        再平衡报告
    """
    # 1. 读取定义
    definitions = get_universe_definitions()
    if not definitions:
        return {"status": "error", "message": "无池定义"}

    # 2. 读取所有美股
    instruments = get_all_us_instruments()
    logger.info(f"[rebalance] 共 {len(instruments)} 只美股")

    # 3. 读取现有成员
    existing = {}
    for d in definitions:
        existing[d["code"]] = get_current_members(d["code"])

    # 4. 分配
    assignments = assign_pools(instruments, existing, definitions)

    # 5. 应用
    report = apply_rebalance(assignments, definitions, dry_run=dry_run)

    # 6. 统计
    new_instruments = get_all_us_instruments()
    report["total_instruments"] = len(new_instruments)

    return report