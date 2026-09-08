"""工具函数测试"""
import pytest
from utils import stock_code_to_sina, is_trading_day, is_trading_time
from utils.cache import TTLCache
from datetime import datetime


class TestStockCodeToSina:
    def test_sh_code(self):
        assert stock_code_to_sina("600519") == "sh600519"

    def test_sz_code(self):
        assert stock_code_to_sina("000001") == "sz000001"

    def test_bj_code_4(self):
        assert stock_code_to_sina("430047") == "bj430047"

    def test_bj_code_8(self):
        assert stock_code_to_sina("830946") == "bj830946"

    def test_9_prefix(self):
        assert stock_code_to_sina("900901") == "sh900901"

    def test_empty(self):
        assert stock_code_to_sina("") == ""

    def test_already_prefixed(self):
        assert stock_code_to_sina("sh600519") == "sh600519"

    def test_short_code(self):
        assert stock_code_to_sina("123") == ""


class TestIsTradingDay:
    def test_weekday(self):
        # 周一~周五是交易日（粗略判断，不含节假日）
        from datetime import date
        # 选一个已知的周一 2025-01-06
        d = date(2025, 1, 6)
        assert is_trading_day(d) is True

    def test_weekend(self):
        from datetime import date
        d = date(2025, 1, 4)  # 周六
        assert is_trading_day(d) is False


class TestTTLCache:
    def test_set_and_get(self):
        cache = TTLCache(maxsize=10, ttl=60)
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_expired(self):
        cache = TTLCache(maxsize=10, ttl=0)  # 0秒即过期
        cache.set("key1", "value1")
        assert cache.get("key1") is None

    def test_missing_key(self):
        cache = TTLCache(maxsize=10, ttl=60)
        assert cache.get("nonexistent") is None

    def test_eviction(self):
        cache = TTLCache(maxsize=3, ttl=60)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)
        cache.set("d", 4)  # triggers eviction
        assert len(cache) <= 3

    def test_clear(self):
        cache = TTLCache(maxsize=10, ttl=60)
        cache.set("key1", "value1")
        cache.clear()
        assert cache.get("key1") is None
        assert len(cache) == 0
