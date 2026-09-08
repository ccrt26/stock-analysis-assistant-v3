"""PRISM WEB 展示合同辅助：展示日期、观点枚举透传与只读观察口径。

小型纯转换模块：只做确定性的格式转换与校验；不访问网络、不读取文件、
不做任何研究判断。供渲染器、适配器与测试共用；页面端对应实现见
tools/guanlan-prism/src/core.js（两侧行为必须一致，由回归测试约束）。
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Mapping, Sequence

_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MMDD_RE = re.compile(r"^\d{2}-\d{2}$")


class DateContractError(ValueError):
    """日期序列无法证明年份或与 analysis_date 不一致时拒绝计算。"""


def _check_strictly_increasing(iso_dates: Sequence[str], label: str) -> None:
    for previous, current in zip(iso_dates, iso_dates[1:]):
        if current <= previous:
            raise DateContractError(
                f"{label} 不是严格递增的日期序列：{previous} → {current}；"
                "跨年或倒序无法定位日期，请从原归档重新生成展示数据"
            )


def _check_iso_shape(values: Sequence[str], label: str) -> None:
    for value in values:
        if not isinstance(value, str) or not _ISO_RE.fullmatch(value):
            raise DateContractError(f"{label} 含非 YYYY-MM-DD 的日期值：{value!r}")
        try:
            date.fromisoformat(value)
        except ValueError as error:
            raise DateContractError(f"{label} 含无效日期：{value!r}") from error


def resolve_session_dates(
    dates: Sequence[str] | None,
    analysis_date: str,
    session_dates: Sequence[str] | None = None,
) -> list[str]:
    """返回与 dates 等长同序、严格递增的完整 ISO 交易日序列。

    - sessionDates（新合同）：校验后原样使用，末日必须等于 analysis_date。
    - dates 本身是完整 ISO（旧自接入方）：按 ISO 校验后使用。
    - dates 是文档约定的同年 MM-DD：假设与 analysis_date 同年；序列严格递增
      且末日等于 analysis_date 时该假设自洽，否则明确拒绝，不猜年份。
    """
    if not isinstance(analysis_date, str) or not _ISO_RE.fullmatch(analysis_date):
        raise DateContractError(f"analysis_date 必须是 YYYY-MM-DD：{analysis_date!r}")
    if not isinstance(dates, (list, tuple)) or not dates:
        raise DateContractError("快照缺少非空 dates 交易日序列")
    if session_dates is not None:
        resolved = [str(value) for value in session_dates]
        _check_iso_shape(resolved, "sessionDates")
        if len(resolved) != len(dates):
            raise DateContractError(
                f"sessionDates 长度 {len(resolved)} 与 dates 长度 {len(dates)} 不一致"
            )
        _check_strictly_increasing(resolved, "sessionDates")
        if resolved[-1] != analysis_date:
            raise DateContractError(
                f"sessionDates 末日 {resolved[-1]} 与 analysis_date {analysis_date} 不一致"
            )
        return resolved
    if all(isinstance(value, str) and _ISO_RE.fullmatch(value) for value in dates):
        resolved = list(dates)
        _check_iso_shape(resolved, "dates")
        _check_strictly_increasing(resolved, "dates")
        if resolved[-1] != analysis_date:
            raise DateContractError(
                f"dates 末日 {resolved[-1]} 与 analysis_date {analysis_date} 不一致"
            )
        return resolved
    if not all(isinstance(value, str) and _MMDD_RE.fullmatch(value) for value in dates):
        raise DateContractError(
            f"dates 既不是完整 ISO 也不是 MM-DD 序列：{list(dates)[:3]!r}"
        )
    year = analysis_date[:4]
    resolved = [f"{year}-{value}" for value in dates]
    for value in resolved:
        try:
            date.fromisoformat(value)
        except ValueError as error:
            raise DateContractError(f"dates 含无效 MM-DD：{value!r}") from error
    _check_strictly_increasing(resolved, "dates")
    if resolved[-1] != analysis_date:
        raise DateContractError(
            f"旧 MM-DD 序列末日 {resolved[-1]} 与 analysis_date {analysis_date} 不一致，"
            "无法证明各日期所属年份；请从原归档重新生成展示数据"
        )
    return resolved


def display_dates(session_dates: Sequence[str]) -> list[str]:
    """旧 V4 布局的 MM-DD 显示数组；只用于显示，不参与定位与比较。"""
    return [value[5:] for value in session_dates]


# ---------------------------------------------------------------------------
# 观点枚举：source → display。严格透传原值；无值为 None；未识别不猜测。
# ---------------------------------------------------------------------------

# outlook_1_3d（1—3 个交易日的短期展望）三类归并；event_pending/空/未识别 → None。
OUTLOOK_DIRECTION: Mapping[str, str | None] = {
    "strengthening": "up",
    "continuation_possible": "up",
    "range_or_wait": "sideways",
    "weakening": "down",
    "overheated": "down",
    "invalidated": "down",
}


def outlook_direction(outlook_code: Any) -> str | None:
    if outlook_code in (None, ""):
        return None
    return OUTLOOK_DIRECTION.get(str(outlook_code))


def review_enums(review: Mapping[str, Any]) -> dict[str, str | None]:
    """从台账/报告复盘原字段提取结构化枚举；缺值输出 None，未知值原样透传。

    source→display：view_change→viewChange；current_assessment→assessmentCode；
    outlook_1_3d→outlookCode；outlookDirection 由 outlookCode 三类归并得出。
    没有值不默认 unchanged；中文文案不参与判断。
    """
    view_change = review.get("view_change")
    assessment = review.get("current_assessment")
    outlook = review.get("outlook_1_3d")
    return {
        "viewChange": str(view_change) if view_change else None,
        "assessmentCode": str(assessment) if assessment else None,
        "outlookCode": str(outlook) if outlook else None,
        "outlookDirection": outlook_direction(outlook),
    }


# ---------------------------------------------------------------------------
# 只读观察口径与来源（F3/F8）：集中维护，不给前端修改历史目标的开关。
# ---------------------------------------------------------------------------

PRIMARY_DAYS = 20
TARGET_RETURN = 0.2


def observation_policy() -> dict[str, Any]:
    return {
        "primaryDays": PRIMARY_DAYS,
        "targetReturn": TARGET_RETURN,
        "origin": "existing_v4_contract",
    }


def source_info(
    kind: str = "frozen_archive",
    label: str = "本地冻结复盘归档",
    externally_verified: bool = False,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "label": label,
        "externallyVerified": externally_verified,
    }
