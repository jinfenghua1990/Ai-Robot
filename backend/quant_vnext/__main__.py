from datetime import date, timedelta

from .contracts import DailyBar, MarketContext
from .pipeline import QuantPipeline


def main() -> None:
    target = date(2026, 3, 21)
    bars = []
    for i in range(80):
        close = 10.0 * (1.01 ** i)
        bars.append(DailyBar(
            ts_code="000001.SZ",
            trade_date=date(2026, 1, 1) + timedelta(days=i),
            open=close * .99,
            high=close * 1.01,
            low=close * .98,
            close=close,
            volume=1000 + i * 10,
            amount=1_000_000 + i * 1000,
            sector="technology",
        ))
    results = QuantPipeline().run(
        {"000001.SZ": bars},
        target,
        MarketContext(target, breadth=.55),
    )
    for result in results:
        print(result.ts_code, result.factor_score, result.resonance.count, result.trading_state)


if __name__ == "__main__":
    main()
