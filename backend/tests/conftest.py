"""让 backend/tests 可从仓库根目录独立运行。"""
import sys
from pathlib import Path


backend_dir = str(Path(__file__).resolve().parents[1])
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)
