"""Market session helpers with an optional exchange_calendars backend."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

_CALENDAR_NAMES = {"US": "XNYS", "HK": "XHKG"}


def is_session(market: str, day: date) -> bool:
    """Return whether *day* is a trading session for HK/US.

    ``exchange_calendars`` is preferred when installed.  The weekday fallback
    is intentionally conservative and is marked as approximate by callers;
    it never fabricates a bar or changes stored data.
    """

    market = market.upper()
    if market not in _CALENDAR_NAMES or day.weekday() >= 5:
        return False
    try:
        import exchange_calendars as xc
        import pandas as pd

        calendar = xc.get_calendar(_CALENDAR_NAMES[market])
        return bool(calendar.is_session(pd.Timestamp(day)))
    except (ImportError, ModuleNotFoundError):
        return True
    except Exception:
        return True


def now_in_market_timezone(market: str) -> datetime:
    """Return current time in the market's exchange timezone."""

    timezone = "America/New_York" if market.upper() == "US" else "Asia/Hong_Kong"
    return datetime.now(ZoneInfo(timezone))


def latest_completed_session(
    market: str,
    now: datetime | None = None,
    data_delay_minutes: int = 45,
) -> date:
    """Return the latest exchange session whose close data should be available.

    The delay prevents a post-market task from treating the just-closed session
    as ready before public daily-bar providers have published it.  An exchange
    calendar handles holidays, half days and US daylight-saving transitions.
    """

    market = market.upper()
    if market not in _CALENDAR_NAMES:
        raise ValueError(f"unsupported market: {market}")
    timezone = ZoneInfo("America/New_York" if market == "US" else "Asia/Hong_Kong")
    current = now or datetime.now(timezone)
    current = current.replace(tzinfo=timezone) if current.tzinfo is None else current.astimezone(timezone)
    delay = max(0, int(data_delay_minutes))

    try:
        import exchange_calendars as xc
        import pandas as pd

        calendar = xc.get_calendar(_CALENDAR_NAMES[market])
        session = calendar.date_to_session(pd.Timestamp(current.date()), direction="previous")
        current_utc = pd.Timestamp(current).tz_convert("UTC")
        if calendar.session_close(session) + pd.Timedelta(minutes=delay) > current_utc:
            session = calendar.previous_session(session)
        return session.date()
    except (ImportError, ModuleNotFoundError):
        # Conservative fallback for a partially installed environment.  The
        # pinned dependency in requirements.txt is the normal production path.
        cutoff = current - timedelta(minutes=delay)
        candidate = cutoff.date()
        if cutoff.hour < 16:
            candidate -= timedelta(days=1)
        while candidate.weekday() >= 5:
            candidate -= timedelta(days=1)
        return candidate
