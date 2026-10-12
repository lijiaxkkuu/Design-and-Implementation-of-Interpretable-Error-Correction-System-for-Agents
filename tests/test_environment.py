"""项目骨架与环境的基础测试（仅使用标准库 unittest）。"""

import sys
import unittest
from pathlib import Path

# tests/ 的上一级目录即项目根目录
PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAIN_PY = PROJECT_ROOT / "main.py"

MIN_PYTHON = (3, 12)


class TestProjectSkeleton(unittest.TestCase):
    """校验项目入口文件存在，且解释器版本满足要求。"""

    def test_main_py_exists(self) -> None:
        self.assertTrue(
            MAIN_PY.is_file(),
            msg=f"未找到项目入口文件：{MAIN_PY}",
        )

    def test_python_version_is_at_least_3_12(self) -> None:
        current = sys.version_info[:2]
        self.assertGreaterEqual(
            current,
            MIN_PYTHON,
            msg=(
                f"Python 版本过低：当前 {current[0]}.{current[1]}，"
                f"要求不低于 {MIN_PYTHON[0]}.{MIN_PYTHON[1]}；"
                f"当前解释器：{sys.executable}"
            ),
        )


if __name__ == "__main__":
    unittest.main()
