from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any, Optional

from pydantic import BaseModel, Field

from stock_analyzer.domain.models import (
    ActionDecision,
    ActionLabel,
    ActionRecommendation,
    EvidenceAtom,
    EvidencePolarity,
    FocusDailyUpdate,
    FocusEntryThesis,
    FocusSource,
    FocusState,
    Recommendation,
    StrategyEvidenceSnapshot,
)


SYSTEM_FOCUS_CAP = 5
SUPPORTIVE_OBSERVATION_WINDOW = 5
MIN_SUPPORTIVE_OBSERVATIONS = 3


class FocusUpdateResult(BaseModel):
    focus_states: list[FocusState] = Field(default_factory=list)
    entry_theses: list[FocusEntryThesis] = Field(default_factory=list)
    daily_updates: list[FocusDailyUpdate] = Field(default_factory=list)


def update_focus_watchlist(
    existing: list[FocusState],
    recommendations: list[Recommendation],
    invalidated_codes: set[str],
    enter_threshold: float = 80.0,
    trade_date: Optional[date] = None,
) -> list[FocusState]:
    by_code = {item.ts_code: item for item in existing}
    output: list[FocusState] = []

    for old in existing:
        if old.ts_code in invalidated_codes:
            output.append(
                old.model_copy(
                    update={
                        "trade_date": trade_date or old.trade_date,
                        "state": ActionLabel.EXIT_OBSERVATION,
                        "exit_reason": "触发预设失效条件",
                    }
                )
            )
        else:
            output.append(
                old.model_copy(
                    update={
                        "trade_date": trade_date or old.trade_date,
                        "state": ActionLabel.CONTINUE_OBSERVATION,
                    }
                )
            )

    for rec in recommendations:
        if rec.ts_code in by_code or rec.ts_code in invalidated_codes or rec.score < enter_threshold:
            continue
        output.append(
            FocusState(
                trade_date=rec.trade_date,
                ts_code=rec.ts_code,
                state=ActionLabel.ENTER_OBSERVATION,
                entry_date=rec.trade_date,
                entry_reason="推荐分数强且支持证据满足重点关注门槛",
                invalidation_conditions=["核心趋势证据消失", "出现官方重大风险", "反证强于支持证据"],
            )
        )
    return output


def update_focus_watchlist_v2(
    existing: list[FocusState],
    recommendation_snapshots: list[StrategyEvidenceSnapshot],
    manual_entries: list[Any],
    trade_date: date,
) -> FocusUpdateResult:
    snapshots_by_code = _group_snapshots_by_code(recommendation_snapshots)
    latest_by_code = {
        ts_code: snapshots[-1] for ts_code, snapshots in snapshots_by_code.items()
    }
    existing_by_code = {item.ts_code: item for item in existing}
    manual_by_code = _manual_entries_by_code(manual_entries)

    focus_states: list[FocusState] = []
    entry_theses: list[FocusEntryThesis] = []
    daily_updates: list[FocusDailyUpdate] = []
    emitted_codes: set[str] = set()
    daily_update_codes: set[str] = set()

    for old in existing:
        snapshot = latest_by_code.get(old.ts_code)
        invalidation_conditions = (
            list(snapshot.action.invalidation_conditions)
            if snapshot
            else list(old.invalidation_conditions)
        )
        focus_states.append(
            old.model_copy(
                update={
                    "trade_date": trade_date,
                    "state": ActionLabel.CONTINUE_OBSERVATION,
                    "invalidation_conditions": invalidation_conditions,
                }
            )
        )
        emitted_codes.add(old.ts_code)
        if snapshot:
            daily_updates.append(build_focus_daily_update(snapshot, old))
            daily_update_codes.add(old.ts_code)

    system_candidates = _system_focus_candidates(snapshots_by_code)
    system_selected_count = 0
    for snapshot in _rank_system_candidates(system_candidates):
        if system_selected_count >= SYSTEM_FOCUS_CAP:
            break
        if snapshot.ts_code in emitted_codes or snapshot.ts_code in manual_by_code:
            continue

        thesis = build_focus_entry_thesis(
            snapshot=snapshot,
            source=FocusSource.SYSTEM,
            manual_reason=None,
        )
        focus_states.append(_new_focus_state(snapshot, trade_date, thesis.thesis))
        entry_theses.append(thesis)
        if snapshot.ts_code not in daily_update_codes:
            daily_updates.append(build_focus_daily_update(snapshot))
            daily_update_codes.add(snapshot.ts_code)
        emitted_codes.add(snapshot.ts_code)
        system_selected_count += 1

    for ts_code, (manual_reason, manual_name) in manual_by_code.items():
        snapshot = latest_by_code.get(ts_code)
        if snapshot:
            thesis = build_focus_entry_thesis(
                snapshot=snapshot,
                source=FocusSource.MANUAL,
                manual_reason=manual_reason,
            )
            if ts_code not in daily_update_codes:
                daily_updates.append(build_focus_daily_update(snapshot))
                daily_update_codes.add(ts_code)
        else:
            thesis = _build_manual_missing_evidence_thesis(
                ts_code=ts_code,
                name=manual_name or ts_code,
                manual_reason=manual_reason,
                trade_date=trade_date,
            )
        state = (
            _manual_focus_state_from_existing(
                existing_by_code[ts_code], trade_date, thesis
            )
            if ts_code in existing_by_code
            else _manual_focus_state_from_thesis(thesis, trade_date)
        )
        if ts_code not in emitted_codes:
            focus_states.append(state)
        else:
            focus_states = [
                state if item.ts_code == ts_code else item for item in focus_states
            ]
        entry_theses.append(thesis)
        emitted_codes.add(ts_code)

    return FocusUpdateResult(
        focus_states=focus_states,
        entry_theses=entry_theses,
        daily_updates=daily_updates,
    )


