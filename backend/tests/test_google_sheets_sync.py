from pathlib import Path

from services import google_sheets_sync as sync


def test_google_symbol_uses_exchange_and_market_prefix():
    assert sync._google_symbol("US", "AAPL", "NASDAQ") == "NASDAQ:AAPL"
    assert sync._google_symbol("US", "SPCU", "") == "NASDAQ:SPCU"
    assert sync._google_symbol("HK", "00700") == "HKG:700"
    assert sync._google_symbol("CN", "600000") == ""


def test_status_does_not_expose_tokens(monkeypatch, tmp_path: Path):
    token_file = tmp_path / "google_token.json"
    token_file.write_text(
        '{"access_token":"secret-access","refresh_token":"secret-refresh",'
        '"spreadsheet_id":"sheet-id","last_sync":"2026-08-11T10:00:00+08:00"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(sync, "GOOGLE_SHEETS_CLIENT_ID", "client-id")
    monkeypatch.setattr(sync, "GOOGLE_SHEETS_CLIENT_SECRET", "client-secret")
    monkeypatch.setattr(sync, "GOOGLE_SHEETS_TOKEN_FILE", str(token_file))

    status = sync.get_status()

    assert status["configured"] is True
    assert status["connected"] is True
    assert status["spreadsheet_id"] == "sheet-id"
    assert "access_token" not in status
    assert "refresh_token" not in status


def test_csv_export_uses_utf8_bom_and_preserves_formula(monkeypatch):
    monkeypatch.setattr(sync, "_collect_snapshot", lambda: {
        "自选": [["市场", "代码", "Google现价"], ["美股", "AAPL", '=IFERROR(GOOGLEFINANCE(G2,"price"),"")']],
        "持仓": [["市场"]], "指标": [["市场"]], "信号": [["市场"]], "说明": [["项目"]],
    })

    output = sync._csv_for_sheet("自选")

    assert output.startswith("\ufeff市场,代码,Google现价")
    assert "GOOGLEFINANCE" in output
