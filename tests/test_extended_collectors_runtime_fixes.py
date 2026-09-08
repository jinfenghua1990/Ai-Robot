from __future__ import annotations

import sys
from types import SimpleNamespace


def test_mootdx_pytdx_fallback_disconnects_once_after_batch(monkeypatch):
    import collectors.extended_collectors as ext
    import collectors.tdx_collector as tdx

    class FakeApi:
        def __init__(self):
            self.disconnected = False
            self.disconnect_count = 0
            self.calls = []

        def get_security_quotes(self, symbols):
            assert not self.disconnected, "connection was closed before batch finished"
            self.calls.append(symbols)
            return [{"price": 11.0, "last_close": 10.0}]

        def disconnect(self):
            self.disconnect_count += 1
            self.disconnected = True

    api = FakeApi()
    monkeypatch.setattr(ext, "_get_mootdx_reader", lambda: "pytdx")
    monkeypatch.setattr(ext, "_mootdx_use_pytdx", True)
    monkeypatch.setattr(tdx, "connect_with_retry", lambda: (api, "fake-server"))

    result = ext.mootdx_batch_quotes(["000001.SZ", "600000.SH", "000002.SZ"])

    assert set(result) == {"000001.SZ", "600000.SH", "000002.SZ"}
    assert len(api.calls) == 3
    assert api.disconnect_count == 1


def test_baostock_uses_close_field_not_low_and_logs_out(monkeypatch):
    import collectors.extended_collectors as ext

    class FakeResult:
        error_code = "0"

        def __init__(self):
            self._done = False

        def next(self):
            if self._done:
                return False
            self._done = True
            return True

        def get_row_data(self):
            # date, code, open, high, low, close, preclose, volume, amount, pctChg, turn
            return ["2026-09-08", "sz.000001", "10.0", "11.0", "9.0", "10.5", "10.0", "1", "2", "5.0", "1.2"]

    state = {"logout": 0}
    fake_bs = SimpleNamespace(
        login=lambda: SimpleNamespace(error_code="0", error_msg=""),
        query_history_k_data_plus=lambda *args, **kwargs: FakeResult(),
        logout=lambda: state.__setitem__("logout", state["logout"] + 1),
    )
    monkeypatch.setitem(sys.modules, "baostock", fake_bs)

    result = ext.baostock_daily_kline("000001.SZ", days=3)

    assert result is not None
    assert result["close"] == 10.5
    assert result["close"] != 9.0
    assert result["pct_chg"] == 5.0
    assert state["logout"] == 1


def test_baostock_rejects_beijing_symbol_instead_of_misrouting_to_shenzhen(monkeypatch):
    import collectors.extended_collectors as ext

    # No import/login should be attempted for a BJ symbol.
    monkeypatch.delitem(sys.modules, "baostock", raising=False)
    result = ext.baostock_daily_kline("920001.BJ", days=3)
    assert result is None
