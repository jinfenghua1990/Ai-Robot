"""DB 会话上下文管理器

用法:
    with get_db_session() as db:
        rows = db.query(XXX).all()
    # 自动关闭，即使发生异常

向后兼容：原有的 db = next(get_db()) ... db.close() 模式不受影响。
"""
from contextlib import contextmanager
from db.connection import SessionLocal
from starlette.concurrency import run_in_threadpool


@contextmanager
def get_db_session():
    """提供自动关闭的 DB 会话，替代 next(get_db()) + try/finally/close"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


async def run_db(func, *args, **kwargs):
    """在独立线程中执行同步 DB 操作，避免阻塞 asyncio 事件循环。

    后端用同步 psycopg2 驱动；在 async 接口里直接调 db.query()/db.commit()
    会卡住整个事件循环，并发请求被迫串行。把同步 DB 段交给线程池即可解除阻塞。

    用法:
        rows = await run_db(lambda: db.query(Model).all())
        result = await run_db(_some_sync_db_func, arg1, arg2)
    """
    return await run_in_threadpool(func, *args, **kwargs)
