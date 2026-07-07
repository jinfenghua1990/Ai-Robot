"""
一次性脚本：回填 watchlist.stock_name（来自同花顺/新浪同步时遗漏的空名称）

数据源：akshare stock_zh_a_spot() 全市场实时行情（含 '名称' 列）
用法：python -m scripts.backfill_watchlist_name [--dry-run]
"""
import argparse
import os
import sys

# 保证 backend 包可被导入
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.http_constants import clear_proxy_env
clear_proxy_env()

from db import get_db  # noqa: E402
from db.models import Watchlist  # noqa: E402


def fetch_code_name_map():
    """从 akshare 拉取全市场 代码 -> 名称 映射（同时返回 带后缀 和 纯数字 两种 key）
    使用 stock_info_a_code_name() 而非 spot 行情接口（更快、更稳定）
    """
    try:
        import akshare as ak
    except ImportError:
        print('[backfill] akshare 未安装，跳过')
        return {}

    code_name = {}
    try:
        df = ak.stock_info_a_code_name()
        # 列：code, name
        for _, row in df.iterrows():
            bare = str(row['code']).strip()  # 纯数字代码，如 600519
            name = str(row.get('name', '')).strip()
            if not name:
                continue
            code_name[bare] = name
            # 推断 ts_code 后缀
            if bare.startswith('6') or bare.startswith('9'):
                code_name[f"{bare}.SH"] = name
            elif bare.startswith('4') or bare.startswith('8'):
                code_name[f"{bare}.BJ"] = name
            else:
                code_name[f"{bare}.SZ"] = name
        print(f'[backfill] akshare 返回 {len(code_name)} 条名称映射（含双重 key）')
    except Exception as e:
        print(f'[backfill] akshare stock_info_a_code_name 错误: {e}，回退到 stock_zh_a_spot')
        try:
            df = ak.stock_zh_a_spot()
            for _, row in df.iterrows():
                code = str(row['代码'])
                if code.startswith('sh'):
                    tc, bare = f"{code[2:]}.SH", code[2:]
                elif code.startswith('sz'):
                    tc, bare = f"{code[2:]}.SZ", code[2:]
                elif code.startswith('bj'):
                    tc, bare = f"{code[2:]}.BJ", code[2:]
                else:
                    continue
                name = str(row.get('名称', '')).strip()
                if name:
                    code_name[tc] = name
                    code_name[bare] = name
            print(f'[backfill] 回退后返回 {len(code_name)} 条名称映射')
        except Exception as e2:
            print(f'[backfill] stock_zh_a_spot 也失败: {e2}')
    return code_name


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true', help='仅打印，不写入数据库')
    args = parser.parse_args()

    code_name = fetch_code_name_map()
    if not code_name:
        print('[backfill] 无可用名称数据，退出')
        return

    with get_db_session() as db:
        items = db.query(Watchlist).filter(
            (Watchlist.stock_name == None) | (Watchlist.stock_name == '')  # noqa: E711
        ).all()
        print(f'[backfill] 待回填 watchlist 行数: {len(items)}')

        updated = 0
        skipped = []
        for it in items:
            name = code_name.get(it.stock_code)
            if name:
                if not args.dry_run:
                    it.stock_name = name
                updated += 1
            else:
                skipped.append(it.stock_code)

        if not args.dry_run:
            db.commit()

        print(f'[backfill] {"模拟" if args.dry_run else "实际"}回填完成: {updated} 条')
        if skipped:
            print(f'[backfill] 未找到名称（{len(skipped)} 条）: {skipped[:20]}')


if __name__ == '__main__':
    main()
