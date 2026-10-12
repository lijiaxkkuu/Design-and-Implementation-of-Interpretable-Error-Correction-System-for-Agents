"""agent_core 核心实验逻辑的单元测试（标准库 unittest）。

覆盖的实验要求：
    1. 存在的学号可以查询成功；
    2. 不存在的学号返回结构化错误；
    3. 目标学号 1002 的"失败—纠错—重试"完整流程；
    4. 轨迹保留两次工具调用；
    5. 诊断包含可核对的证据；
    6. 验证器接受真实且合格的结果；
    7. 验证器拒绝不合格结果；
    8. 不存在的目标学号不会被编造成成功。
"""

import json
import sys
import unittest
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import agent_core  # noqa: E402  （需先补充 sys.path）


class TestScoreTool(unittest.TestCase):
    """工具层：真实返回，不编造数据。"""

    def test_existing_student_query_succeeds(self) -> None:
        """存在学号 1002 时查询成功且结构完整。"""
        result = agent_core.query_student_score("1002")

        self.assertEqual(result["status"], agent_core.STATUS_SUCCESS)
        self.assertIsNone(result["error_code"])
        self.assertEqual(result["queried_student_id"], "1002")

        data = result["data"]
        for field in agent_core.DATA_FIELDS:
            self.assertIn(field, data)
        self.assertEqual(data["student_id"], "1002")
        self.assertIsInstance(data["score"], (int, float))
        self.assertGreaterEqual(float(data["score"]), agent_core.SCORE_MIN)
        self.assertLessEqual(float(data["score"]), agent_core.SCORE_MAX)

    def test_missing_student_returns_structured_error(self) -> None:
        """不存在学号 9999 时返回结构化错误，而不是异常或伪造数据。"""
        result = agent_core.query_student_score("9999")

        for key in ("status", "error_code", "message", "queried_student_id", "data"):
            self.assertIn(key, result)
        self.assertEqual(result["status"], agent_core.STATUS_ERROR)
        self.assertEqual(result["error_code"], agent_core.ERROR_STUDENT_NOT_FOUND)
        self.assertEqual(result["queried_student_id"], "9999")
        self.assertIsNone(result["data"])
        self.assertIn("不存在", result["message"])

    def test_invalid_format_returns_structured_error(self) -> None:
        """非数字学号同样返回结构化错误。"""
        result = agent_core.query_student_score("abc")

        self.assertEqual(result["status"], agent_core.STATUS_ERROR)
        self.assertEqual(result["error_code"], agent_core.ERROR_INVALID_STUDENT_ID)
        self.assertIsNone(result["data"])