def build_focus_entry_thesis(
    snapshot: StrategyEvidenceSnapshot,
    source: FocusSource,
    manual_reason: str | None,
) -> FocusEntryThesis:
    supporting_ids = _supporting_evidence_ids(snapshot)
    risk_notes = _risk_notes(snapshot)
    validation_result = _validation_result(snapshot, source, supporting_ids)
    thesis_text = snapshot.thesis

    if source == FocusSource.MANUAL:
        reason = (manual_reason or "未提供人工关注理由").strip()
        if validation_result == "证据不足":
            thesis_text = (
                f"人工关注理由：{reason}；当前 Strategy V2 证据不足，"
                "不能把人工理由视为已验证结论。"
            )
        else:
            thesis_text = (
                f"人工关注理由：{reason}；系统证据待验证：{snapshot.thesis}"
            )

    return FocusEntryThesis(
        evidence_id=snapshot.evidence_id,
        trade_date=snapshot.trade_date,
        ts_code=snapshot.ts_code,
        name=snapshot.name,
        source=source,
        thesis=thesis_text,
        action=snapshot.action,
        expected_upside_pct=snapshot.expected_upside_pct,
        expected_downside_pct=snapshot.expected_downside_pct,
        risk_reward=snapshot.risk_reward,
        required_confirmation=list(snapshot.action.required_confirmation),
        invalidation_conditions=list(snapshot.action.invalidation_conditions),
        supporting_evidence_ids=supporting_ids,
        validation_result=validation_result,
        risk_notes=risk_notes,
    )


def build_focus_daily_update(
    snapshot: StrategyEvidenceSnapshot,
    focus_state: FocusState | None = None,
) -> FocusDailyUpdate:
    action = (
        _removal_confirmation_action(snapshot)
        if _risk_dominates(snapshot)
        else snapshot.action
    )
    thesis = snapshot.thesis
    if _risk_dominates(snapshot):
        thesis = f"{snapshot.thesis} 风险或反证已主导，建议确认是否移出重点观察。"

    return FocusDailyUpdate(
        trade_date=snapshot.trade_date,
        ts_code=snapshot.ts_code,
        name=snapshot.name,
        evidence_id=snapshot.evidence_id,
        thesis=thesis,
        action=action,
        focus_entry_progress=snapshot.focus_entry_progress
        or _fallback_focus_progress(snapshot, focus_state),
        new_support=_evidence_atoms(snapshot, EvidencePolarity.SUPPORT),
        new_counter=_evidence_atoms(snapshot, EvidencePolarity.COUNTER),
        required_confirmation=list(action.required_confirmation),
        invalidation_conditions=list(action.invalidation_conditions),
        data_insufficient=snapshot.data_insufficient,
        data_insufficient_reason=snapshot.data_insufficient_reason,
    )


def _group_snapshots_by_code(
    recommendation_snapshots: list[StrategyEvidenceSnapshot],
) -> dict[str, list[StrategyEvidenceSnapshot]]:
    grouped: dict[str, list[StrategyEvidenceSnapshot]] = defaultdict(list)
    for snapshot in recommendation_snapshots:
        grouped[snapshot.ts_code].append(snapshot)
    return {
        ts_code: sorted(items, key=lambda item: (item.trade_date, item.evidence_id))
        for ts_code, items in grouped.items()
    }


