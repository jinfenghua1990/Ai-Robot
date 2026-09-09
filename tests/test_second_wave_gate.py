from backend.api.quant_embedded import _board_stage, _stock_candidate, _trade_levels


def _stock(rank=1, *, day=2.5, drawdown=-6.0, volume_ratio=0.9, slope=3.0, age=15, ret20=12.0):
    return {
        "ts_code": f"60000{rank}.SH",
        "name": f"测试{rank}",
        "sector": "测试行业",
        "rank": rank,
        "score": 72 - rank,
        "qualification": {
            "event_count": 3,
            "days_since_trigger": age,
        },
        "metrics": {
            "ret_5d": 4.0,
            "ret_20d": ret20,
            "ret_60d": 30.0,
            "day_change_pct": day,
            "drawdown": drawdown,
            "above_ma20": True,
            "above_ma60": True,
            "ma20_slope": slope,
            "volume_ratio": volume_ratio,
            "last_price": 20.0,
            "ma20": 18.8,
            "support": 19.1,
            "resistance": 21.6,
            "main_net": 1_000_000,
        },
    }


def test_board_second_wave_startup_requires_first_wave_and_trend():
    stocks = [_stock(1), _stock(2), _stock(3)]
    board = _board_stage("算力", "主题", stocks)
    assert board["eligible"] is True
    assert board["stage"] == "二波启动"
    assert board["grade"] == "A"


def test_board_trend_damage_is_hard_veto():
    stocks = [_stock(1), _stock(2), _stock(3)]
    for stock in stocks:
        stock["metrics"]["above_ma20"] = False
        stock["metrics"]["ma20_slope"] = -3.0
    board = _board_stage("测试", "行业", stocks)
    assert board["eligible"] is False
    assert board["stage"] in {"退潮", "无二波资格"}


def test_core_leader_can_trigger_after_healthy_reset():
    stock = _stock(1, day=3.2, drawdown=-5.0, volume_ratio=1.05)
    board = {
        "name": "算力",
        "kind": "主题",
        "stage": "二波启动",
        "eligible": True,
        "grade": "A",
    }
    result = _stock_candidate(stock, board)
    assert result["leader"] == "核心龙头"
    assert result["structure"] == "二波触发"
    assert result["action"] == "买点触发"
    assert result["levels"]["breakout_reference"] >= result["price"] * 0.995
    assert result["levels"]["defense_reference"] < result["price"]


def test_broken_stock_trend_cannot_be_rescued_by_board_strength():
    stock = _stock(1)
    stock["metrics"]["above_ma20"] = False
    board = {
        "name": "算力",
        "kind": "主题",
        "stage": "二波启动",
        "eligible": True,
        "grade": "A",
    }
    result = _stock_candidate(stock, board)
    assert result["structure"] == "结构破坏"
    assert result["action"] == "不做"


def test_trade_levels_use_nearest_valid_defense_below_price():
    levels = _trade_levels({
        "last_price": 20.0,
        "drawdown": -10.0,
        "ma20": 18.7,
        "support": 19.25,
        "resistance": 22.5,
    })
    assert levels["defense_reference"] == 19.25
    assert levels["defense_basis"] == "趋势支撑"
    assert levels["breakout_reference"] >= 20.0 * 0.995
    assert levels["distance_to_breakout_pct"] >= -0.5


def test_trade_levels_never_use_level_above_price_as_defense():
    levels = _trade_levels({
        "last_price": 20.0,
        "drawdown": -4.0,
        "ma20": 20.5,
        "support": 20.2,
        "resistance": 21.2,
    })
    assert levels["defense_reference"] is None
    assert levels["defense_basis"] is None
