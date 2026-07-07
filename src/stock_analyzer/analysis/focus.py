from __future__ import annotations

from stock_analyzer.domain.models import ActionLabel, FocusState, Recommendation


def update_focus_watchlist(
    existing: list[FocusState],
    recommendations: list[Recommendation],
    invalidated_codes: set[str],
    enter_threshold: float = 80.0,
) -> list[FocusState]:
    by_code = {item.ts_code: item for item in existing}
    output: list[FocusState] = []

    for old in existing:
        if old.ts_code in invalidated_codes:
            output.append(
                old.model_copy(
                    update={
                        "state": ActionLabel.EXIT_OBSERVATION,
                        "exit_reason": "触发预设失效条件",
                    }
                )
            )
        else:
            output.append(old.model_copy(update={"state": ActionLabel.CONTINUE_OBSERVATION}))

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