class TestCorrectionFlow(unittest.TestCase):
    """流程层：默认目标 1002 的失败—纠错—重试—验证。"""

    def setUp(self) -> None:
        self.result = agent_core.run_experiment(agent_core.DEFAULT_TARGET_STUDENT_ID)

    def test_default_target_flow_succeeds(self) -> None:
        """目标 1002：首次调用失败，纠错重试后成功。"""
        calls = self.result.tool_calls()

        self.assertEqual(calls[0]["arguments"], {"student_id": agent_core.DELIBERATE_WRONG_STUDENT_ID})
        self.assertEqual(calls[0]["status"], agent_core.STATUS_ERROR)
        self.assertEqual(calls[0]["result"]["error_code"], agent_core.ERROR_STUDENT_NOT_FOUND)

        self.assertEqual(calls[-1]["arguments"], {"student_id": "1002"})
        self.assertEqual(calls[-1]["status"], agent_core.STATUS_SUCCESS)

        self.assertEqual(self.result.final_status, agent_core.FINAL_SUCCESS)
        self.assertEqual(self.result.final_status_text, "成功")
        self.assertTrue(self.result.verification["passed"])

    def test_trace_keeps_two_tool_calls(self) -> None:
        """轨迹中恰好保留两次工具调用，参数依次为 9999、1002。"""
        calls = self.result.tool_calls()

        self.assertEqual(len(calls), 2)
        self.assertEqual(
            [call["arguments"]["student_id"] for call in calls],
            [agent_core.DELIBERATE_WRONG_STUDENT_ID, "1002"],
        )
        self.assertTrue(all(call["tool"] == agent_core.TOOL_NAME for call in calls))
        # 每一步都记录了阶段、工具、参数、实际返回与状态
        for entry in self.result.trace:
            for key in ("step", "phase", "tool", "arguments", "result", "status"):
                self.assertIn(key, entry)

    def test_repaired_arguments_come_from_original_task(self) -> None:
        """修正后的参数等于原始任务的目标学号。"""
        self.assertEqual(
            self.result.repair["corrected_arguments"],
            {"student_id": self.result.raw_task["target_student_id"]},
        )
        self.assertEqual(
            self.result.repair["changed_fields"],
            [{"field": "student_id", "before": agent_core.DELIBERATE_WRONG_STUDENT_ID, "after": "1002"}],
        )

    def test_diagnosis_has_evidence(self) -> None:
        """诊断必须给出可核对的证据，且与实际参数、错误码一致。"""
        diagnosis = self.result.diagnosis

        self.assertTrue(diagnosis["error_found"])
        self.assertEqual(diagnosis["actual_arguments"], {"student_id": agent_core.DELIBERATE_WRONG_STUDENT_ID})
        self.assertEqual(diagnosis["expected_arguments"], {"student_id": "1002"})
        self.assertEqual(diagnosis["error_code"], agent_core.ERROR_STUDENT_NOT_FOUND)

        evidence = diagnosis["evidence"]
        self.assertGreaterEqual(len(evidence), 2)
        for item in evidence:
            self.assertIn("step", item)
            self.assertTrue(str(item["observation"]).strip())

        # 诊断发生在重试之前，因此证据链引用的是诊断时刻已发生的步骤：
        # 任务解析（第 1 步）与首次工具调用（第 2 步）。
        referenced_steps = {item["step"] for item in evidence}
        parse_step = self.result.trace[0]["step"]
        first_call_step = self.result.tool_calls()[0]["step"]
        self.assertIn(parse_step, referenced_steps, "证据链应引用任务解析步骤")
        self.assertIn(first_call_step, referenced_steps, "证据链应引用首次工具调用步骤")

        joined = " ".join(item["observation"] for item in evidence)
        self.assertIn(agent_core.ERROR_STUDENT_NOT_FOUND, joined)
        self.assertIn("9999", joined)

    def test_structured_result_contains_all_sections(self) -> None:
        """返回对象包含原始任务、轨迹、诊断、修正、重试、验证与最终状态。"""
        payload = self.result.to_dict()

        for key in (
            "raw_task",
            "trace",
            "diagnosis",
            "repair",
            "retry_result",
            "verification",
            "final_status",
            "final_status_text",
            "summary",
        ):
            self.assertIn(key, payload)

        self.assertIsInstance(payload["trace"], list)
        self.assertIsInstance(payload["retry_result"], dict)


class TestVerifier(unittest.TestCase):
    """验证层：只看真实返回值，合格才通过。"""

    def test_verifier_accepts_correct_result(self) -> None:
        """真实且合格的查询结果应通过验证。"""
        outcome = agent_core.verify_result(agent_core.query_student_score("1002"), "1002")

        self.assertTrue(outcome["passed"])
        self.assertTrue(all(check["passed"] for check in outcome["checks"]))

    def test_verifier_rejects_wrong_student_id(self) -> None:
        """学号不匹配时不通过。"""
        outcome = agent_core.verify_result(agent_core.query_student_score("1001"), "1002")

        self.assertFalse(outcome["passed"])
        failed = [check["name"] for check in outcome["checks"] if not check["passed"]]
        self.assertIn("学号与目标一致", failed)

    def test_verifier_rejects_missing_score_field(self) -> None:
        """缺少成绩字段时不通过。"""
        fake = {
            "status": agent_core.STATUS_SUCCESS,
            "error_code": None,
            "message": "查询成功",
            "queried_student_id": "1002",
            "data": {"student_id": "1002", "name": "李四", "course": "数据结构"},
        }
        outcome = agent_core.verify_result(fake, "1002")

        self.assertFalse(outcome["passed"])
        failed = [check["name"] for check in outcome["checks"] if not check["passed"]]
        self.assertIn("成绩数据结构完整", failed)

    def test_verifier_rejects_unreasonable_score(self) -> None:
        """成绩不是数值或超出合理范围时不通过。"""
        for bad_score in ("优秀", None, 120.0, -5.0, True):
            with self.subTest(bad_score=bad_score):
                fake = {
                    "status": agent_core.STATUS_SUCCESS,
                    "error_code": None,
                    "message": "查询成功",
                    "queried_student_id": "1002",
                    "data": {
                        "student_id": "1002",
                        "name": "李四",
                        "course": "数据结构",
                        "score": bad_score,
                    },
                }
                outcome = agent_core.verify_result(fake, "1002")
                self.assertFalse(outcome["passed"])

    def test_verifier_rejects_error_result(self) -> None:
        """工具返回错误时不通过，且不会被当成成功。"""
        outcome = agent_core.verify_result(agent_core.query_student_score("9999"), "1002")

        self.assertFalse(outcome["passed"])
        failed = [check["name"] for check in outcome["checks"] if not check["passed"]]
        self.assertIn("状态字段为成功", failed)

    def test_verifier_rejects_non_structured_result(self) -> None:
        """非结构化返回（例如字符串）直接判定不通过。"""
        outcome = agent_core.verify_result("查询成功", "1002")

        self.assertFalse(outcome["passed"])
        self.assertEqual(outcome["checks"][0]["name"], "返回结果为结构化对象")
        self.assertFalse(outcome["checks"][0]["passed"])


