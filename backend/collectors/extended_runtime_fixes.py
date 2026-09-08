"""Runtime correctness fixes for legacy extended collectors.

This module patches two known defects in ``extended_collectors`` while keeping
that large legacy file stable:

1. pytdx fallback disconnected inside the per-symbol loop, so only the first
   quote was reliable.
2. baostock parsed ``low`` (index 4) as ``close`` instead of index 5, and did
   not reliably logout.

The patch is applied once from ``collectors.__init__`` so all normal imports of
``collectors.extended_collectors`` receive the corrected behavior.
"""
from __future__ import annotations

from datetime import datetime, timedelta


def apply_extended_collector_fixes() -> None:
    from collectors import extended_collectors as ext

    if getattr(ext, "_AIROBOT_RUNTIME_FIXES_APPLIED", False):
        return

    original_mootdx_batch_quotes = ext.mootdx_batch_quotes

    def fixed_mootdx_batch_quotes(ts_codes):
        """Keep one pytdx connection alive for the whole batch."""
        try:
            reader = ext._get_mootdx_reader()
            if not reader:
                ext._record_call("mootdx", False, "no mootdx or pytdx available")
                return {}

            # Native mootdx path was not affected by the disconnect bug.
            if not ext._mootdx_use_pytdx:
                return original_mootdx_batch_quotes(ts_codes)

            from collectors.tdx_collector import connect_with_retry

            api, _server = connect_with_retry()
            if not api:
                ext._record_call("mootdx", False, "pytdx connect failed")
                return {}

            result = {}
            try:
                for ts_code in ts_codes[:30]:
                    try:
                        code = ext._ts_to_code(ts_code)
                        if ts_code.endswith(".SZ"):
                            market = 0
                        elif ts_code.endswith(".SH"):
                            market = 1
                        else:
                            # pytdx standard HQ does not safely map BJ symbols.
                            continue
                        quotes = api.get_security_quotes([(market, code)])
                        if not quotes:
                            continue
                        quote = quotes[0]
                        price = float(quote.get("price", 0) or quote.get("last_close", 0) or 0)
                        pre_close = float(quote.get("last_close", 0) or 0)
                        pct_chg = ((price - pre_close) / pre_close * 100) if pre_close > 0 else 0
                        result[ts_code] = {
                            "price": price,
                            "price_chg": round(pct_chg, 2),
                        }
                    except Exception:
                        ext.logger.debug("mootdx pytdx item failed", exc_info=True)
            finally:
                try:
                    api.disconnect()
                except Exception:
                    ext.logger.debug("mootdx pytdx disconnect failed", exc_info=True)

            if result:
                ext._record_call("mootdx", True)
            else:
                ext._record_call("mootdx", False, "pytdx no data")
            return result
        except Exception as exc:
            ext._record_call("mootdx", False, str(exc))
            return {}

    def fixed_baostock_daily_kline(ts_code, days=5):
        """Parse baostock close correctly and always release the session."""
        try:
            import baostock as bs

            code = ext._ts_to_code(ts_code)
            if ts_code.endswith(".SH"):
                bs_code = f"sh.{code}"
            elif ts_code.endswith(".SZ"):
                bs_code = f"sz.{code}"
            else:
                ext._record_call("baostock", False, f"unsupported market: {ts_code}")
                return None

            end_date = datetime.now().strftime("%Y-%m-%d")
            start_date = (datetime.now() - timedelta(days=days * 2)).strftime("%Y-%m-%d")

            login = bs.login()
            if login.error_code != "0":
                ext._record_call("baostock", False, f"login: {login.error_msg}")
                return None

            try:
                rs = bs.query_history_k_data_plus(
                    bs_code,
                    "date,code,open,high,low,close,preclose,volume,amount,pctChg,turn",
                    start_date=start_date,
                    end_date=end_date,
                    frequency="d",
                )
                rows = []
                while rs.error_code == "0" and rs.next():
                    rows.append(rs.get_row_data())

                if not rows:
                    ext._record_call("baostock", False, "no data")
                    return None

                latest = rows[-1]
                result = {
                    "date": latest[0],
                    # fields: date, code, open, high, low, close, ...
                    "close": float(latest[5]) if latest[5] else 0,
                    "pct_chg": float(latest[9]) if latest[9] else 0,
                    "turn": float(latest[10]) if latest[10] else 0,
                }
                ext._record_call("baostock", True)
                return result
            finally:
                try:
                    bs.logout()
                except Exception:
                    ext.logger.debug("baostock logout failed", exc_info=True)
        except Exception as exc:
            ext._record_call("baostock", False, str(exc))
            return None

    ext.mootdx_batch_quotes = fixed_mootdx_batch_quotes
    ext.baostock_daily_kline = fixed_baostock_daily_kline
    # baostock_batch_quotes resolves baostock_daily_kline from module globals
    # at call time, so replacing the module attribute fixes the batch path too.
    ext._AIROBOT_RUNTIME_FIXES_APPLIED = True
