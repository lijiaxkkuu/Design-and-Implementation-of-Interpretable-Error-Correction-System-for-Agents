"""展示层测试：轨迹可以查看完整 JSON，耗时展示与计算口径一致。

这些测试直接检查展示模型（trace_view）与界面源码（app.py），
不需要启动 Streamlit 服务，也不需要浏览器。
"""

import json
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import agent_core  # noqa: E402  （需先补充 sys.path）
import trace_view  # noqa: E402

APP_SOURCE = (PROJECT_ROOT / "app.py").read_text(encoding="utf-8")


class TestTraceTableView(unittest.TestCase):
    """执行轨迹的展示模型：表格只放摘要，完整 JSON 单独提供。"""

    def setUp(self) -> None:
        self.result = agent_core.run_experiment("1002")

    def test_table_rows_keep_short_summaries(self) -> None:
        rows = trace_view.trace_table_rows(self.result.trace)

        self.assertEqual(len(rows), len(self.result.trace))
        for row in rows:
            self.assertTrue(str(row["返回摘要"]).strip())
            self.assertIn(row["状态"], ("成功", "错误", "信息"))
            self.assertNotIn("实际返回结果", row)

    def test_details_contain_complete_json_for_every_step(self) -> None:
        details = trace_view.trace_step_details(self.result.trace)

        self.assertEqual(len(details), len(self.result.trace))
        for detail, entry in zip(details, self.result.trace):
            # 完整 JSON 可以原样还原成轨迹中的对象：没有被截断，也没有被摘要替换
            self.assertEqual(json.loads(detail["result_json"]), entry["result"])
            self.assertEqual(json.loads(detail["arguments_json"]), entry["arguments"])
            self.assertIn(str(entry["step"]), detail["title"])

    def test_long_json_is_kept_intact(self) -> None:
        """长返回内容（错误诊断）必须完整保留，而不是截断后的片段。"""
        detail = trace_view.trace_step_details(self.result.trace)[2]  # 第 3 步：错误诊断
        payload = json.loads(detail["result_json"])

        self.assertIn("evidence", payload)
        self.assertIn("repair_basis", payload)
        self.assertEqual(payload["cause"], self.result.diagnosis["cause"])
        self.assertEqual(
            payload["evidence"],
            self.result.diagnosis["evidence"],
        )
        # indent=2 的完整文本应比单行压缩文本更长，说明没有被裁掉
        self.assertGreater(
            len(detail["result_json"]),
            len(json.dumps(self.result.diagnosis, ensure_ascii=False)),
        )

    def test_missing_summary_falls_back_to_message(self) -> None:
        trace = [
            {
                "step": 1,
                "phase": "任务解析",
                "action": "解析用户输入",
                "tool": "-",
                "arguments": {"raw_input": "1002"},
                "result": {"message": "查询成功"},
                "status": "info",
            }
        ]
        rows = trace_view.trace_table_rows(trace)

        self.assertEqual(rows[0]["返回摘要"], "查询成功")
        self.assertEqual(rows[0]["状态"], "信息")


class TestAppContract(unittest.TestCase):
    """界面源码必须使用统一的耗时换算，并提供完整 JSON 的查看入口。"""

    def test_app_uses_core_duration_helper(self) -> None:
        self.assertIn("agent_core.describe_elapsed", APP_SOURCE)
        # 旧的两位小数写法（数值过小会显示成 0.00）不应再出现
        self.assertNotIn("round(elapsed * 1000, 2)", APP_SOURCE)

    def test_app_renders_full_json_details(self) -> None:
        self.assertIn("trace_view.trace_step_details", APP_SOURCE)
        self.assertIn("实际返回结果（完整 JSON）", APP_SOURCE)
        # 长 JSON 不应再直接塞进表格单元格
        self.assertNotIn('"实际返回结果": _plain(entry["result"])', APP_SOURCE)


class TestAppRendering(unittest.TestCase):
    """用 Streamlit 自带的 AppTest 真正渲染一次界面（不启动浏览器）。"""

    @classmethod
    def setUpClass(cls) -> None:
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=60)
        app.run()
        app.button[0].click().run()
        cls.app = app

    def test_render_has_no_exception(self) -> None:
        self.assertFalse(self.app.exception)

    def test_every_trace_step_has_full_json_expander(self) -> None:
        labels = [expander.label for expander in self.app.expander]
        trace_expanders = [label for label in labels if "查看完整参数与返回" in label]

        self.assertEqual(len(trace_expanders), 6)
        for label in trace_expanders:
            self.assertIn("第", label)

    def test_full_json_content_is_visible(self) -> None:
        rendered_code = [block.value for block in self.app.code]

        self.assertTrue(any("queried_student_id" in text for text in rendered_code))
        self.assertTrue(any("repair_basis" in text for text in rendered_code))
        self.assertTrue(any("evidence" in text for text in rendered_code))

    def test_success_case_shows_success_banner(self) -> None:
        self.assertEqual(len(self.app.success), 1)
        self.assertIn("成功", self.app.success[0].value)
        self.assertEqual(self.app.error, [])


if __name__ == "__main__":
    unittest.main()