class TestFabricationGuard(unittest.TestCase):
    """防伪造：目标学号不存在时，系统必须判失败。"""

    def test_missing_target_is_not_reported_as_success(self) -> None:
        """输入 8888（不存在）时最终状态为失败，且重试结果是工具真实返回的错误。"""
        result = agent_core.run_experiment("8888")

        self.assertNotEqual(result.final_status, agent_core.FINAL_SUCCESS)
        self.assertEqual(result.final_status, agent_core.FINAL_FAILED)
        self.assertEqual(result.final_status_text, "失败")
        self.assertFalse(result.verification["passed"])

        self.assertIsNotNone(result.retry_result)
        self.assertEqual(result.retry_result["status"], agent_core.STATUS_ERROR)
        self.assertEqual(result.retry_result["error_code"], agent_core.ERROR_STUDENT_NOT_FOUND)
        self.assertIsNone(result.retry_result["data"])

        self.assertIn("失败", result.summary)

    def test_missing_target_still_keeps_full_trace(self) -> None:
        """失败分支同样保留两次工具调用与参数修正记录。"""
        result = agent_core.run_experiment("8888")
        calls = result.tool_calls()

        self.assertEqual(len(calls), 2)
        self.assertEqual(
            [call["arguments"]["student_id"] for call in calls],
            [agent_core.DELIBERATE_WRONG_STUDENT_ID, "8888"],
        )
        self.assertEqual(result.repair["corrected_arguments"], {"student_id": "8888"})

    def test_empty_target_is_invalid_input(self) -> None:
        """空输入时明确报告输入无效，不猜测查询目标。"""
        result = agent_core.run_experiment("   ")

        self.assertEqual(result.final_status, agent_core.FINAL_INVALID_INPUT)
        self.assertEqual(result.final_status_text, "输入无效")
        self.assertFalse(result.verification["passed"])
        self.assertEqual(result.tool_calls(), [])


