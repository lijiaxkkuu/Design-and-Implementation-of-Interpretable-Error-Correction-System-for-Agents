"""执行轨迹的展示模型（不依赖 Streamlit，可被单元测试直接检查）。

界面层（app.py）只负责把这里生成的数据渲染出来。把「展示数据」和「渲染」分开，
是为了让「轨迹能否看到完整返回内容」这件事本身可以被测试覆盖：

    - trace_table_rows() 只放短文本摘要，避免长 JSON 在表格里被截断；
    - trace_step_details() 给出每一步的完整参数与完整返回 JSON（indent=2），
      界面用逐步骤展开区渲染，内容与轨迹中的对象完全一致。
"""

from __future__ import annotations

import json
from typing import Any

# 状态 -> 中文展示文本（表格、对比区共用同一份映射）
STATUS_TEXT = {"success": "成功", "error": "错误", "info": "信息"}

# 步骤没有返回内容时的占位摘要
EMPTY_SUMMARY = "（该步骤没有返回内容）"


def status_text(status: Any) -> str:
    """把状态码渲染成中文标签，未知状态原样返回。"""
    return STATUS_TEXT.get(status, str(status))


def result_summary(entry: dict[str, Any]) -> str:
    """取一步轨迹的短摘要：优先用轨迹里记录的 result_summary，其次用 message。"""
    summary = str(entry.get("result_summary") or "").strip()
    if summary:
        return summary
    result = entry.get("result")
    if isinstance(result, dict) and result.get("message"):
        return str(result["message"])
    return EMPTY_SUMMARY


def trace_table_rows(trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """构造执行轨迹表格的行（只含短文本，长 JSON 不放表格）。"""
    return [
        {
            "步骤": entry.get("step"),
            "阶段": entry.get("phase"),
            "动作": entry.get("action"),
            "工具": entry.get("tool"),
            "参数": json.dumps(entry.get("arguments"), ensure_ascii=False),
            "返回摘要": result_summary(entry),
            "状态": status_text(entry.get("status")),
        }
        for entry in trace
    ]


def trace_step_details(trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """构造逐步骤详情，提供完整、未被截断的参数与实际返回 JSON。"""
    details: list[dict[str, Any]] = []
    for entry in trace:
        step = entry.get("step")
        phase = entry.get("phase")
        details.append(
            {
                "step": step,
                "phase": phase,
                "action": entry.get("action"),
                "tool": entry.get("tool"),
                "status_text": status_text(entry.get("status")),
                "summary": result_summary(entry),
                "arguments_json": json.dumps(entry.get("arguments"), ensure_ascii=False, indent=2),
                "result_json": json.dumps(entry.get("result"), ensure_ascii=False, indent=2),
                "title": f"第 {step} 步 · {phase} · 状态：{status_text(entry.get('status'))} · 查看完整参数与返回",
            }
        )
    return details
