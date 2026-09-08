from datetime import datetime, timedelta

from services.auto_trade_guard import authorization_reason


def _control(**overrides):
    data = {
        "mode": "full_auto",
        "status": "MONITORING",
        "run_environment": "paper",
        "authorization_expiry_type": "daily",
        "enabled_at": datetime.now().isoformat(),
        "authorization_expired_at": None,
        "actions": {
            "allow_entry": True,
            "allow_add": False,
            "allow_reduce": True,
            "allow_exit": True,
            "allow_stop": True,
            "allow_take_profit": True,
            "allow_trailing": True,
        },
    }
    data.update(overrides)
    return data


def test_missing_control_is_off():
    assert authorization_reason(None, "buy", "paper") is not None
    assert authorization_reason(None, "sell", "paper") is not None


def test_off_and_paused_are_blocked():
    assert authorization_reason(_control(mode="off"), "buy", "paper") is not None
    assert authorization_reason(_control(status="PAUSED"), "sell", "paper") is not None


def test_risk_only_can_sell_but_cannot_buy():
    control = _control(mode="risk_only")
    assert authorization_reason(control, "buy", "paper") is not None
    assert authorization_reason(control, "sell", "paper") is None


def test_full_auto_requires_entry_permission():
    denied = _control(actions={"allow_entry": False, "allow_exit": True})
    assert authorization_reason(denied, "buy", "paper") is not None
    assert authorization_reason(_control(), "buy", "paper") is None


def test_daily_authorization_expires_next_day():
    yesterday = (datetime.now() - timedelta(days=1)).isoformat()
    assert authorization_reason(_control(enabled_at=yesterday), "buy", "paper") is not None


def test_explicit_expiry_is_enforced():
    expired = (datetime.now() - timedelta(minutes=1)).isoformat()
    assert authorization_reason(_control(authorization_expired_at=expired), "sell", "paper") is not None


def test_live_is_fail_closed_until_real_broker_exists():
    assert authorization_reason(_control(run_environment="live"), "sell", "paper") is not None
    assert authorization_reason(_control(), "buy", "live") is not None