class TestWrongStudentIdInjection(unittest.TestCase):
    """首次调用注入的错误学号必须始终不同于用户输入的目标学号。"""

    def test_choose_wrong_student_id_avoids_collision(self) -> None:
        """默认注入 9999；目标学号也是 9999 时自动改用备选学号。"""
        self.assertEqual(
            agent_core.choose_wrong_student_id("1002"),
            agent_core.DELIBERATE_WRONG_STUDENT_ID,
        )
        self.assertNotEqual(agent_core.choose_wrong_student_id("9999"), "9999")
        self.assertEqual(
            agent_core.choose_wrong_student_id("9999"),
            agent_core.FALLBACK_WRONG_STUDENT_IDS[0],
        )
        # 显式指定的错误学号与目标相同时，同样要被替换
        self.assertNotEqual(
            agent_core.choose_wrong_student_id("8888", requested_wrong_student_id="8888"),
            "8888",
        )

    def test_choose_wrong_student_id_never_uses_real_student(self) -> None:
        """挑出来的错误学号不能是成绩库里真实存在的学号。"""
        for target in ("1001", "1002", "9999", "8888", "0000", "7777"):
            with self.subTest(target=target):
                chosen = agent_core.choose_wrong_student_id(target)
                self.assertNotEqual(chosen, target)
                self.assertNotIn(chosen, agent_core.STUDENT_DB)

    def test_first_call_always_differs_from_target(self) -> None:
        """无论目标学号是什么，首次调用参数都与目标不同，重试回到目标学号。"""
        for target in ("1002", "1001", "9999", "8888", "1234"):
            with self.subTest(target=target):
                result = agent_core.run_experiment(target)
                calls = result.tool_calls()

                self.assertEqual(len(calls), 2)
                self.assertNotEqual(calls[0]["arguments"]["student_id"], target)
                self.assertEqual(calls[0]["status"], agent_core.STATUS_ERROR)
                self.assertEqual(
                    calls[0]["result"]["error_code"], agent_core.ERROR_STUDENT_NOT_FOUND
                )
                self.assertEqual(calls[-1]["arguments"]["student_id"], target)

    def test_target_9999_uses_fallback_and_marks_adjustment(self) -> None:
        """目标为 9999：首次使用 8888，重试使用 9999，因目标不存在最终失败。"""
        result = agent_core.run_experiment("9999")
        calls = result.tool_calls()

        self.assertEqual(calls[0]["arguments"], {"student_id": "8888"})
        self.assertEqual(calls[-1]["arguments"], {"student_id": "9999"})
        self.assertTrue(result.raw_task["wrong_student_id_adjusted"])
        self.assertEqual(result.raw_task["deliberate_wrong_student_id"], "8888")
        self.assertEqual(result.final_status, agent_core.FINAL_FAILED)
        self.assertFalse(result.verification["passed"])

    def test_explicit_wrong_id_equal_to_target_is_replaced(self) -> None:
        """调用方显式传入与目标相同的错误学号时，仍会被替换掉。"""
        result = agent_core.run_experiment("9999", wrong_student_id="9999")

        self.assertEqual(result.tool_calls()[0]["arguments"], {"student_id": "8888"})
        self.assertEqual(result.tool_calls()[-1]["arguments"], {"student_id": "9999"})


class TestDiagnosisConsistency(unittest.TestCase):
    """诊断文案必须依据真实轨迹与参数比较结果生成。"""

    def test_parameter_error_only_when_parameters_differ(self) -> None:
        """参数确实不一致时，才可以使用「与原始任务不一致」的表述。"""
        diagnosis = agent_core.run_experiment("1002").diagnosis

        self.assertTrue(diagnosis["parameter_mismatch"])
        self.assertTrue(diagnosis["target_exists_in_db"])
        self.assertEqual(diagnosis["failure_category"], "首次调用参数错误")
        self.assertIn("与原始任务不一致", diagnosis["cause"])
        self.assertIn("1002", diagnosis["cause"])
        self.assertIn(agent_core.DELIBERATE_WRONG_STUDENT_ID, diagnosis["cause"])

    def test_missing_target_is_distinguished_from_parameter_error(self) -> None:
        """目标学号不存在时，必须区分「参数写错」与「目标学号本身不存在」。"""
        diagnosis = agent_core.run_experiment("8888").diagnosis
        reference = agent_core.run_experiment("1002").diagnosis["cause"]

        self.assertTrue(diagnosis["parameter_mismatch"])
        self.assertFalse(diagnosis["target_exists_in_db"])
        self.assertIn("不一致", diagnosis["cause"])
        self.assertIn("本身也不在成绩库中", diagnosis["cause"])
        self.assertNotEqual(diagnosis["cause"], reference, "诊断文案不能是固定模板")
        self.assertEqual(
            diagnosis["failure_category"], "首次调用参数错误 + 目标学号本身不存在"
        )

    def test_identical_parameters_are_not_reported_as_parameter_error(self) -> None:
        """参数与目标一致却仍失败时，不能再归因于参数错误。"""
        tool_result = agent_core.query_student_score("9999")
        trace = [
            {
                "step": 1,
                "phase": agent_core.PHASE_PARSE,
                "action": "解析用户输入",
                "tool": "-",
                "arguments": {"raw_input": "9999"},
                "result": {"target_student_id": "9999"},
                "result_summary": "目标学号 = '9999'",
                "status": agent_core.STATUS_INFO,
            },
            {
                "step": 2,
                "phase": agent_core.PHASE_FIRST_CALL,
                "action": "第一次调用工具",
                "tool": agent_core.TOOL_NAME,
                "arguments": {"student_id": "9999"},
                "result": tool_result,
                "result_summary": tool_result["message"],
                "status": tool_result["status"],
            },
        ]

        diagnosis = agent_core.diagnose_trace("9999", "9999", tool_result, trace)

        self.assertTrue(diagnosis["error_found"])
        self.assertFalse(diagnosis["parameter_mismatch"])
        self.assertIn("不是参数错误", diagnosis["cause"])
        self.assertNotIn("与原始任务不一致", diagnosis["cause"])
        self.assertIn("不存在需要修正的参数", diagnosis["repair_basis"])
        self.assertEqual(
            diagnosis["failure_category"], "目标学号本身不存在（不是参数错误）"
        )

    def test_diagnosis_evidence_matches_actual_trace(self) -> None:
        """证据链引用真实步骤与真实参数，并给出参数比较结论。"""
        result = agent_core.run_experiment("9999")
        evidence = result.diagnosis["evidence"]
        joined = " ".join(item["observation"] for item in evidence)
        referenced = {item["step"] for item in evidence}

        self.assertIn(result.trace[0]["step"], referenced)
        self.assertIn(result.tool_calls()[0]["step"], referenced)
        self.assertIn("8888", joined)
        self.assertIn("9999", joined)
        self.assertIn("不一致", joined)
        self.assertIn("不存在学号", joined)


