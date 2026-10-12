"""《面向智能体的可解释纠错系统设计与实现》Streamlit 界面（阶段 1）。

界面只负责展示，实验逻辑全部来自 agent_core，二者互不依赖。
每次点击"运行实验"都会重新执行一次真实的实验流程。
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st

APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import agent_core  # noqa: E402  （需先补充 sys.path）
import trace_view  # noqa: E402  （展示模型，同样需要先补充 sys.path）

# 状态标签统一由展示模型提供，避免表格与对比区出现两套口径
STATUS_TEXT = trace_view.STATUS_TEXT


def _plain(value: Any) -> str:
    """把任意值渲染成便于阅读的一行文本。"""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _render_trace(trace: list[dict[str, Any]]) -> None:
    st.subheader("① 执行轨迹")
    tool_calls = [entry for entry in trace if entry["tool"] == agent_core.TOOL_NAME]
    st.caption(
        f"共记录 {len(trace)} 个步骤，其中工具调用 {len(tool_calls)} 次"
        f"（工具名：{agent_core.TOOL_NAME}）"
    )
    st.dataframe(trace_view.trace_table_rows(trace), hide_index=True)
    st.caption(
        "表格只展示短摘要；每一步的完整参数与实际返回结果见下方展开区，"
        "展开后的 JSON 与轨迹中记录的内容完全一致。"
    )
    for detail in trace_view.trace_step_details(trace):
        with st.expander(detail["title"]):
            st.markdown(f"**动作**：{detail['action']}")
            st.markdown(f"**工具**：`{detail['tool']}`　**状态**：{detail['status_text']}")
            st.markdown(f"**返回摘要**：{detail['summary']}")
            st.markdown("**参数（完整 JSON）**")
            st.code(detail["arguments_json"], language="json")
            st.markdown("**实际返回结果（完整 JSON）**")
            st.code(detail["result_json"], language="json")


def _render_diagnosis(diagnosis: dict[str, Any]) -> None:
    st.subheader("② 证据化错误诊断")

    if not diagnosis.get("error_found"):
        st.info(f"未发现需要纠正的错误：{diagnosis.get('conclusion')}")
    else:
        st.markdown(f"**失败类别**：{diagnosis.get('failure_category') or '未分类'}")
        st.markdown(f"**错误位置**：{diagnosis['error_location']}")
        st.markdown(f"**实际参数**：`{_plain(diagnosis['actual_arguments'])}`")
        st.markdown(f"**期望参数**：`{_plain(diagnosis['expected_arguments'])}`")
        st.markdown(f"**工具真实返回**：`{_plain(diagnosis['tool_response'])}`")
        st.markdown(f"**错误码**：`{diagnosis['error_code']}`")
        if diagnosis.get("parameter_mismatch") is not None:
            mismatch_text = (
                "否（首次调用参数与目标学号不一致，属于参数错误）"
                if diagnosis["parameter_mismatch"]
                else "是（首次调用参数与目标学号一致，本次不是参数错误）"
            )
            st.markdown(f"**首次调用参数是否与目标学号一致**：{mismatch_text}")
            # 目标学号的状态由诊断结果给出：格式非法与「不在成绩库中」必须区别显示
            st.markdown(
                "**目标学号是否登记在成绩库中**："
                + (
                    diagnosis.get("target_status_text")
                    or (
                        "是（该学号登记在成绩库中）"
                        if diagnosis.get("target_exists_in_db")
                        else "否（该学号不在成绩库中）"
                    )
                )
            )
        st.markdown(f"**原因分析**：{diagnosis['cause']}")
        st.markdown(f"**修正依据**：{diagnosis['repair_basis']}")

    st.markdown("**证据链**")
    evidence = diagnosis.get("evidence", [])
    if not evidence:
        st.markdown("- 无")
    for item in evidence:
        st.markdown(f"- 第 {item['step']} 步：{item['observation']}")


def _result_message(result: Any) -> str:
    """取返回结果的简短说明，完整 JSON 放在展开区展示。"""
    if isinstance(result, dict):
        return str(result.get("message") or "（该返回没有 message 字段）")
    return _plain(result)


def _render_comparison(
    comparison: dict[str, Any],
    repair: dict[str, Any],
    retry_analysis: dict[str, Any],
) -> None:
    st.subheader("③ 纠错前后对比")

    before = comparison.get("before")
    after = comparison.get("after")
    left, right = st.columns(2)

    with left:
        st.markdown("**纠错前（首次调用）**")
        if before:
            st.markdown(f"- 参数：`{_plain(before['arguments'])}`")
            st.markdown(f"- 状态：{STATUS_TEXT.get(before['status'], before['status'])}")
            st.markdown(f"- 返回摘要：{_result_message(before['result'])}")
            with st.expander("查看完整返回 JSON"):
                st.code(json.dumps(before["result"], ensure_ascii=False, indent=2), language="json")
        else:
            st.markdown("- 无记录")

    with right:
        st.markdown("**纠错后（重试调用）**")
        if after:
            st.markdown(f"- 参数：`{_plain(after['arguments'])}`")
            st.markdown(f"- 状态：{STATUS_TEXT.get(after['status'], after['status'])}")
            st.markdown(f"- 返回摘要：{_result_message(after['result'])}")
            with st.expander("查看完整返回 JSON"):
                st.code(json.dumps(after["result"], ensure_ascii=False, indent=2), language="json")
        else:
            st.markdown("- 未发生重试")

    if comparison.get("changed"):
        st.markdown(f"**参数变更**：{comparison['change_text']}")
    else:
        st.markdown("**参数变更**：无（首次调用参数已与目标学号一致，没有可修正的参数）")

    if repair.get("changed_fields"):
        st.markdown("**修正记录**")
        st.dataframe(
            [
                {"字段": item["field"], "修正前": item["before"], "修正后": item["after"]}
                for item in repair["changed_fields"]
            ],
            hide_index=True,
        )
    else:
        st.markdown("**修正记录**：无（未发生参数变更）")

    if retry_analysis.get("conclusion"):
        st.markdown(f"**重试结论**：{retry_analysis['conclusion']}")

    st.markdown(f"**修正依据**：{repair.get('basis', '无')}")


def _render_verification(verification: dict[str, Any]) -> None:
    st.subheader("④ 独立验证清单")
    checks = verification.get("checks", [])
    if not checks:
        st.warning(verification.get("verdict", "没有可展示的验证项。"))
        return

    st.caption(f"验证对象：学号 {verification.get('expected_student_id')!r} 的查询结果（直接检查工具真实返回值）")
    for check in checks:
        mark = "✅" if check["passed"] else "❌"
        st.markdown(f"{mark} **{check['name']}** —— {check['detail']}")

    passed_count = sum(1 for check in checks if check["passed"])
    st.markdown(f"**验证结论**：{verification['verdict']}（{passed_count}/{len(checks)} 项通过）")


def _render_final(result: agent_core.ExperimentResult) -> None:
    st.subheader("⑤ 最终状态")
    if result.final_status == agent_core.FINAL_SUCCESS:
        st.success(f"最终状态：{result.final_status_text} —— {result.summary}")
    elif result.final_status == agent_core.FINAL_INVALID_INPUT:
        st.warning(f"最终状态：{result.final_status_text} —— {result.summary}")
    else:
        st.error(f"最终状态：{result.final_status_text} —— {result.summary}")


def main() -> None:
    st.set_page_config(page_title="面向智能体的可解释纠错系统", layout="wide")

    st.title("面向智能体的可解释纠错系统设计与实现")
    st.caption(
        "阶段 1 实验：虚构学生成绩查询 —— 首次调用使用错误学号 → 依据轨迹证据诊断 → "
        "修正参数重试 → 独立验证结果"
    )

    with st.sidebar:
        st.header("实验说明")
        fallback_ids = "、".join(agent_core.FALLBACK_WRONG_STUDENT_IDS)
        st.markdown(
            f"- 数据源：虚构成绩库，仅包含学号 {', '.join(sorted(agent_core.STUDENT_DB))}\n"
            f"- 首次调用注入错误学号：默认 `{agent_core.DELIBERATE_WRONG_STUDENT_ID}`；"
            f"若它与目标学号相同，则自动改用备选学号（{fallback_ids}），"
            "保证首次调用参数一定不同于目标学号\n"
            "- 纠错后按用户输入的原始目标学号重试，不会用其他学生的成绩充当结果\n"
            "- 独立验证器直接检查工具真实返回结果\n"
            "- 目标学号不存在时，最终状态会是「失败」，不会伪造成功"
        )
        st.divider()
        st.markdown("启动命令：")
        st.code(r"D:\AgentThesis\.venv\Scripts\python12.exe -m streamlit run app.py", language="powershell")

    col_input, col_button = st.columns([3, 1])
    with col_input:
        target = st.text_input(
            "目标学号",
            value=agent_core.DEFAULT_TARGET_STUDENT_ID,
            help="虚构成绩库中可用的学号：1001、1002、1003、1004、1005；输入其他学号会走到失败分支。",
        )
    with col_button:
        st.write("")
        st.write("")
        run_clicked = st.button("运行实验", type="primary")

    if run_clicked:
        # 计时范围：只统计实验逻辑本身（不含页面渲染），单位换算统一交给 agent_core
        started = time.perf_counter()
        result = agent_core.run_experiment(target)
        elapsed = time.perf_counter() - started
        duration = agent_core.describe_elapsed(elapsed)
        st.session_state["result"] = result
        st.session_state["run_info"] = {
            "输入学号": target,
            "运行时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "耗时（毫秒）": duration["milliseconds_text"],
            "耗时（秒）": duration["seconds_text"],
        }

    result = st.session_state.get("result")
    if result is None:
        st.info("请输入目标学号后点击「运行实验」。每次点击都会重新执行一次真实实验。")
        return

    run_info = st.session_state.get("run_info", {})
    st.caption(
        "本次运行："
        + "　".join(f"{key}={value}" for key, value in run_info.items())
    )
    st.caption(
        "耗时只统计实验逻辑本身（agent_core.run_experiment，纯本地计算），不含页面渲染；"
        "数值很小属于正常现象，因此毫秒保留 3 位小数、秒保留 6 位小数。"
    )
    st.markdown(
        f"**原始任务**：查询学号 `{result.raw_task['target_student_id']}` 的期末成绩"
        f"（用户输入 `{result.raw_task['user_input']}`，工具 `{result.raw_task['tool']}`）"
    )
    st.divider()

    _render_trace(result.trace)
    st.divider()
    _render_diagnosis(result.diagnosis)
    st.divider()
    _render_comparison(result.comparison, result.repair, result.retry_analysis)
    st.divider()
    _render_verification(result.verification)
    st.divider()
    _render_final(result)

    with st.expander("完整结构化返回（JSON）"):
        st.json(result.to_dict())


if __name__ == "__main__":
    main()
