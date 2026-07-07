"""DB 会话上下文管理器

用法:
    with get_db_session() as db:
        rows = db.query(XXX).all()
    # 自动关闭，即使发生异常

向后兼容：原有的 db = next(get_db()) ... db.close() 模式不受影响。
"""
from contextlib import contextmanager
from db.connection import SessionLocal


@contextmanager
def get_db_session():
    """提供自动关闭的 DB 会话，替代 next(get_db()) + try/finally/close"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