class TestRepairAndRetryStatements(unittest.TestCase):
    """修正记录与重试结论不得包含误导性表述。"""

    def test_repair_plan_marks_real_change(self) -> None:
        plan = agent_core.build_repair_plan("1002", "9999", "依据")

        self.assertTrue(plan["changed"])
        self.assertEqual(
            plan["changed_fields"],
            [{"field": "student_id", "before": "9999", "after": "1002"}],
        )
        self.assertIn("→", plan["correction_text"])

    def test_repair_plan_without_change_is_not_success_wording(self) -> None:
        """参数没有变化时不能显示成一次成功的修正。"""
        plan = agent_core.build_repair_plan("9999", "9999", "依据")

        self.assertFalse(plan["changed"])
        self.assertEqual(plan["changed_fields"], [])
        self.assertNotIn("→", plan["correction_text"])
        self.assertIn("未变更", plan["correction_text"])

    def test_run_experiment_records_actual_change_only(self) -> None:
        changed = agent_core.run_experiment("1002")
        self.assertTrue(changed.repair["changed"])
        self.assertEqual(changed.comparison["change_text"], "student_id：9999 → 1002")

        fallback = agent_core.run_experiment("9999")
        self.assertTrue(fallback.repair["changed"])
        self.assertEqual(fallback.repair["correction_text"], "student_id：8888 → 9999")

    def test_retry_always_targets_user_input_and_never_fabricates(self) -> None:
        for target in ("1002", "8888", "9999"):
            with self.subTest(target=target):
                result = agent_core.run_experiment(target)

                self.assertEqual(result.tool_calls()[-1]["arguments"], {"student_id": target})
                self.assertEqual(result.retry_analysis["requested_student_id"], target)

                if target in agent_core.STUDENT_DB:
                    continue
                # 目标学号不存在：两次调用都是工具真实返回的错误，且没有任何学生数据
                for call in result.tool_calls():
                    self.assertEqual(call["status"], agent_core.STATUS_ERROR)
                    self.assertEqual(
                        call["result"]["error_code"], agent_core.ERROR_STUDENT_NOT_FOUND
                    )
                    self.assertIsNone(call["result"]["data"])
                self.assertIsNone(result.retry_result["data"])
                self.assertEqual(result.final_status, agent_core.FINAL_FAILED)

    def test_retry_conclusion_explains_missing_target(self) -> None:
        result = agent_core.run_experiment("8888")
        conclusion = result.retry_analysis["conclusion"]

        self.assertIn("8888", conclusion)
        self.assertIn("不是调用参数", conclusion)
        self.assertFalse(result.retry_analysis["target_exists_in_db"])

    def test_success_case_retry_conclusion_points_to_target(self) -> None:
        result = agent_core.run_experiment("1003")
        conclusion = result.retry_analysis["conclusion"]

        self.assertIn("1003", conclusion)
        self.assertTrue(result.retry_analysis["target_exists_in_db"])
        self.assertTrue(result.verification["passed"])


