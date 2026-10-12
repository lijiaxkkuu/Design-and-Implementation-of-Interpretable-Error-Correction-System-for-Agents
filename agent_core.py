"""《面向智能体的可解释纠错系统设计与实现》核心实验逻辑。

本模块与 Streamlit 完全解耦，只依赖 Python 标准库，可被命令行、单元测试
或 Web 层调用。

阶段 1 的实验流程：
    1. 解析用户给出的目标学号（默认 1002）；
    2. 第一次工具调用故意注入一个错误学号（默认 9999，且一定不同于目标学号），
       工具真实返回结构化错误；
    3. 诊断器基于轨迹证据说明错误位置、实际参数、错误返回与修正依据；
    4. 纠错器按原始目标学号修正参数并重试；
    5. 独立验证器直接检查重试结果，验证不通过即判定失败，绝不伪造成功。

所有学生与成绩数据均为虚构，仅用于实验演示。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# 实验常量
# ---------------------------------------------------------------------------

PROJECT_NAME = "面向智能体的可解释纠错系统设计与实现"

DEFAULT_TARGET_STUDENT_ID = "1002"
DELIBERATE_WRONG_STUDENT_ID = "9999"
# 备选错误学号：当首选错误学号与用户输入的目标学号相同时，按顺序挑选第一个
# 满足「不同于目标学号且不在成绩库中」的学号。注入的错误学号必须始终不同于
# 目标学号，否则「首次调用参数错误」这一实验前提就不成立。
FALLBACK_WRONG_STUDENT_IDS = ("8888", "7777", "6666", "0000")

SCORE_MIN = 0.0
SCORE_MAX = 100.0

# 通用状态码
STATUS_SUCCESS = "success"
STATUS_ERROR = "error"
STATUS_INFO = "info"

# 轨迹阶段名称
PHASE_PARSE = "任务解析"
PHASE_FIRST_CALL = "首次工具调用"
PHASE_DIAGNOSIS = "错误诊断"
PHASE_REPAIR = "参数修正"
PHASE_RETRY = "纠错重试"
PHASE_VERIFY = "独立验证"

# 最终状态
FINAL_SUCCESS = "success"
FINAL_FAILED = "failed"
FINAL_INVALID_INPUT = "invalid_input"

FINAL_STATUS_TEXT = {
    FINAL_SUCCESS: "成功",
    FINAL_FAILED: "失败",
    FINAL_INVALID_INPUT: "输入无效",
}

# 工具名与错误码
TOOL_NAME = "query_student_score"
ERROR_STUDENT_NOT_FOUND = "STUDENT_NOT_FOUND"
ERROR_INVALID_STUDENT_ID = "INVALID_STUDENT_ID"

# 虚构成绩库（学号 -> 记录），仅用于实验
STUDENT_DB: dict[str, dict[str, Any]] = {
    "1001": {"name": "张三", "course": "数据结构", "score": 85.0},
    "1002": {"name": "李四", "course": "数据结构", "score": 92.5},
    "1003": {"name": "王五", "course": "数据结构", "score": 78.0},
    "1004": {"name": "赵六", "course": "数据结构", "score": 63.5},
    "1005": {"name": "孙七", "course": "数据结构", "score": 96.0},
}

DATA_FIELDS = ("student_id", "name", "course", "score")


# ---------------------------------------------------------------------------
# 错误注入策略：首次调用使用的错误学号
# ---------------------------------------------------------------------------


def choose_wrong_student_id(
    target_student_id: Any,
    requested_wrong_student_id: Any = None,
) -> str:
    """为首次工具调用挑选一个「一定不同于目标学号」的错误学号。

    选号规则（按顺序尝试）：
        1. 调用方显式指定的错误学号；
        2. DELIBERATE_WRONG_STUDENT_ID；
        3. FALLBACK_WRONG_STUDENT_IDS 中第一个可用学号。

    候选学号必须同时满足两个条件才会被采用：
        (a) 不等于目标学号 —— 否则首次调用就不存在参数错误，诊断会与事实不符；
        (b) 不在成绩库中 —— 保证首次调用真实地失败，且失败原因只是「学号不存在」。

    如果以上候选都不可用，则在数字空间里兜底生成一个满足条件的学号。
    """
    target = "" if target_student_id is None else str(target_student_id).strip()

    candidates: list[str] = []
    if requested_wrong_student_id is not None and str(requested_wrong_student_id).strip():
        candidates.append(str(requested_wrong_student_id).strip())
    candidates.append(DELIBERATE_WRONG_STUDENT_ID)
    candidates.extend(FALLBACK_WRONG_STUDENT_IDS)

    for candidate in candidates:
        if candidate != target and candidate not in STUDENT_DB:
            return candidate

    probe = 9000
    while str(probe) == target or str(probe) in STUDENT_DB:
        probe += 1
    return str(probe)


# ---------------------------------------------------------------------------
# 工具层：真实的成绩查询（返回结构化结果，不抛异常）
# ---------------------------------------------------------------------------


def query_student_score(student_id: Any) -> dict[str, Any]:
    """模拟成绩查询工具。

    该函数是系统中"与外部世界交互"的唯一入口，它只会返回真实查询结果：
    查得到就是 ``status="success"``，查不到或参数非法就是 ``status="error"``，
    不会为了配合上层流程而编造数据。

    返回结构统一为::

        {"status": ..., "error_code": ..., "message": ...,
         "queried_student_id": ..., "data": {...} 或 None}
    """
    text = "" if student_id is None else str(student_id).strip()

    if not text.isdigit():
        return {
            "status": STATUS_ERROR,
            "error_code": ERROR_INVALID_STUDENT_ID,
            "message": f"学号格式非法：{text!r} 不是纯数字学号",
            "queried_student_id": text,
            "data": None,
        }

    record = STUDENT_DB.get(text)
    if record is None:
        return {
            "status": STATUS_ERROR,
            "error_code": ERROR_STUDENT_NOT_FOUND,
            "message": f"学生不存在：学号 {text} 不在成绩库中",
            "queried_student_id": text,
            "data": None,
        }

    return {
        "status": STATUS_SUCCESS,
        "error_code": None,
        "message": "查询成功",
        "queried_student_id": text,
        "data": {
            "student_id": text,
            "name": record["name"],
            "course": record["course"],
            "score": record["score"],
        },
    }


# ---------------------------------------------------------------------------
# 诊断层：只依据轨迹中的真实证据说明问题
# ---------------------------------------------------------------------------


def _tool_failure_clause(
    error_code: Any,
    student_id: str,
    queried: Any,
    message: Any = None,
) -> str:
    """按工具真实返回的错误码解释这次调用为什么失败（不超出证据范围）。

    只有 STUDENT_NOT_FOUND 才能解释为「该学号不在成绩库中」；
    INVALID_STUDENT_ID 说明工具连查询都没有执行，不能据此认定学生是否存在；
    其它错误码只能给出通用描述，不能推断原因。
    """
    if error_code == ERROR_STUDENT_NOT_FOUND:
        return (
            f"工具真实返回 error_code={ERROR_STUDENT_NOT_FOUND!r}、queried_student_id={queried!r}，"
            f"说明 {student_id} 不在成绩库中，因此工具返回“学生不存在”"
        )
    if error_code == ERROR_INVALID_STUDENT_ID:
        return (
            f"工具真实返回 error_code={ERROR_INVALID_STUDENT_ID!r}、queried_student_id={queried!r}，"
            f"说明学号 {student_id} 不是合法的纯数字学号（格式或类型不符合要求），"
            "工具没有执行查询，不能据此认定学生是否存在"
        )
    return (
        f"工具真实返回 error_code={error_code!r}、message={message!r}、queried_student_id={queried!r}，"
        "该错误码不在本次实验已定义的范围内，只能确认这次调用失败，无法推断学生是否存在"
    )


def _target_status_predicate(
    target_student_id: str,
    target_exists: bool,
    available_ids: str,
) -> str:
    """描述目标学号的状态，用于「目标学号本身…… 」这样的句式。"""
    if target_exists:
        return "登记在成绩库中"
    if not target_student_id.isdigit():
        return "不是合法的纯数字学号（格式或类型不符合要求）"
    return f"不在成绩库中（当前仅包含 {available_ids}）"


def _target_status_text(target_student_id: str, target_exists: bool) -> str:
    """目标学号的登记状态（供界面显示，避免把「格式非法」显示成「不存在」）。"""
    if target_exists:
        return "是（该学号登记在成绩库中）"
    if not target_student_id.isdigit():
        return "否（该输入不是合法的纯数字学号，无法定位到任何学生）"
    return "否（该学号不在成绩库中）"


def diagnose_trace(
    target_student_id: str,
    used_student_id: str,
    tool_result: dict[str, Any],
    trace: list[dict[str, Any]],
) -> dict[str, Any]:
    """根据调用轨迹诊断首次调用失败的原因。

    诊断只依据两类可核对的事实生成：
        1. 轨迹中真实发生的步骤（原始任务、每次工具调用的实际参数与真实返回）；
        2. 原始目标学号与首次调用参数的实际比较结果，以及目标学号是否登记在成绩库中。

    因此「首次调用参数错误」与「目标学号本身不存在」会被明确区分开，
    不会无条件套用同一段文案。
    """
    call_steps = [entry for entry in trace if entry["tool"] == TOOL_NAME]
    parse_step = trace[0] if trace else {"step": 0}

    target = "" if target_student_id is None else str(target_student_id).strip()
    used = "" if used_student_id is None else str(used_student_id).strip()

    # 参数比较结果与数据源事实：这两项决定诊断文案走哪个分支
    parameter_mismatch = used != target
    target_exists = target in STUDENT_DB
    available_ids = "、".join(sorted(STUDENT_DB))

    evidence: list[dict[str, Any]] = [
        {
            "step": parse_step.get("step", 0),
            "observation": (
                f"原始任务要求查询的学号为 {target}；"
                f"该学号来自用户输入 {parse_step.get('arguments', {}).get('raw_input')!r}"
            ),
        }
    ]
    for entry in call_steps:
        result = entry["result"]
        evidence.append(
            {
                "step": entry["step"],
                "observation": (
                    f"调用工具 {entry['tool']}，参数 student_id={entry['arguments'].get('student_id')!r}，"
                    f"工具真实返回 status={result.get('status')!r}、"
                    f"error_code={result.get('error_code')!r}、message={result.get('message')!r}"
                ),
            }
        )

    evidence.append(
        {
            "step": parse_step.get("step", 0),
            "observation": (
                f"参数比较：原始任务的目标学号为 {target!r}，首次调用实际使用 {used!r}，"
                f"两者{'不一致' if parameter_mismatch else '一致'}；"
                f"成绩库中{'存在' if target_exists else '不存在'}学号 {target!r}"
                f"（成绩库当前仅包含 {available_ids}）"
            ),
        }
    )

    if tool_result.get("status") == STATUS_SUCCESS:
        return {
            "error_found": False,
            "error_location": None,
            "actual_arguments": {"student_id": used},
            "expected_arguments": {"student_id": target},
            "error_code": None,
            "tool_message": tool_result.get("message"),
            "tool_response": tool_result,
            "parameter_mismatch": parameter_mismatch,
            "target_exists_in_db": target_exists,
            "target_status_text": _target_status_text(target, target_exists),
            "failure_category": None,
            "cause": "首次工具调用即返回成功，未发现参数错误。",
            "conclusion": "未发现需要纠正的错误，无需参数修正。",
            "repair_basis": (
                f"首次调用使用的学号 {used!r} 与原始任务的目标学号 {target!r} 一致，"
                "查询已经成功，无需修正。"
            ),
            "evidence": evidence,
        }

    error_code = tool_result.get("error_code")
    call_step = call_steps[0]["step"] if call_steps else parse_step.get("step", 0)
    queried = tool_result.get("queried_student_id")

    # 失败原因只能按工具真实返回的错误码来解释，不能一律说成「学号不存在」
    failure_clause = _tool_failure_clause(error_code, used, queried, tool_result.get("message"))
    target_predicate = _target_status_predicate(target, target_exists, available_ids)
    target_status_text = _target_status_text(target, target_exists)
    parameter_issue = (
        "首次调用参数格式/类型错误"
        if error_code == ERROR_INVALID_STUDENT_ID
        else "首次调用参数错误"
    )
    target_issue = None if target_exists else (
        "目标学号格式非法" if not target.isdigit() else "目标学号本身不存在"
    )

    if parameter_mismatch and target_exists:
        # 典型情况：目标学号有效，只是首次调用把参数写错了
        failure_category = parameter_issue
        cause = (
            f"首次调用使用了与原始任务不一致的学号参数：原始任务要求查询 {target}，实际传入 {used}。"
            f"{failure_clause}。"
            "问题出在调用参数，而不是成绩库或工具本身。"
        )
        conclusion = (
            f"错误定位为第 {call_step} 步工具调用的 student_id 参数："
            f"实际传入 {used!r}，而原始任务要求 {target!r}，两者不一致，属于参数错误；"
            f"目标学号 {target} 本身登记在成绩库中，把参数改回目标学号后重试即可查到。"
        )
        repair_basis = (
            f"第 {parse_step.get('step', 0)} 步的原始任务明确要求查询学号 {target}；"
            f"第 {call_step} 步工具返回的 queried_student_id={queried!r} "
            f"证明本次查询确实使用了 {used!r}。"
            f"因此修正依据是把 student_id 改回原始目标学号 {target} 后重试，"
            "而不是修改成绩库或降低查询标准。"
        )
    elif parameter_mismatch and not target_exists:
        # 参数确实写错，但即使改回目标学号也查不到：两种原因必须分开说明
        failure_category = f"{parameter_issue} + {target_issue}"
        cause = (
            "本次失败包含两件需要分开说明的事："
            f"① 首次调用的参数确实与原始任务不一致（原始任务要求 {target}，实际传入 {used}），"
            f"{failure_clause}；"
            f"② 用户输入的目标学号 {target!r} 本身也{target_predicate}，"
            f"因此把参数改回 {target} 重试同样不会成功，这与「参数写错」是两回事。"
            "系统不会为了显示成功而编造姓名、课程或成绩。"
        )
        conclusion = (
            f"错误定位分两层：第 {call_step} 步工具调用的 student_id 参数确实写错"
            f"（实际传入 {used!r}，原始任务要求 {target!r}）；"
            f"但把参数改回 {target!r} 也不能让查询成功，因为目标学号本身{target_predicate}。"
        )
        repair_basis = (
            f"第 {parse_step.get('step', 0)} 步的原始任务明确要求查询学号 {target}；"
            f"第 {call_step} 步工具返回的 queried_student_id={queried!r} "
            f"证明本次查询确实使用了 {used!r}。"
            f"修正依据是把 student_id 改回原始目标学号 {target} 后重试；"
            f"但重试仍然无法成功：目标学号本身{target_predicate}，"
            "因此只能如实报告失败，而不是修改成绩库或编造数据。"
        )
    elif not parameter_mismatch and not target_exists:
        # 参数没错，是目标学号本身查不到
        failure_category = f"{target_issue}（不是参数错误）"
        if error_code in (ERROR_STUDENT_NOT_FOUND, ERROR_INVALID_STUDENT_ID):
            reason_clause = f"原因是目标学号 {target!r} 本身{target_predicate}"
        else:
            reason_clause = (
                f"该错误码不在本次实验已定义的范围内，"
                "只能确认这次调用失败，不能据此推断原因"
            )
        cause = (
            f"首次调用使用的学号 {used} 与原始任务的目标学号完全一致，本次失败不是参数错误；"
            f"工具返回 error_code={error_code!r}，{reason_clause}。"
            "重新提交同一个学号不会得到不同结果。"
        )
        conclusion = (
            f"错误定位为第 {call_step} 步工具调用：传入参数与原始任务要求一致，"
            f"失败原因是目标学号 {target!r} 本身{target_predicate}，而不是调用参数写错。"
        )
        repair_basis = (
            f"第 {parse_step.get('step', 0)} 步的原始任务要求查询学号 {target}，"
            f"第 {call_step} 步实际传入的也是 {used}，两者一致，不存在需要修正的参数；"
            + (
                "重试只会得到同一个格式错误，需要先把输入改成合法的纯数字学号，"
                "本系统不会替用户改写学号。"
                if not target.isdigit()
                else f"重试只能用于确认 {target} 确实不在成绩库中。"
            )
        )
    else:
        # 参数与目标一致且学号在库中，但工具仍返回错误：不能归因为参数问题
        failure_category = "非参数错误：工具返回其它错误"
        cause = (
            f"首次调用使用的学号 {used} 与原始任务的目标学号一致，且该学号登记在成绩库中，"
            f"但工具返回 error_code={error_code!r}、message={tool_result.get('message')!r}，"
            "失败原因不在本次调用参数上，需要按工具返回的错误码进一步排查。"
        )
        conclusion = (
            f"错误定位为第 {call_step} 步工具调用：参数与原始任务一致，"
            f"工具返回的错误码 {error_code!r} 不能归因为参数错误。"
        )
        repair_basis = (
            f"第 {call_step} 步实际传入 {used}，与原始任务要求一致，没有可修正的参数；"
            "应先排查工具返回的错误码，再决定下一步动作。"
        )

    return {
        "error_found": True,
        "error_location": f"第 {call_step} 步「{PHASE_FIRST_CALL}」的 student_id 参数",
        "actual_arguments": {"student_id": used},
        "expected_arguments": {"student_id": target},
        "error_code": error_code,
        "tool_message": tool_result.get("message"),
        "tool_response": tool_result,
        "parameter_mismatch": parameter_mismatch,
        "target_exists_in_db": target_exists,
        "target_status_text": target_status_text,
        "failure_category": failure_category,
        "cause": cause,
        "conclusion": conclusion,
        "repair_basis": repair_basis,
        "evidence": evidence,
    }


# ---------------------------------------------------------------------------
# 纠错层：参数修正方案与重试结论
# ---------------------------------------------------------------------------


def build_repair_plan(
    target_student_id: str,
    used_student_id: str,
    basis: str,
) -> dict[str, Any]:
    """构造参数修正方案（只描述方案，不执行重试）。

    只有首次调用参数与目标学号确实不同时，才记为一次修正；两者相同时返回空的
    修正记录，避免出现「9999 → 9999」这类误导性的「修正成功」信息。
    """
    changed = used_student_id != target_student_id
    changed_fields = (
        [{"field": "student_id", "before": used_student_id, "after": target_student_id}]
        if changed
        else []
    )
    return {
        "corrected_arguments": {"student_id": target_student_id},
        "changed": changed,
        "changed_fields": changed_fields,
        "basis": basis,
        "correction_text": (
            f"student_id：{used_student_id} → {target_student_id}"
            if changed
            else f"参数未变更（{used_student_id} 已经是目标学号），不存在需要修正的参数"
        ),
    }


def build_retry_analysis(
    target_student_id: str,
    used_student_id: str,
    retry_result: dict[str, Any],
    parameter_changed: bool,
) -> dict[str, Any]:
    """说明重试结果的真实含义。

    归因只依据工具真实返回的错误码：只有 STUDENT_NOT_FOUND 才能说成
    「目标学号本身不在成绩库中」；INVALID_STUDENT_ID 必须说成「输入格式或类型非法」，
    不能仅凭 target_exists_in_db == False 就把失败归因于学号不存在。
    ``attribution`` 是给最终 summary 复用的同一句归因，保证两处表述一致。
    """
    target_exists = str(target_student_id) in STUDENT_DB
    status = retry_result.get("status")
    error_code = retry_result.get("error_code")
    origin = (
        f"（由首次调用的 {used_student_id!r} 修正而来）"
        if parameter_changed
        else "（与首次调用的参数相同，本就不存在需要修正的参数）"
    )

    if status == STATUS_SUCCESS:
        conclusion = (
            f"重试使用的是用户输入的目标学号 {target_student_id!r}，工具返回成功，"
            f"结果中的 queried_student_id={retry_result.get('queried_student_id')!r}，"
            "查询到的就是目标学号对应的成绩。"
        )
        attribution = (
            f"重试已使用用户输入的目标学号 {target_student_id}，工具返回成功。"
        )
    elif error_code == ERROR_STUDENT_NOT_FOUND and not target_exists:
        conclusion = (
            f"重试使用的是用户输入的目标学号 {target_student_id!r}{origin}，"
            f"工具仍返回 error_code={ERROR_STUDENT_NOT_FOUND!r}："
            "该学号本身不在成绩库中，所以失败原因不是调用参数，继续修改参数也不会得到结果。"
        )
        attribution = (
            f"重试已使用用户输入的目标学号 {target_student_id}，"
            f"工具返回 {ERROR_STUDENT_NOT_FOUND}："
            "该学号本身不在成绩库中，属于「目标学号不存在」，而不是「调用参数错误」。"
        )
    elif error_code == ERROR_STUDENT_NOT_FOUND:
        conclusion = (
            f"重试使用 {target_student_id!r} 仍返回 {ERROR_STUDENT_NOT_FOUND!r}，"
            "而该学号已经登记在成绩库中，说明问题不在调用参数上，需要人工排查。"
        )
        attribution = (
            f"重试已使用用户输入的目标学号 {target_student_id}，"
            f"工具返回 {ERROR_STUDENT_NOT_FOUND}，而该学号已经登记在成绩库中，需要人工排查。"
        )
    elif error_code == ERROR_INVALID_STUDENT_ID:
        conclusion = (
            f"重试使用的是用户输入的目标学号 {target_student_id!r}{origin}，"
            f"工具返回 error_code={ERROR_INVALID_STUDENT_ID!r}："
            "该输入不是合法的纯数字学号（格式或类型不符合要求），工具没有执行查询，"
            "本次没有得到任何有效的成绩数据，因此不能据此认定学生是否存在；"
            "需要先把输入改成合法学号，而不是继续修改调用参数。"
        )
        attribution = (
            f"重试已使用用户输入的目标学号 {target_student_id}，"
            f"工具返回 {ERROR_INVALID_STUDENT_ID}："
            "该输入不是合法的纯数字学号（格式或类型不符合要求），本次查询没有得到有效成绩数据，"
            "也不能据此认定学生是否存在。"
        )
    else:
        conclusion = (
            f"重试使用 {target_student_id!r} 返回 error_code={error_code!r}"
            f"（message={retry_result.get('message')!r}），最终结论以独立验证结果为准。"
        )
        attribution = (
            f"重试已使用用户输入的目标学号 {target_student_id}，工具返回 error_code={error_code!r}，"
            "该错误码不在本次实验已定义的范围内，最终结论以独立验证结果为准。"
        )

    return {
        "retried": True,
        "requested_student_id": target_student_id,
        "parameter_changed": bool(parameter_changed),
        "target_exists_in_db": target_exists,
        "status": status,
        "error_code": error_code,
        "conclusion": conclusion,
        "attribution": attribution,
    }


# ---------------------------------------------------------------------------
# 计时：把 perf_counter 的秒数换算成毫秒与秒两种表述
# ---------------------------------------------------------------------------


def describe_elapsed(elapsed_seconds: float, milliseconds_digits: int = 3) -> dict[str, Any]:
    """把计时结果（秒）同时换算为毫秒与秒，并给出统一文本。

    换算关系固定为 1 秒 = 1000 毫秒。数值不做任何「修饰」：耗时很短时保留
    更多小数位（毫秒 3 位、秒 6 位），而不是把数值放大到看起来合理。
    展示用的 ``*_text`` 是定点小数字符串，避免出现 7.6e-05 这类科学计数法。
    """
    seconds = float(elapsed_seconds)
    milliseconds = seconds * 1000.0
    seconds_text = f"{seconds:.6f}"
    milliseconds_text = f"{milliseconds:.{milliseconds_digits}f}"
    return {
        "seconds": round(seconds, 6),
        "milliseconds": round(milliseconds, milliseconds_digits),
        "seconds_text": seconds_text,
        "milliseconds_text": milliseconds_text,
        "text": f"{milliseconds_text} 毫秒（{seconds_text} 秒）",
    }


# ---------------------------------------------------------------------------
# 验证层：独立检查真实返回值，拒绝不合格结果
# ---------------------------------------------------------------------------


def verify_result(
    tool_result: Any,
    expected_student_id: str,
    recorded_result: Any = None,
) -> dict[str, Any]:
    """独立验证器：直接检查工具的真实返回结果是否满足全部要求。

    验证器不读取诊断结论，也不相信纠错器的自我声明，只检查传入的结果对象：
    状态是否为成功、结构是否完整、学号是否与目标一致、成绩字段是否存在且为
    合理数值。任何一项不满足都判定验证失败。
    """
    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    if not isinstance(tool_result, dict):
        add(
            "返回结果为结构化对象",
            False,
            f"期望 dict，实际为 {type(tool_result).__name__}：{tool_result!r}",
        )
        add("状态字段为成功", False, "无法检查：返回结果不是结构化对象")
        add("data 字段为结构化数据", False, "无法检查：返回结果不是结构化对象")
        add("成绩数据结构完整", False, f"无法检查：缺少字段 {list(DATA_FIELDS)}")
        add("学号与目标一致", False, "无法检查：返回结果不是结构化对象")
        add("成绩字段为数值", False, "无法检查：返回结果不是结构化对象")
        add("成绩数值在合理范围", False, "无法检查：返回结果不是结构化对象")
        add("无遗留错误码", False, "无法检查：返回结果不是结构化对象")
        return _finish_verification(checks, tool_result, expected_student_id, recorded_result)

    status_value = tool_result.get("status")
    add(
        "返回结果为结构化对象",
        True,
        f"dict，键为 {'、'.join(sorted(tool_result))}",
    )
    add(
        "状态字段为成功",
        status_value == STATUS_SUCCESS,
        f"status = {status_value!r}（期望 {STATUS_SUCCESS!r}）",
    )

    data = tool_result.get("data")
    data_is_mapping = isinstance(data, dict)
    add(
        "data 字段为结构化数据",
        data_is_mapping,
        f"data = {data!r}",
    )

    missing = [field for field in DATA_FIELDS if not data_is_mapping or field not in data]
    add(
        "成绩数据结构完整",
        not missing,
        f"缺失字段：{missing}" if missing else f"字段齐全：{'、'.join(DATA_FIELDS)}",
    )

    actual_id = data.get("student_id") if data_is_mapping else None
    add(
        "学号与目标一致",
        actual_id == expected_student_id,
        f"结果学号 {actual_id!r}（目标学号 {expected_student_id!r}）",
    )

    score = data.get("score") if data_is_mapping else None
    score_is_number = isinstance(score, (int, float)) and not isinstance(score, bool)
    add(
        "成绩字段为数值",
        score_is_number,
        f"score = {score!r}（类型 {type(score).__name__}）",
    )

    in_range = score_is_number and SCORE_MIN <= float(score) <= SCORE_MAX
    add(
        "成绩数值在合理范围",
        in_range,
        f"合理区间 [{SCORE_MIN:g}, {SCORE_MAX:g}]，实际 score = {score!r}",
    )

    error_code = tool_result.get("error_code")
    add(
        "无遗留错误码",
        not error_code,
        f"error_code = {error_code!r}",
    )

    return _finish_verification(checks, tool_result, expected_student_id, recorded_result)


def _finish_verification(
    checks: list[dict[str, Any]],
    tool_result: Any,
    expected_student_id: str,
    recorded_result: Any = None,
) -> dict[str, Any]:
    """汇总验证清单，追加来源可追溯性检查，并给出结论。"""
    if recorded_result is not None:
        checks.append(
            {
                "name": "结果来源可追溯",
                "passed": tool_result is recorded_result,
                "detail": "验证对象与轨迹中记录的工具返回值是同一个对象，不是二次构造的结果",
            }
        )

    passed = all(check["passed"] for check in checks)
    return {
        "passed": passed,
        "checks": checks,
        "expected_student_id": expected_student_id,
        "checked_result": tool_result,
        "verdict": (
            "验证通过：结果由工具真实返回，状态、结构、学号与成绩均符合要求。"
            if passed
            else "验证未通过：结果不满足全部要求，不能判定为成功。"
        ),
    }


# ---------------------------------------------------------------------------
# 结构化实验对象
# ---------------------------------------------------------------------------


@dataclass
class ExperimentResult:
    """一次完整实验的结构化结果。"""

    raw_task: dict[str, Any]
    trace: list[dict[str, Any]]
    diagnosis: dict[str, Any]
    repair: dict[str, Any]
    retry_analysis: dict[str, Any]
    retry_result: dict[str, Any] | None
    verification: dict[str, Any]
    comparison: dict[str, Any]
    final_status: str
    final_status_text: str
    summary: str

    def to_dict(self) -> dict[str, Any]:
        """转为可序列化的字典，便于展示与断言。"""
        return {
            "raw_task": self.raw_task,
            "trace": self.trace,
            "diagnosis": self.diagnosis,
            "repair": self.repair,
            "retry_analysis": self.retry_analysis,
            "retry_result": self.retry_result,
            "verification": self.verification,
            "comparison": self.comparison,
            "final_status": self.final_status,
            "final_status_text": self.final_status_text,
            "summary": self.summary,
        }

    def tool_calls(self) -> list[dict[str, Any]]:
        """返回轨迹中的全部工具调用步骤。"""
        return [entry for entry in self.trace if entry["tool"] == TOOL_NAME]


# ---------------------------------------------------------------------------
# 实验主流程
# ---------------------------------------------------------------------------


def run_experiment(
    target_student_id: Any = None,
    wrong_student_id: Any = None,
) -> ExperimentResult:
    """执行一次"失败—诊断—纠错—重试—验证"的完整实验。

    参数:
        target_student_id: 用户给出的目标学号，缺省为 1002。
        wrong_student_id: 首次调用故意注入的错误学号；缺省使用
            DELIBERATE_WRONG_STUDENT_ID（9999）。无论调用方传入什么，
            实际使用的错误学号都会经过 choose_wrong_student_id 校验，
            保证它与目标学号不同、且不在成绩库中。

    返回:
        ExperimentResult，包含原始任务、完整轨迹、诊断、参数修正、
        重试结论、重试结果、独立验证与最终状态。
    """
    raw_input = DEFAULT_TARGET_STUDENT_ID if target_student_id is None else str(target_student_id)
    target = raw_input.strip()
    requested_wrong = "" if wrong_student_id is None else str(wrong_student_id).strip()
    # 首次注入的错误学号必须不同于目标学号，否则「首次调用参数错误」的前提不成立
    wrong = choose_wrong_student_id(target, requested_wrong or None)
    wrong_adjusted = wrong != (requested_wrong or DELIBERATE_WRONG_STUDENT_ID)

    trace: list[dict[str, Any]] = []

    def record(
        phase: str,
        action: str,
        tool: str,
        arguments: dict[str, Any],
        result: Any,
        status: str,
        result_summary: str,
    ) -> dict[str, Any]:
        entry = {
            "step": len(trace) + 1,
            "phase": phase,
            "action": action,
            "tool": tool,
            "arguments": arguments,
            "result": result,
            "result_summary": result_summary,
            "status": status,
        }
        trace.append(entry)
        return entry

    raw_task = {
        "project": PROJECT_NAME,
        "user_input": raw_input,
        "target_student_id": target,
        "deliberate_wrong_student_id": wrong,
        "requested_wrong_student_id": requested_wrong or DELIBERATE_WRONG_STUDENT_ID,
        "wrong_student_id_adjusted": wrong_adjusted,
        "wrong_student_id_note": (
            f"首选错误学号 {requested_wrong or DELIBERATE_WRONG_STUDENT_ID} 与目标学号相同，"
            f"已自动改用 {wrong} 作为首次调用的错误学号，保证首次调用参数与目标学号不同"
            if wrong_adjusted
            else (
                f"首次调用注入的错误学号为 {wrong}，与目标学号 {target} 不同，因此第一次调用会真实失败"
                if target
                else "目标学号为空，未执行任何工具调用"
            )
        ),
        "tool": TOOL_NAME,
        "available_student_ids": sorted(STUDENT_DB),
    }

    # 0) 解析任务
    parse_entry = record(
        PHASE_PARSE,
        "解析用户输入，确定本次实验的目标学号",
        "-",
        {"raw_input": raw_input},
        {"target_student_id": target},
        STATUS_INFO,
        f"目标学号 = {target!r}",
    )

    if not target:
        diagnosis = {
            "error_found": False,
            "error_location": None,
            "actual_arguments": None,
            "expected_arguments": None,
            "error_code": None,
            "tool_message": None,
            "tool_response": None,
            "parameter_mismatch": None,
            "target_exists_in_db": False,
            "target_status_text": "否（没有输入目标学号）",
            "failure_category": "输入无效",
            "cause": "用户没有提供目标学号，无法确定查询目标。",
            "conclusion": "输入为空，实验未执行。",
            "repair_basis": "没有可信的目标学号，系统不会猜测或编造查询目标。",
            "evidence": [
                {
                    "step": parse_entry["step"],
                    "observation": f"解析阶段的原始输入为 {raw_input!r}，去空格后为空",
                }
            ],
        }
        return ExperimentResult(
            raw_task=raw_task,
            trace=trace,
            diagnosis=diagnosis,
            repair={
                "corrected_arguments": None,
                "changed": False,
                "changed_fields": [],
                "basis": diagnosis["repair_basis"],
                "correction_text": "输入无效，没有需要修正的参数",
            },
            retry_analysis={
                "retried": False,
                "requested_student_id": target,
                "parameter_changed": False,
                "target_exists_in_db": False,
                "status": None,
                "error_code": None,
                "conclusion": "目标学号为空，未执行任何工具调用与重试。",
                "attribution": "目标学号为空，未执行任何工具调用与重试。",
            },
            retry_result=None,
            verification={
                "passed": False,
                "checks": [],
                "expected_student_id": target,
                "checked_result": None,
                "verdict": "未执行验证：目标学号为空。",
            },
            comparison={"field": "student_id", "before": None, "after": None, "changed": False, "change_text": "无变更"},
            final_status=FINAL_INVALID_INPUT,
            final_status_text=FINAL_STATUS_TEXT[FINAL_INVALID_INPUT],
            summary=f"目标学号为空（原始输入 {raw_input!r}），实验未执行，最终状态：输入无效。",
        )

    # 1) 第一次工具调用：故意使用错误学号
    first_arguments = {"student_id": wrong}
    first_entry = record(
        PHASE_FIRST_CALL,
        f"第一次调用工具，故意使用错误学号 {wrong}",
        TOOL_NAME,
        first_arguments,
        None,
        STATUS_INFO,
        "",
    )
    first_result = query_student_score(wrong)
    first_entry["result"] = first_result
    first_entry["status"] = first_result["status"]
    first_entry["result_summary"] = first_result["message"]

    # 2) 诊断
    diagnosis = diagnose_trace(target, wrong, first_result, trace)
    record(
        PHASE_DIAGNOSIS,
        "依据轨迹证据定位错误并说明修正依据",
        "-",
        {"目标学号": target, "实际使用学号": wrong},
        diagnosis,
        STATUS_INFO,
        diagnosis["conclusion"],
    )

    retry_result: dict[str, Any] | None = None
    repair: dict[str, Any] = {
        "corrected_arguments": None,
        "changed": False,
        "changed_fields": [],
        "basis": diagnosis["repair_basis"],
        "correction_text": "首次调用即成功，无需修正参数",
    }
    verification: dict[str, Any]
    comparison: dict[str, Any]

    if not diagnosis["error_found"]:
        # 首次调用即成功：仍要独立验证，验证不通过同样判失败
        verification = verify_result(
            first_result, expected_student_id=target, recorded_result=first_result
        )
        retry_analysis = {
            "retried": False,
            "requested_student_id": target,
            "parameter_changed": False,
            "target_exists_in_db": target in STUDENT_DB,
            "status": None,
            "error_code": None,
            "conclusion": "首次工具调用即返回成功，未发生重试。",
            "attribution": "首次工具调用即返回成功，未发生重试。",
        }
        comparison = {
            "field": "student_id",
            "before": {"arguments": first_arguments, "result": first_result, "status": first_result["status"]},
            "after": None,
            "changed": False,
            "change_text": "未发生参数变更",
        }
    else:
        # 3) 纠错：按原始目标学号修正参数
        repair = build_repair_plan(target, wrong, basis=diagnosis["repair_basis"])
        repaired_arguments = repair["corrected_arguments"]
        record(
            PHASE_REPAIR,
            (
                "依据原始目标学号修正调用参数"
                if repair["changed"]
                else "按原始目标学号重新调用（参数未变更，无修正记录）"
            ),
            "-",
            repaired_arguments,
            repair,
            STATUS_INFO,
            repair["correction_text"],
        )

        # 4) 重试：使用修正后的参数再次真实调用工具
        retry_entry = record(
            PHASE_RETRY,
            f"使用用户输入的目标学号 {target} 重试工具调用",
            TOOL_NAME,
            repaired_arguments,
            None,
            STATUS_INFO,
            "",
        )
        retry_result = query_student_score(target)
        retry_entry["result"] = retry_result
        retry_entry["status"] = retry_result["status"]
        retry_entry["result_summary"] = retry_result["message"]

        verified_result = retry_result
        verification = verify_result(
            verified_result, expected_student_id=target, recorded_result=retry_entry["result"]
        )
        retry_analysis = build_retry_analysis(target, wrong, retry_result, repair["changed"])
        comparison = {
            "field": "student_id",
            "before": {"arguments": first_arguments, "result": first_result, "status": first_result["status"]},
            "after": {"arguments": repaired_arguments, "result": retry_result, "status": retry_result["status"]},
            "changed": repair["changed"],
            "change_text": repair["correction_text"],
        }

    record(
        PHASE_VERIFY,
        "独立验证器直接检查结果是否满足全部要求",
        "-",
        {"expected_student_id": target},
        verification,
        STATUS_INFO,
        verification["verdict"],
    )

    if verification["passed"]:
        final_status = FINAL_SUCCESS
        summary = f"目标学号 {target} 的成绩查询在纠错后通过独立验证，最终状态：成功。"
    else:
        final_status = FINAL_FAILED
        failed_checks = [check["name"] for check in verification["checks"] if not check["passed"]]
        reason = "；".join(failed_checks) if failed_checks else "验证未通过"
        # 归因句与「重试结论」共用同一来源（build_retry_analysis），
        # 避免最终状态与重试结论对错误原因给出相互矛盾的解释
        if retry_analysis["retried"]:
            head = retry_analysis["attribution"]
        else:
            head = "本次没有发生重试。"
        summary = (
            f"{head}目标学号 {target} 未通过独立验证（未满足：{reason}），"
            "最终状态：失败。系统不会把失败的结果包装成成功。"
        )

    return ExperimentResult(
        raw_task=raw_task,
        trace=trace,
        diagnosis=diagnosis,
        repair=repair,
        retry_analysis=retry_analysis,
        retry_result=retry_result,
        verification=verification,
        comparison=comparison,
        final_status=final_status,
        final_status_text=FINAL_STATUS_TEXT[final_status],
        summary=summary,
    )


if __name__ == "__main__":  # pragma: no cover - 便于命令行快速查看
    import json

    outcome = run_experiment(DEFAULT_TARGET_STUDENT_ID)
    print(json.dumps(outcome.to_dict(), ensure_ascii=False, indent=2))
