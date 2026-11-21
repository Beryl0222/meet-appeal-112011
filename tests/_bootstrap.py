"""测试引导：在隔离模式（python3 -I）下把仓库根加入模块搜索路径。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