class TestElapsedConversion(unittest.TestCase):
    """耗时展示：单位换算正确，且不为了让数值好看而改动测量结果。"""

    def test_milliseconds_are_converted_from_seconds(self) -> None:
        info = agent_core.describe_elapsed(0.00019)

        self.assertAlmostEqual(info["seconds"], 0.00019, places=9)
        self.assertAlmostEqual(info["milliseconds"], 0.19, places=9)
        # 展示文本是定点小数，不会出现 1.9e-04 这类科学计数法
        self.assertEqual(info["milliseconds_text"], "0.190")
        self.assertEqual(info["seconds_text"], "0.000190")
        self.assertNotIn("e", info["text"])
        self.assertIn("毫秒", info["text"])
        self.assertIn("秒", info["text"])

    def test_unit_conversion_holds_for_larger_values(self) -> None:
        self.assertEqual(agent_core.describe_elapsed(1.5)["milliseconds"], 1500.0)
        self.assertEqual(agent_core.describe_elapsed(1.5)["seconds"], 1.5)
        self.assertEqual(agent_core.describe_elapsed(0.25)["milliseconds"], 250.0)

    def test_very_short_duration_keeps_extra_decimals(self) -> None:
        """耗时极短时保留更多小数位，而不是把数值放大到看起来合理。"""
        info = agent_core.describe_elapsed(0.0000123)

        self.assertGreater(info["milliseconds"], 0)
        self.assertAlmostEqual(info["milliseconds"], 0.012, places=3)
        self.assertLess(info["milliseconds"], 0.02)
        self.assertEqual(info["milliseconds_text"], "0.012")
        self.assertEqual(info["seconds_text"], "0.000012")


