"""Pure A-share market-clock helpers shared by collector and read API."""

from datetime import datetime, time


PHASE_PREOPEN = "PREOPEN"
PHASE_TRADING = "TRADING"
PHASE_BREAK = "BREAK"
PHASE_CLOSED = "CLOSED"
REALTIME_REFRESH_SECONDS = 10
REALTIME_FRESH_SECONDS = 30


def market_phase(now: datetime | None = None, is_market_day: bool | None = None) -> str:
    current = now or datetime.now()
    if current.weekday() >= 5 or is_market_day is False:
        return PHASE_CLOSED

    current_time = current.time()
    if time(9, 25) <= current_time <= time(11, 30):
        return PHASE_TRADING
    if time(11, 30) < current_time < time(13, 0):
        return PHASE_BREAK
    if time(13, 0) <= current_time <= time(15, 0):
        return PHASE_TRADING
    if current_time < time(9, 25):
        return PHASE_PREOPEN
    return PHASE_CLOSED
