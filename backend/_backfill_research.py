"""一次性回填：对目标池全量跑研究采集（独立进程，不占用 9000 服务事件循环）。

用法：
  cd /Users/gino/Projects/AIROBOT/backend
  <py3.9> _backfill_research.py
"""
import asyncio
import logging
import sys
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("backfill")

from collectors.research_collector import (
    get_research_targets,
    run_research_collection,
)


async def main():
    today = datetime.now().strftime("%Y-%m-%d")
    targets = get_research_targets(today)
    logger.info(f"目标池共 {len(targets)} 只，开始全量回填（带节流+防重入锁）")
    done = await run_research_collection(today)
    logger.info(f"回填完成：成功 {done}/{len(targets)}")


if __name__ == "__main__":
    asyncio.run(main())
    logger.info("=== BACKFILL EXIT OK ===")