class TestInvalidStudentIdDiagnosis(unittest.TestCase):
    """INVALID_STUDENT_ID 必须解释为「输入格式/类型非法」，不能当成「学生不存在」。"""

    @staticmethod
    def _trace(target: str, used: str, tool_result: dict[str, Any]) -> list[dict[str, Any]]:
        """构造「任务解析 + 首次工具调用」两步最小轨迹。"""
        return [
            {
                "step": 1,
                "phase": agent_core.PHASE_PARSE,
                "action": "解析用户输入，确定本次实验的目标学号",
                "tool": "-",
                "arguments": {"raw_input": target},
                "result": {"target_student_id": target},
                "result_summary": f"目标学号 = {target!r}",
                "status": agent_core.STATUS_INFO,
            },
            {
                "step": 2,
                "phase": agent_core.PHASE_FIRST_CALL,
                "action": f"第一次调用工具，故意使用错误学号 {used}",
                "tool": agent_core.TOOL_NAME,
                "arguments": {"student_id": used},
                "result": tool_result,
                "result_summary": tool_result["message"],
                "status": tool_result["status"],
            },
        ]

    def test_invalid_format_is_not_reported_as_missing_student(self) -> None:
        """错误码为 INVALID_STUDENT_ID 时，不得说成「学生不存在」或「不在成绩库中」。"""
        tool_result = agent_core.query_student_score("abc")
        trace = self._trace("1002", "abc", tool_result)

        diagnosis = agent_core.diagnose_trace("1002", "abc", tool_result, trace)

        self.assertTrue(diagnosis["error_found"])
        self.assertEqual(diagnosis["error_code"], agent_core.ERROR_INVALID_STUDENT_ID)
        self.assertEqual(diagnosis["failure_category"], "首次调用参数格式/类型错误")
        self.assertNotIn("学生不存在", diagnosis["cause"])
        self.assertNotIn("不在成绩库中", diagnosis["cause"])
        self.assertIn("不是合法的纯数字学号", diagnosis["cause"])
        self.assertIn(agent_core.ERROR_INVALID_STUDENT_ID, diagnosis["cause"])
        self.assertIn("abc", diagnosis["cause"])
        # 目标学号 1002 本身是合法且登记在库的，出问题的是首次调用的参数
        self.assertEqual(diagnosis["target_status_text"], "是（该学号登记在成绩库中）")

    def test_invalid_target_format_is_not_reported_as_missing_student(self) -> None:
        """目标学号本身就是非法格式时，同样不能说成「目标学号不存在」。"""
        tool_result = agent_core.query_student_score("abc")
        trace = self._trace("abc", "abc", tool_result)

        diagnosis = agent_core.diagnose_trace("abc", "abc", tool_result, trace)

        self.assertEqual(diagnosis["failure_category"], "目标学号格式非法（不是参数错误）")
        self.assertIn("不是参数错误", diagnosis["cause"])
        self.assertIn("不是合法的纯数字学号", diagnosis["cause"])
        self.assertNotIn("不在成绩库中", diagnosis["cause"])
        self.assertIn("不存在需要修正的参数", diagnosis["repair_basis"])
        self.assertIn("不会替用户改写学号", diagnosis["repair_basis"])
        self.assertEqual(
            diagnosis["target_status_text"],
            "否（该输入不是合法的纯数字学号，无法定位到任何学生）",
        )

    def test_run_experiment_with_invalid_target_fails_without_fabrication(self) -> None:
        """run_experiment("abc")：最终失败，且全程没有任何编造的学生数据。"""
        result = agent_core.run_experiment("abc")

        self.assertEqual(result.final_status, agent_core.FINAL_FAILED)
        self.assertEqual(result.final_status_text, "失败")
        self.assertFalse(result.verification["passed"])

        self.assertIsNotNone(result.retry_result)
        self.assertEqual(result.retry_result["error_code"], agent_core.ERROR_INVALID_STUDENT_ID)
        self.assertIsNone(result.retry_result["data"])
        for call in result.tool_calls():
            self.assertIsNone(call["result"]["data"])

        payload = json.dumps(result.to_dict(), ensure_ascii=False)
        for name in ("张三", "李四", "王五", "赵六", "孙七"):
            self.assertNotIn(name, payload)
        for score in ("85.0", "92.5", "78.0", "63.5", "96.0"):
            self.assertNotIn(score, payload)

    def test_invalid_target_messages_are_consistent(self) -> None:
        """诊断、重试分析与最终状态必须给出同一个归因（输入格式非法）。"""
        result = agent_core.run_experiment("abc")

        self.assertEqual(result.diagnosis["failure_category"], "首次调用参数错误 + 目标学号格式非法")
        self.assertEqual(result.retry_analysis["error_code"], agent_core.ERROR_INVALID_STUDENT_ID)
        self.assertEqual(result.retry_analysis["status"], agent_core.STATUS_ERROR)

        texts = {
            "诊断原因": result.diagnosis["cause"],
            "诊断结论": result.diagnosis["conclusion"],
            "修正依据": result.diagnosis["repair_basis"],
            "重试结论": result.retry_analysis["conclusion"],
            "归因句": result.retry_analysis["attribution"],
            "最终状态": result.summary,
        }
        for label, text in texts.items():
            with self.subTest(label=label):
                self.assertIn("不是合法的纯数字学号", text)
                self.assertNotIn("属于「目标学号不存在」", text)
                self.assertNotIn("该学号本身不在成绩库中", text)

    def test_missing_student_wording_is_preserved(self) -> None:
        """回归保护：STUDENT_NOT_FOUND 仍解释为「目标学号不存在」。"""
        result = agent_core.run_experiment("8888")

        self.assertEqual(result.retry_analysis["error_code"], agent_core.ERROR_STUDENT_NOT_FOUND)
        self.assertEqual(
            result.diagnosis["failure_category"], "首次调用参数错误 + 目标学号本身不存在"
        )
        self.assertIn("本身也不在成绩库中", result.diagnosis["cause"])
        self.assertIn("属于「目标学号不存在」", result.summary)
        self.assertNotIn("不是合法的纯数字学号", result.summary)

    def test_valid_target_wording_is_unchanged(self) -> None:
        """回归保护：合法学号仍然按「首次调用参数错误」解释并纠错成功。"""
        result = agent_core.run_experiment("1002")

        self.assertEqual(result.final_status, agent_core.FINAL_SUCCESS)
        self.assertEqual(result.diagnosis["failure_category"], "首次调用参数错误")
        self.assertIn("与原始任务不一致", result.diagnosis["cause"])
        self.assertIn("问题出在调用参数", result.diagnosis["cause"])
        self.assertNotIn("不是合法的纯数字学号", result.diagnosis["cause"])
        self.assertIn("目标学号 1002 的成绩查询在纠错后通过独立验证", result.summary)


if __name__ == "__main__":
    unittest.main()
