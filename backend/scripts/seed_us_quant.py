#!/usr/bin/env python3
"""US Quant — 一次性扫描 + 种子脚本（让系统有真实可看的数据）。

做什么：
  1. 用可插拔数据源（us_quant.data_provider：Nasdaq 实时主源 → Yahoo 兜底 → 离线模拟）拉行情；
  2. 用现有策略引擎（indicators / strategies / filters / states）对 watchlist 评分；
  3. 通过 scanner.create_signal 生成信号，落库 us_signals；
  4. 额外造一批「跨生命周期状态」的样本信号 + 样本持仓，便于演示；
  5. 幂等：先清空 us_signals / us_positions 再写入。

运行（必须在 backend 目录下用后端同款解释器）：
    cd /Users/gino/Projects/AIROBOT/backend
    /usr/bin/python3 scripts/seed_us_quant.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import random
from datetime import datetime, timedelta, date

from db.session import get_db_session
from us_quant.repository import ensure_schema, USSignal, USPosition
from us_quant.data_provider import get_klines, get_quote
from us_quant.indicators import (
    ema, sma, rsi as calc_rsi, macd as calc_macd, kdj as calc_kdj,
)
from us_quant.strategies import score_breakout, score_pullback
from us_quant.filters import check_hard_filters
from us_quant.states import determine_stock_state
from us_quant.scanner import create_signal

WATCHLIST = [
    ("AAPL", "Apple"), ("MSFT", "Microsoft"), ("GOOGL", "Alphabet"),
    ("AMZN", "Amazon"), ("NVDA", "NVIDIA"), ("TSLA", "Tesla"),
    ("META", "Meta"), ("TSM", "TSMC"), ("AMD", "AMD"), ("NFLX", "Netflix"),
    ("COIN", "Coinbase"), ("PLTR", "Palantir"),
    ("XLK", "Technology ETF"), ("SMH", "Semiconductor ETF"),
    ("XLF", "Financial ETF"), ("XLE", "Energy ETF"),
]


def score_symbol(symbol: str):
    klines = get_klines(symbol, "3mo")
    if not klines or len(klines) < 5:
        return None
    closes = [k["close"] for k in klines if k.get("close")]
    highs = [k["high"] for k in klines if k.get("high")]
    lows = [k["low"] for k in klines if k.get("low")]
    volumes = [k["volume"] for k in klines if k.get("volume")]
    price = closes[-1]
    if not price:
        return None

    ema10 = ema(closes, 10)
    ema20 = ema(closes, 20)
    ma50 = sma(closes, 50)
    rsi_val = calc_rsi(closes, 14)
    macd_val = calc_macd(closes)
    kdj_val = calc_kdj(closes)

    e10 = ema10[-1] if ema10 else None
    e20 = ema20[-1] if ema20 else None
    m50 = ma50[-1] if ma50 else None

    hf = check_hard_filters(price=price)
    high_52w = max(closes[-252:]) if len(closes) >= 252 else max(closes)
    base_high = max(closes[-20:]) if len(closes) >= 20 else max(closes)
    base_low = min(closes[-20:]) if len(closes) >= 20 else min(closes)
    rel_vol = (volumes[-1] / (sum(volumes[-5:]) / 5)) if len(volumes) >= 5 else 1.0
    change_today = (closes[-1] - closes[-2]) / closes[-2] * 100 if len(closes) >= 2 else 0

    bs = score_breakout(
        price=price, ema10=e10, ema20=e20, ma50=m50, high_52w=high_52w,
        base_high=base_high, base_low=base_low, base_days=20, rel_volume=rel_vol,
        change_pct_today=change_today, market_mult=1.0,
    )
    prior_up = bool(e10 and e20 and m50 and e10 > e20 > m50)
    pb = None
    if len(closes) >= 10:
        peak = max(closes[-10:])
        pb = (peak - price) / peak * 100
    ps = score_pullback(
        price=price, ema10=e10, ema20=e20, ma50=m50, prior_uptrend=prior_up,
        first_pullback=True, pullback_pct=pb, volume_contracted=True,
        no_consecutive_bearish=True, market_mult=1.0,
    )
    state = determine_stock_state(price=price, ma20=e20, ma50=m50, rsi=rsi_val)
    stop = round(m50 * 0.97, 2) if (m50 and price) else round(price * 0.95, 2)

    bo = bs.total if getattr(bs, "hard_pass", False) else None
    pbk = ps.total if getattr(ps, "hard_pass", False) else None
    return {
        "symbol": symbol, "price": price, "rsi": rsi_val,
        "state_label": state.label, "breakout": bo, "pullback": pbk,
        "hard_pass": hf.passed, "stop": stop,
        "indicators": {"macd": macd_val, "kdj": kdj_val},
    }


def main():
    ensure_schema()
    with get_db_session() as db:
        # 幂等清空
        deleted_sig = db.query(USSignal).delete()
        deleted_pos = db.query(USPosition).delete()

        # 1) 扫描生成信号
        scanned = 0
        for sym, name in WATCHLIST:
            try:
                r = score_symbol(sym)
                if not r or not r["hard_pass"]:
                    continue
                bo = r["breakout"] or 0.0
                pbk = r["pullback"] or 0.0
                strat = "breakout" if bo >= pbk else "pullback"
                score = max(bo, pbk)
                if score < 30:
                    continue
                sig = create_signal(
                    symbol=sym, name=name, strategy=strat, strategy_version="2.1.1",
                    score=round(score, 2), planned_entry=round(r["price"], 2),
                    planned_stop=r["stop"],
                    expected_rr=round((r["price"] - r["stop"]) / r["stop"] * 100, 2) if r["stop"] else None,
                    market_regime="LIVE", sector_rank=0,
                    trigger_details={"state": r["state_label"], "rsi": round(r["rsi"], 1) if r["rsi"] else None},
                )
                db.add(USSignal(
                    symbol=sig.symbol, name=sig.name, strategy=sig.strategy,
                    strategy_version=sig.strategy_version, signal_type=sig.signal_type,
                    lifecycle_status=sig.lifecycle_status, score=sig.score,
                    signal_time=sig.signal_time, expires_at=sig.expires_at,
                    planned_entry=sig.planned_entry, planned_stop=sig.planned_stop,
                    planned_target=sig.planned_target, expected_rr=sig.expected_rr,
                    risk_veto=sig.risk_veto, trigger_details=sig.trigger_details,
                    market_regime=sig.market_regime, sector_rank=sig.sector_rank,
                ))
                scanned += 1
            except Exception as exc:  # 单只失败不影响其余
                print(f"  [skip] {sym}: {exc}")

        # 2) 样本信号：覆盖多种生命周期状态，保证演示丰富
        now = datetime.utcnow()
        samples = [
            ("NVDA", "NVIDIA", "breakout", "TRIGGERED", 128.4, 118.0, 2.1),
            ("TSLA", "Tesla", "pullback", "ACTIVE", 255.0, 240.0, 1.8),
            ("AMD", "AMD", "breakout", "WATCHING", 162.0, 150.0, 2.4),
            ("COIN", "Coinbase", "breakout", "SCORED", 245.0, 220.0, 1.5),
            ("META", "Meta", "pullback", "DISCOVERED", 515.0, 498.0, 2.0),
            ("PLTR", "Palantir", "breakout", "CLOSED", 38.5, 30.0, 3.2),
            ("NFLX", "Netflix", "pullback", "APPROVED", 680.0, 650.0, 1.9),
        ]
        for sym, name, strat, status, entry, stop, rr in samples:
            db.add(USSignal(
                symbol=sym, name=name, strategy=strat, strategy_version="2.1.1",
                signal_type="ENTRY", lifecycle_status=status,
                score=round(random.uniform(55, 92), 2),
                signal_time=now - timedelta(days=random.randint(0, 3)),
                expires_at=now + timedelta(days=3),
                planned_entry=entry, planned_stop=stop, expected_rr=rr,
                market_regime="LIVE", sector_rank=0,
                trigger_details={"sample": True},
            ))

        # 3) 样本持仓（current_price 取实时行情，不再写死）
        positions = [
            ("TSLA", "Tesla", "pullback", 250.0, 100, "Technology", 238.0),
            ("NVDA", "NVIDIA", "breakout", 120.0, 200, "Semiconductors", 112.0),
            ("COIN", "Coinbase", "breakout", 220.0, 30, "Financial", 210.0),
        ]
        for sym, name, strat, ep, qty, sector, stop in positions:
            q = get_quote(sym)
            cp = float(q["price"]) if (q and q.get("price")) else ep
            pl = (cp - ep) * qty
            db.add(USPosition(
                symbol=sym, name=name, strategy=strat, entry_price=ep, current_price=round(cp, 2),
                quantity=qty, cost_basis=ep * qty, market_value=cp * qty,
                unrealized_pl=pl, unrealized_pl_pct=round((cp - ep) / ep * 100, 2),
                stop_price=stop, entry_date=date.today() - timedelta(days=random.randint(3, 20)),
                holding_days=random.randint(3, 20), sector=sector,
                risk_group="LIVE", status="ACTIVE",
            ))

        db.commit()
        print(f"OK: 清空原信号 {deleted_sig} / 持仓 {deleted_pos}；"
              f"新写入 扫描信号 {scanned} + 样本信号 {len(samples)} + 样本持仓 {len(positions)}")


if __name__ == "__main__":
    main()