def _system_focus_candidates(
    snapshots_by_code: dict[str, list[StrategyEvidenceSnapshot]],
) -> list[StrategyEvidenceSnapshot]:
    candidates: list[StrategyEvidenceSnapshot] = []
    for snapshots in snapshots_by_code.values():
        latest_five = snapshots[-SUPPORTIVE_OBSERVATION_WINDOW:]
        supportive_count = sum(1 for item in latest_five if _is_supportive(item))
        latest = snapshots[-1]
        if supportive_count >= MIN_SUPPORTIVE_OBSERVATIONS and _is_supportive(latest):
            candidates.append(latest)
    return candidates


def _rank_system_candidates(
    candidates: list[StrategyEvidenceSnapshot],
) -> list[StrategyEvidenceSnapshot]:
    return sorted(
        candidates,
        key=lambda snapshot: (
            -snapshot.internal_score,
            -(snapshot.risk_reward or 0.0),
            -_thesis_quality(snapshot),
            snapshot.ts_code,
        ),
    )


def _is_supportive(snapshot: StrategyEvidenceSnapshot) -> bool:
    return (
        not snapshot.data_insufficient
        and (snapshot.expected_upside_pct or 0.0) >= 10.0
        and (snapshot.risk_reward or 0.0) >= 1.5
        and not _risk_dominates(snapshot)
    )


def _risk_dominates(snapshot: StrategyEvidenceSnapshot) -> bool:
    return snapshot.action.decision in {
        ActionDecision.NO_PARTICIPATION,
        ActionDecision.REDUCE_OR_AVOID,
        ActionDecision.CONFIRM_REMOVAL,
    }


def _thesis_quality(snapshot: StrategyEvidenceSnapshot) -> float:
    support = _evidence_atoms(snapshot, EvidencePolarity.SUPPORT)
    if not support:
        return 0.0
    return round(sum(atom.strength for atom in support) / len(support), 4)


def _supporting_evidence_ids(snapshot: StrategyEvidenceSnapshot) -> list[str]:
    return [atom.id for atom in _evidence_atoms(snapshot, EvidencePolarity.SUPPORT)]


def _evidence_atoms(
    snapshot: StrategyEvidenceSnapshot,
    polarity: EvidencePolarity,
) -> list[EvidenceAtom]:
    atoms: list[EvidenceAtom] = []
    for module in snapshot.modules:
        atoms.extend(module.support if polarity == EvidencePolarity.SUPPORT else module.counter)
    return atoms


def _validation_result(
    snapshot: StrategyEvidenceSnapshot,
    source: FocusSource,
    supporting_ids: list[str],
) -> str:
    if snapshot.data_insufficient or not supporting_ids:
        return "证据不足"
    if source == FocusSource.SYSTEM and _is_supportive(snapshot):
        return "通过"
    return "待验证"


def _risk_notes(snapshot: StrategyEvidenceSnapshot) -> list[str]:
    notes: list[str] = []
    if snapshot.data_insufficient:
        notes.append(f"证据不足：{snapshot.data_insufficient_reason or '关键数据缺失'}")
    if not _supporting_evidence_ids(snapshot):
        notes.append("证据不足：缺少正向证据原子")
    for atom in _evidence_atoms(snapshot, EvidencePolarity.COUNTER):
        notes.append(f"{atom.headline}：{atom.detail}" if atom.detail else atom.headline)
    if snapshot.action.risk_if_wrong:
        notes.append(snapshot.action.risk_if_wrong)
    return _dedupe(notes)


def _new_focus_state(
    snapshot: StrategyEvidenceSnapshot,
    trade_date: date,
    entry_reason: str,
) -> FocusState:
    return FocusState(
        trade_date=trade_date,
        ts_code=snapshot.ts_code,
        state=ActionLabel.ENTER_OBSERVATION,
        entry_date=trade_date,
        entry_reason=entry_reason,
        invalidation_conditions=list(snapshot.action.invalidation_conditions),
    )


def _manual_focus_state_from_existing(
    existing: FocusState,
    trade_date: date,
    thesis: FocusEntryThesis,
) -> FocusState:
    return existing.model_copy(
        update={
            "trade_date": trade_date,
            "state": ActionLabel.CONTINUE_OBSERVATION,
            "entry_reason": existing.entry_reason or thesis.thesis,
            "invalidation_conditions": list(thesis.invalidation_conditions),
        }
    )


def _manual_focus_state_from_thesis(
    thesis: FocusEntryThesis,
    trade_date: date,
) -> FocusState:
    return FocusState(
        trade_date=trade_date,
        ts_code=thesis.ts_code,
        state=ActionLabel.ENTER_OBSERVATION,
        entry_date=trade_date,
        entry_reason=thesis.thesis,
        invalidation_conditions=list(thesis.invalidation_conditions),
    )


