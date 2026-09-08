from backend.api.quant_embedded import _board_stage, _stock_candidate


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
