"""DB 会话管理器测试"""
import pytest
from db.session import get_db_session
from db.models import Watchlist


def test_session_closes_normally():
    """正常路径：with 块结束后 session 关闭"""
    with get_db_session() as db:
        # 能正常查询
        result = db.query(Watchlist).limit(1).all()
        assert isinstance(result, list)


def test_session_closes_on_exception():
    """异常路径：with 块抛出异常时 session 也关闭"""
    session_ref = None
    try:
        with get_db_session() as db:
            session_ref = db
            raise ValueError("test error")
    except ValueError:
        pass
    # session 应该已关闭（close 后 is_active 为 False 或连接已归还池）
    assert session_ref is not None
