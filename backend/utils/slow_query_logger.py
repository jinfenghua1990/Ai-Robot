"""SQLAlchemy 慢查询监听器
- 不需要 PostgreSQL superuser 权限
- 在应用层捕获 >200ms 的 SQL，记录到 logger
- 启用方式：在 main.py 中 import 一次即可
"""
import time
import logging
from sqlalchemy import event
from db.connection import engine

logger = logging.getLogger('slow_query')
SLOW_THRESHOLD_MS = 200


@event.listens_for(engine, 'before_cursor_execute')
def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    context._query_start_time = time.time()


@event.listens_for(engine, 'after_cursor_execute')
def _after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    if not hasattr(context, '_query_start_time'):
        return
    elapsed_ms = (time.time() - context._query_start_time) * 1000
    if elapsed_ms > SLOW_THRESHOLD_MS:
        # 截断 SQL 避免日志过长
        sql_short = statement[:300].replace('\n', ' ')
        if len(statement) > 300:
            sql_short += '...'
        logger.warning(
            f'[slow_query] {elapsed_ms:.0f}ms | {sql_short} | params={str(parameters)[:100]}'
        )