def _build_manual_missing_evidence_thesis(
    ts_code: str,
    name: str,
    manual_reason: str,
    trade_date: date,
) -> FocusEntryThesis:
    reason = manual_reason.strip() or "未提供人工关注理由"
    action = _manual_insufficient_action(reason)
    return FocusEntryThesis(
        evidence_id=f"{trade_date.isoformat()}-{ts_code}-manual",
        trade_date=trade_date,
        ts_code=ts_code,
        name=name,
        source=FocusSource.MANUAL,
        thesis=(
            f"人工关注理由：{reason}；当前缺少 Strategy V2 证据，"
            "不能形成正向观察结论。"
        ),
        action=action,
        expected_upside_pct=None,
        expected_downside_pct=None,
        risk_reward=None,
        required_confirmation=list(action.required_confirmation),
        invalidation_conditions=list(action.invalidation_conditions),
        supporting_evidence_ids=[],
        validation_result="证据不足",
        risk_notes=[
            "证据不足：没有可匹配的 Strategy V2 快照，不能验证人工关注理由。",
            "人工来源需要等待行情、风险和公司证据补齐后再判断。",
        ],
    )


def _manual_insufficient_action(manual_reason: str) -> ActionRecommendation:
    return ActionRecommendation(
        decision=ActionDecision.WAIT_FOR_CONFIRMATION,
        position_min_pct=0.0,
        position_max_pct=0.0,
        reasoning=[
            "人工关注理由尚无 Strategy V2 证据验证。",
            f"人工备注：{manual_reason}",
        ],
        required_confirmation=[
            "补齐 Strategy V2 证据快照",
            "确认风险收益比、硬风险和关键失效条件",
        ],
        invalidation_conditions=[
            "证据补齐后仍无法支持人工关注理由",
            "出现官方硬风险或流动性约束",
        ],
        risk_if_wrong="证据不足时若直接正向解读，可能把外部推荐或传闻误当成可执行依据。",
        staging_plan=[
            "仅保留人工观察标签，不新增系统背书。",
            "证据补齐前不提高仓位暴露。",
        ],
    )


def _removal_confirmation_action(
    snapshot: StrategyEvidenceSnapshot,
) -> ActionRecommendation:
    return ActionRecommendation(
        decision=ActionDecision.CONFIRM_REMOVAL,
        position_min_pct=0.0,
        position_max_pct=0.0,
        reasoning=[
            "风险或反证已主导，重点观察资格需要重新确认。",
            *list(snapshot.action.reasoning),
        ],
        required_confirmation=[
            "确认硬风险或关键反证是否仍存在",
            "若反证无法解除，确认是否移出重点观察",
        ],
        invalidation_conditions=list(snapshot.action.invalidation_conditions),
        risk_if_wrong=snapshot.action.risk_if_wrong,
        staging_plan=[
            "不新增仓位暴露，先确认是否移出重点观察。",
            "若风险解除，再按 Strategy V2 重新进入观察流程。",
        ],
        holding_adjustment=snapshot.action.holding_adjustment,
    )


def _fallback_focus_progress(
    snapshot: StrategyEvidenceSnapshot,
    focus_state: FocusState | None,
) -> str:
    if snapshot.data_insufficient:
        return snapshot.data_insufficient_reason or "数据不足，不形成今日观察结论。"
    entry_date = focus_state.entry_date if focus_state else snapshot.trade_date
    return (
        f"短期信号：{snapshot.action.decision.value}；"
        f"中期 thesis：{snapshot.thesis}；"
        f"入选日期：{entry_date.isoformat()}。"
    )


def _manual_entry_parts(entry: Any) -> tuple[str, str, str | None]:
    if isinstance(entry, dict):
        ts_code = str(entry.get("ts_code") or entry.get("code") or "").strip()
        reason = str(entry.get("reason") or entry.get("manual_reason") or "").strip()
        name = entry.get("name")
        return ts_code, reason, str(name).strip() if name else None

    if isinstance(entry, (tuple, list)):
        ts_code = str(entry[0]).strip() if len(entry) >= 1 else ""
        reason = str(entry[1]).strip() if len(entry) >= 2 else ""
        name = str(entry[2]).strip() if len(entry) >= 3 else None
        return ts_code, reason, name

    return str(entry).strip(), "", None


def _manual_entries_by_code(manual_entries: list[Any]) -> dict[str, tuple[str, str | None]]:
    entries: dict[str, tuple[str, str | None]] = {}
    for entry in manual_entries:
        ts_code, reason, name = _manual_entry_parts(entry)
        if ts_code:
            entries[ts_code] = (reason, name)
    return entries


def _dedupe(items: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for item in items:
        normalized = item.strip()
        if normalized and normalized not in seen:
            output.append(normalized)
            seen.add(normalized)
    return output
