from __future__ import annotations

import json
from datetime import date
from html import escape
from pathlib import Path
from typing import Optional

try:
    from jinja2 import Environment, FileSystemLoader, select_autoescape
except ModuleNotFoundError:  # pragma: no cover - exercised when local deps are absent.
    Environment = None
    FileSystemLoader = None
    select_autoescape = None
from stock_analyzer.data.models import DataStatus, DataUnavailableNotice
from stock_analyzer.domain.models import (
    EvidencePackage,
    FocusDailyUpdate,
    FocusEntryThesis,
    FocusState,
    OperationalDailyStatus,
    Recommendation,
    RecommendationCard,
    StrategyEvidenceSnapshot,
)


FIXTURE_REPORT_WARNING = (
    "Fixture/sample report: generated from local sample data; not production data."
)
STRATEGY_MODULE_LABELS = {
    "company_business": "公司业务",
    "fundamentals_valuation": "基本面与估值",
    "market_board": "市场与板块",
    "trend_volume": "趋势与成交",
    "events_catalysts": "事件与催化",
    "risk_counter": "风险与反证",
}


def render_reports(
    output_dir: Path,
    recommendations: list[Recommendation],
    focus_states: list[FocusState],
    evidence_packages: Optional[list[EvidencePackage]] = None,
    trade_date: Optional[date] = None,
    fixture_mode: bool = False,
    data_status: Optional[DataStatus] = None,
    source_versions: Optional[dict[str, str]] = None,
    operational_status: Optional[OperationalDailyStatus] = None,
    strategy_v2_cards: Optional[list[RecommendationCard]] = None,
    strategy_v2_snapshots: Optional[list[StrategyEvidenceSnapshot]] = None,
    focus_entry_theses: Optional[list[FocusEntryThesis]] = None,
    focus_daily_updates: Optional[list[FocusDailyUpdate]] = None,
    formal_narrative: Optional[dict[str, str]] = None,
) -> None:
    strategy_v2_cards = strategy_v2_cards or []
    strategy_v2_snapshots = strategy_v2_snapshots or []
    focus_entry_theses = focus_entry_theses or []
    focus_daily_updates = focus_daily_updates or []
    formal_narrative = formal_narrative or {}
    report_date = _resolve_trade_date(
        trade_date,
        recommendations,
        focus_states,
        strategy_v2_cards,
        strategy_v2_snapshots,
        focus_entry_theses,
        focus_daily_updates,
        operational_status,
    )
    evidence_packages = evidence_packages or []
    source_versions = source_versions or {}
    if not fixture_mode:
        _require_matching_evidence(recommendations, evidence_packages)
    recommendation_details = _recommendation_details(
        recommendations,
        report_date,
        evidence_packages,
        stock_page_prefix=f"daily/{report_date.isoformat()}/stocks",
    )
    daily_recommendation_details = _recommendation_details(
        recommendations,
        report_date,
        evidence_packages,
        stock_page_prefix="stocks",
    )
    strategy_v2_card_views = _strategy_v2_card_views(
        strategy_v2_cards,
        stock_page_prefix=f"daily/{report_date.isoformat()}/stocks",
    )
    daily_strategy_v2_card_views = _strategy_v2_card_views(
        strategy_v2_cards,
        stock_page_prefix="stocks",
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    data_dir = output_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "trade_date": report_date.isoformat(),
        "report_mode": "fixture" if fixture_mode else "production",
        "is_fixture": fixture_mode,
        "warning": FIXTURE_REPORT_WARNING if fixture_mode else None,
        "data_status": data_status.value if data_status else None,
        "source_versions": source_versions,
        "operational_status": (
            operational_status.model_dump(mode="json") if operational_status else None
        ),
        "recommendations": [
            item.model_dump(mode="json") for item in recommendations
        ],
        "focus_states": [item.model_dump(mode="json") for item in focus_states],
        "evidence_packages": [
            item.model_dump(mode="json") for item in evidence_packages
        ],
        "recommendation_details": recommendation_details,
        "recommendation_cards": [
            item.model_dump(mode="json") for item in strategy_v2_cards
        ],
        "strategy_snapshots": [
            item.model_dump(mode="json") for item in strategy_v2_snapshots
        ],
        "focus_entry_theses": [
            item.model_dump(mode="json") for item in focus_entry_theses
        ],
        "focus_daily_updates": [
            item.model_dump(mode="json") for item in focus_daily_updates
        ],
        "formal_narrative": dict(sorted(formal_narrative.items())),
    }
    latest_path = data_dir / "latest.json"
    latest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    index_html = _render_index_html(
        trade_date=report_date,
        recommendation_details=recommendation_details,
        focus_states=focus_states,
        strategy_v2_cards=strategy_v2_card_views,
        focus_entry_theses=focus_entry_theses,
        focus_daily_updates=focus_daily_updates,
        is_fixture=fixture_mode,
        fixture_warning=FIXTURE_REPORT_WARNING,
        data_unavailable_notice=None,
        operational_status=operational_status,
        report_mode=payload["report_mode"],
    )
    (output_dir / "index.html").write_text(index_html, encoding="utf-8")

    daily_dir = output_dir / "daily" / report_date.isoformat()
    daily_dir.mkdir(parents=True, exist_ok=True)
    daily_index_html = _render_index_html(
        trade_date=report_date,
        recommendation_details=daily_recommendation_details,
        focus_states=focus_states,
        strategy_v2_cards=daily_strategy_v2_card_views,
        focus_entry_theses=focus_entry_theses,
        focus_daily_updates=focus_daily_updates,
        is_fixture=fixture_mode,
        fixture_warning=FIXTURE_REPORT_WARNING,
        data_unavailable_notice=None,
        operational_status=operational_status,
        report_mode=payload["report_mode"],
    )
    (daily_dir / "index.html").write_text(daily_index_html, encoding="utf-8")

    stocks_dir = daily_dir / "stocks"
    stocks_dir.mkdir(parents=True, exist_ok=True)
    strategy_codes = {card.ts_code for card in strategy_v2_cards}
    for recommendation, detail in zip(recommendations, recommendation_details):
        if recommendation.ts_code in strategy_codes:
            continue
        stock_html = _render_stock_html(
            stock_name=f"{recommendation.name} {recommendation.ts_code}",
            conclusion=_stock_conclusion(recommendation),
            recommendation=recommendation,
            detail=detail,
            focus_state=_focus_state_for(recommendation.ts_code, focus_states),
            strategy_v2_card=None,
            strategy_v2_snapshot=None,
            is_fixture=fixture_mode,
            fixture_warning=FIXTURE_REPORT_WARNING,
        )
        (stocks_dir / f"{recommendation.ts_code}.html").write_text(
            stock_html,
            encoding="utf-8",
        )
    for card in strategy_v2_cards:
        snapshot = _strategy_v2_snapshot_for_card(card, strategy_v2_snapshots)
        stock_html = _render_stock_html(
            stock_name=f"{card.name} {card.ts_code}",
            conclusion=_strategy_v2_conclusion(card),
            recommendation=None,
            detail=None,
            focus_state=_focus_state_for(card.ts_code, focus_states),
            strategy_v2_card=_strategy_v2_card_view(
                card,
                stock_page=f"{card.ts_code}.html",
            ),
            strategy_v2_snapshot=snapshot,
            is_fixture=fixture_mode,
            fixture_warning=FIXTURE_REPORT_WARNING,
        )
        (stocks_dir / f"{card.ts_code}.html").write_text(
            stock_html,
            encoding="utf-8",
        )


def render_data_insufficient_report(
    output_dir: Path,
    operational_status: OperationalDailyStatus,
    source_versions: Optional[dict[str, str]] = None,
) -> None:
    notice = DataUnavailableNotice(
        trade_date=operational_status.trade_date,
        reason=operational_status.message,
    )
    _render_empty_operational_notice(
        output_dir=output_dir,
        notice=notice,
        report_mode="data_insufficient",
        warning="当日实时数据不足，不生成新的股票分析结论。",
        operational_status=operational_status,
        source_versions=source_versions or {},
    )


def render_strategy_v2_data_insufficient_report(
    output_dir: Path,
    operational_status: OperationalDailyStatus,
    source_versions: Optional[dict[str, str]] = None,
) -> None:
    render_data_insufficient_report(
        output_dir,
        operational_status,
        source_versions=source_versions,
    )


def render_data_unavailable_notice(
    output_dir: Path,
    notice: DataUnavailableNotice,
) -> None:
    _render_empty_operational_notice(
        output_dir=output_dir,
        notice=notice,
        report_mode="data_unavailable",
        warning="当日实时数据不可用，不生成新的股票分析结论。",
        operational_status=None,
        source_versions={},
    )


def _render_empty_operational_notice(
    output_dir: Path,
    notice: DataUnavailableNotice,
    report_mode: str,
    warning: str,
    operational_status: Optional[OperationalDailyStatus],
    source_versions: dict[str, str],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    data_dir = output_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "trade_date": notice.trade_date.isoformat(),
        "report_mode": report_mode,
        "is_fixture": False,
        "warning": warning,
        "reason": notice.reason,
        "last_successful_trade_date": (
            notice.last_successful_trade_date.isoformat()
            if notice.last_successful_trade_date
            else None
        ),
        "source_versions": source_versions,
        "operational_status": (
            operational_status.model_dump(mode="json") if operational_status else None
        ),
        "recommendations": [],
        "focus_states": [],
        "evidence_packages": [],
        "recommendation_details": [],
        "recommendation_cards": [],
        "strategy_snapshots": [],
        "focus_entry_theses": [],
        "focus_daily_updates": [],
    }
    (data_dir / "latest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    html = _render_index_html(
        trade_date=notice.trade_date,
        recommendation_details=[],
        focus_states=[],
        strategy_v2_cards=[],
        focus_entry_theses=[],
        focus_daily_updates=[],
        is_fixture=False,
        fixture_warning=None,
        data_unavailable_notice=notice,
        operational_status=operational_status,
        report_mode=report_mode,
    )
    (output_dir / "index.html").write_text(html, encoding="utf-8")

    daily_dir = output_dir / "daily" / notice.trade_date.isoformat()
    daily_dir.mkdir(parents=True, exist_ok=True)
    (daily_dir / "index.html").write_text(html, encoding="utf-8")


def _focus_state_for(
    ts_code: str,
    focus_states: list[FocusState],
) -> Optional[FocusState]:
    for state in focus_states:
        if state.ts_code == ts_code:
            return state
    return None


def _render_index_html(
    trade_date: date,
    recommendation_details: list[dict],
    focus_states: list[FocusState],
    strategy_v2_cards: list[dict],
    focus_entry_theses: list[FocusEntryThesis],
    focus_daily_updates: list[FocusDailyUpdate],
    is_fixture: bool,
    fixture_warning: Optional[str],
    data_unavailable_notice: Optional[DataUnavailableNotice],
    operational_status: Optional[OperationalDailyStatus],
    report_mode: str,
) -> str:
    if Environment is not None:
        return _template_env().get_template("index.html.j2").render(
            trade_date=trade_date,
            recommendation_details=recommendation_details,
            focus_states=focus_states,
            strategy_v2_cards=strategy_v2_cards,
            focus_entry_theses=focus_entry_theses,
            focus_daily_updates=focus_daily_updates,
            is_fixture=is_fixture,
            fixture_warning=fixture_warning,
            data_unavailable_notice=data_unavailable_notice,
            operational_status=operational_status,
            report_mode=report_mode,
        )
    return _render_index_html_without_jinja(
        trade_date,
        recommendation_details,
        focus_states,
        strategy_v2_cards,
        focus_entry_theses,
        focus_daily_updates,
        is_fixture,
        fixture_warning,
        data_unavailable_notice,
        operational_status,
        report_mode,
    )


def _render_stock_html(
    stock_name: str,
    conclusion: str,
    recommendation: Optional[Recommendation],
    detail: Optional[dict],
    focus_state: Optional[FocusState],
    strategy_v2_card: Optional[dict],
    strategy_v2_snapshot: Optional[StrategyEvidenceSnapshot],
    is_fixture: bool,
    fixture_warning: str,
) -> str:
    if Environment is not None:
        return _template_env().get_template("stock.html.j2").render(
            stock_name=stock_name,
            conclusion=conclusion,
            recommendation=recommendation,
            detail=detail,
            focus_state=focus_state,
            strategy_v2_card=strategy_v2_card,
            strategy_v2_snapshot=strategy_v2_snapshot,
            strategy_module_labels=STRATEGY_MODULE_LABELS,
            is_fixture=is_fixture,
            fixture_warning=fixture_warning,
        )
    return _render_stock_html_without_jinja(
        stock_name,
        conclusion,
        recommendation,
        detail,
        focus_state,
        strategy_v2_card,
        strategy_v2_snapshot,
        is_fixture,
        fixture_warning,
    )


def _template_env() -> Environment:
    template_dir = Path(__file__).parent / "templates"
    env = Environment(
        loader=FileSystemLoader(template_dir),
        autoescape=select_autoescape(["html"]),
    )
    env.filters["strategy_text"] = _strategy_display_text
    return env


def _render_index_html_without_jinja(
    trade_date: date,
    recommendation_details: list[dict],
    focus_states: list[FocusState],
    strategy_v2_cards: list[dict],
    focus_entry_theses: list[FocusEntryThesis],
    focus_daily_updates: list[FocusDailyUpdate],
    is_fixture: bool,
    fixture_warning: Optional[str],
    data_unavailable_notice: Optional[DataUnavailableNotice],
    operational_status: Optional[OperationalDailyStatus],
    report_mode: str,
) -> str:
    if data_unavailable_notice:
        is_data_insufficient = report_mode == "data_insufficient"
        notice_label = "数据不足" if is_data_insufficient else "数据不可用"
        lines = [
            f"<h1>{_html(trade_date.isoformat())} {notice_label}</h1>",
            '<section role="alert">',
            f"<h2>当日实时{notice_label}</h2>",
            "<p>不生成新的股票分析结论。</p>",
            f"<p>原因：{_html(data_unavailable_notice.reason)}</p>",
        ]
        if operational_status and operational_status.blocking_missing_fields:
            lines.append("<h3>阻塞缺失字段</h3>")
            _append_html_list(lines, operational_status.blocking_missing_fields)
        if operational_status and operational_status.data_recovery_attempts:
            lines.append("<h3>数据恢复尝试</h3>")
            lines.append("<ul>")
            for attempt in operational_status.data_recovery_attempts:
                parts = [
                    attempt.family,
                    attempt.source_name,
                    attempt.status,
                    attempt.message,
                ]
                lines.append(
                    "<li>"
                    + _html(" / ".join(str(part) for part in parts if part))
                    + "</li>"
                )
            lines.append("</ul>")
        if is_data_insufficient:
            lines.extend(
                [
                    "<h3>影响</h3>",
                    "<p>推荐与重点关注不能形成完整结论；等待缺失字段恢复后重新生成报告。</p>",
                ]
            )
        if data_unavailable_notice.last_successful_trade_date:
            lines.append(
                "<p>最近一次成功数据日期："
                f"{_html(data_unavailable_notice.last_successful_trade_date.isoformat())}"
                "</p>"
            )
        lines.append("</section>")
        return _html_page(f"{notice_label}通知", lines)

    lines = ["<h1>股票观察报告</h1>"]
    if is_fixture:
        lines.extend(
            [
                '<section role="alert">',
                "<h2>Fixture/sample report</h2>",
                f"<p>{_html(fixture_warning)}</p>",
                "</section>",
            ]
        )

    lines.extend(["<section>", "<h2>今日推荐</h2>"])
    if strategy_v2_cards:
        for item in strategy_v2_cards:
            lines.extend(
                [
                    "<article>",
                    '<h3><a href="'
                    f'{_html(item["stock_page"])}">'
                    f'{_html(item["name"])} {_html(item["ts_code"])}</a></h3>',
                    f'<p>分层：{_html(item["display_rank_bucket"])}</p>',
                    f'<p>操作建议：{_html(item["action"])}</p>',
                    "<p>仓位："
                    f'{_html(item["position_min_pct"])}%-'
                    f'{_html(item["position_max_pct"])}%</p>',
                    "<h4>发生了什么</h4>",
                    f'<p>{_html(item["what_happened"])}</p>',
                    "<h4>为什么可能发生</h4>",
                    f'<p>{_html(item["why_it_may_have_happened"])}</p>',
                    "<h4>可能意味着什么</h4>",
                    f'<p>{_html(item["what_it_may_mean"])}</p>',
                    "<h4>主要风险</h4>",
                    f'<p>{_html(item["main_risk"])}</p>',
                    "<h4>重点关注进度</h4>",
                    f'<p>{_html(item["focus_entry_progress"] or "待观察")}</p>',
                    "<h4>进入重点前需要</h4>",
                ]
            )
            _append_html_list(lines, item["needed_before_focus_entry"])
            lines.append("<h4>行动依据</h4>")
            _append_html_list(lines, item["action_reasoning"])
            lines.append("<h4>确认条件</h4>")
            _append_html_list(lines, item["required_confirmation"])
            lines.append("<h4>失效条件</h4>")
            _append_html_list(lines, item["invalidation_conditions"])
            lines.extend(
                [
                    "<h4>看错风险</h4>",
                    f'<p>{_html(item["risk_if_wrong"])}</p>',
                    "</article>",
                ]
            )
    elif recommendation_details:
        for item in recommendation_details:
            evidence = item["evidence"]
            lines.extend(
                [
                    "<article>",
                    '<h3><a href="'
                    f'{_html(item["stock_page"])}">'
                    f'{_html(item["name"])} {_html(item["ts_code"])}</a></h3>',
                    f'<p>{_html(item["action"])}，评分 {_html(item["score"])}</p>',
                    "<h4>发生了什么</h4>",
                    f'<p>{_html(item["what_happened"])}</p>',
                    "<h4>支撑证据</h4>",
                ]
            )
            _append_html_list(lines, evidence["support"])
            lines.append("<h4>反证与风险</h4>")
            _append_html_list(lines, evidence["counter_evidence"])
            lines.append("<h4>确认信号</h4>")
            _append_html_list(lines, evidence["confirmation_signals"])
            lines.append("<h4>失效信号</h4>")
            _append_html_list(lines, evidence["invalidation_signals"])
            lines.append("<h4>观察计划</h4>")
            _append_html_list(lines, item["observation_plan"])
            lines.extend(
                [
                    "<h4>证据与规则引用</h4>",
                    f'<p>证据：{_html(evidence["evidence_id"] or "未记录")}</p>',
                    "<p>规则："
                    f'{_html("；".join(evidence["rule_references"]) or "未匹配规则")}'
                    "</p>",
                    "<h4>数据可信度</h4>",
                    f'<p>{_html(evidence["data_credibility"])}</p>',
                    "</article>",
                ]
            )
    else:
        lines.append("<p>今日没有符合标准的推荐。</p>")
    lines.append("</section>")

    lines.extend(["<section>", "<h2>重点关注</h2>"])
    if focus_entry_theses or focus_daily_updates:
        for item in focus_entry_theses:
            lines.extend(
                [
                    "<article>",
                    f"<h3>{_html(item.name)} {_html(item.ts_code)}</h3>",
                    f"<p>来源：{_html(item.source.value)}</p>",
                    f"<p>状态：{_html(item.validation_result)}</p>",
                    f"<p>论点：{_html(_strategy_display_text(item.thesis))}</p>",
                ]
            )
            _append_strategy_action_without_jinja(lines, item.action)
            lines.append("<h4>要求确认</h4>")
            _append_html_list(
                lines,
                [_strategy_display_text(x) for x in item.required_confirmation],
            )
            lines.append("<h4>失效条件</h4>")
            _append_html_list(
                lines,
                [_strategy_display_text(x) for x in item.invalidation_conditions],
            )
            lines.append("<h4>风险备注</h4>")
            _append_html_list(
                lines,
                [_strategy_display_text(x) for x in item.risk_notes],
            )
            lines.append("</article>")
        for item in focus_daily_updates:
            lines.extend(
                [
                    "<article>",
                    f"<h3>{_html(item.name)} {_html(item.ts_code)}</h3>",
                    "<p>来源：重点关注更新</p>",
                    "<p>状态："
                    f"{_html(_strategy_display_text(item.focus_entry_progress))}"
                    "</p>",
                    f"<p>论点：{_html(_strategy_display_text(item.thesis))}</p>",
                ]
            )
            _append_strategy_action_without_jinja(lines, item.action)
            lines.append("<h4>要求确认</h4>")
            _append_html_list(
                lines,
                [_strategy_display_text(x) for x in item.required_confirmation],
            )
            lines.append("<h4>失效条件</h4>")
            _append_html_list(
                lines,
                [_strategy_display_text(x) for x in item.invalidation_conditions],
            )
            if item.data_insufficient_reason:
                lines.append(
                    "<p>数据不足："
                    f"{_html(_strategy_display_text(item.data_insufficient_reason))}"
                    "</p>"
                )
            lines.append("</article>")
    elif focus_states:
        for item in focus_states:
            lines.extend(
                [
                    "<article>",
                    f"<h3>{_html(item.ts_code)}</h3>",
                    f"<p>{_html(item.state.value)}</p>",
                    "</article>",
                ]
            )
    else:
        lines.append("<p>当前没有重点关注股票。</p>")
    lines.append("</section>")
    return _html_page("股票观察报告", lines)


def _render_stock_html_without_jinja(
    stock_name: str,
    conclusion: str,
    recommendation: Optional[Recommendation],
    detail: Optional[dict],
    focus_state: Optional[FocusState],
    strategy_v2_card: Optional[dict],
    strategy_v2_snapshot: Optional[StrategyEvidenceSnapshot],
    is_fixture: bool,
    fixture_warning: str,
) -> str:
    del recommendation, focus_state

    lines = [f"<h1>{_html(stock_name)}</h1>"]
    if is_fixture:
        lines.extend(
            [
                '<section role="alert">',
                "<h2>Fixture/sample report</h2>",
                f"<p>{_html(fixture_warning)}</p>",
                "</section>",
            ]
        )
    lines.append(f"<p>{_html(conclusion)}</p>")
    if strategy_v2_card:
        lines.extend(
            [
                "<section>",
                "<h2>操作建议</h2>",
                f'<p>{_html(strategy_v2_card["action"])}</p>',
                "<p>仓位："
                f'{_html(strategy_v2_card["position_min_pct"])}%-'
                f'{_html(strategy_v2_card["position_max_pct"])}%</p>',
                "<h3>理由</h3>",
            ]
        )
        _append_html_list(lines, strategy_v2_card["action_reasoning"])
        lines.append("<h3>确认条件</h3>")
        _append_html_list(lines, strategy_v2_card["required_confirmation"])
        lines.append("<h3>失效条件</h3>")
        _append_html_list(lines, strategy_v2_card["invalidation_conditions"])
        lines.extend(
            [
                "<h3>看错风险</h3>",
                f'<p>{_html(strategy_v2_card["risk_if_wrong"])}</p>',
                "</section>",
                "<section>",
                "<h2>六模块证据</h2>",
            ]
        )
        if strategy_v2_snapshot:
            for module in strategy_v2_snapshot.modules:
                module_value = module.module.value
                lines.extend(
                    [
                        "<article>",
                        "<h3>"
                        f"{_html(STRATEGY_MODULE_LABELS.get(module_value, module_value))}"
                        "</h3>",
                        f"<p>{_html(_strategy_display_text(module.conclusion))}</p>",
                    ]
                )
                if module.support:
                    lines.append("<h4>支持</h4>")
                    _append_html_list(
                        lines,
                        [
                            _strategy_display_text(atom.headline)
                            for atom in module.support
                        ],
                    )
                if module.counter:
                    lines.append("<h4>反证</h4>")
                    _append_html_list(
                        lines,
                        [
                            _strategy_display_text(atom.headline)
                            for atom in module.counter
                        ],
                    )
                lines.append("</article>")
        lines.append("</section>")
        return _html_page(f"{stock_name} 股票报告", lines)

    if detail is None:
        return _html_page(f"{stock_name} 股票报告", lines)

    lines.extend(
        [
            "<section>",
            "<h2>发生了什么</h2>",
            f'<p>{_html(detail["what_happened"])}</p>',
            "</section>",
            "<section>",
            "<h2>支撑证据</h2>",
        ]
    )
    _append_html_list(lines, detail["evidence"]["support"])
    lines.extend(["</section>", "<section>", "<h2>反证与风险</h2>"])
    _append_html_list(lines, detail["evidence"]["counter_evidence"])
    lines.extend(["</section>", "<section>", "<h2>确认信号</h2>"])
    _append_html_list(lines, detail["evidence"]["confirmation_signals"])
    lines.extend(["</section>", "<section>", "<h2>失效信号</h2>"])
    _append_html_list(lines, detail["evidence"]["invalidation_signals"])
    lines.extend(["</section>", "<section>", "<h2>观察计划</h2>"])
    _append_html_list(lines, detail["observation_plan"])
    lines.extend(
        [
            "</section>",
            "<section>",
            "<h2>证据与规则引用</h2>",
            f'<p>证据：{_html(detail["evidence"]["evidence_id"] or "未记录")}</p>',
            "<p>规则："
            f'{_html("；".join(detail["evidence"]["rule_references"]) or "未匹配规则")}'
            "</p>",
            "</section>",
            "<section>",
            "<h2>数据可信度</h2>",
            f'<p>{_html(detail["evidence"]["data_credibility"])}</p>',
            "</section>",
        ]
    )
    return _html_page(f"{stock_name} 股票报告", lines)


def _append_html_list(lines: list[str], items: list[str]) -> None:
    lines.append("<ul>")
    for item in items:
        lines.append(f"<li>{_html(item)}</li>")
    lines.append("</ul>")


def _html_page(title: str, body_lines: list[str]) -> str:
    lines = [
        "<!doctype html>",
        '<html lang="zh-CN">',
        "<head>",
        '  <meta charset="utf-8">',
        '  <meta name="viewport" content="width=device-width, initial-scale=1">',
        f"  <title>{_html(title)}</title>",
        "</head>",
        "<body>",
        "  <main>",
    ]
    lines.extend(f"    {line}" for line in body_lines)
    lines.extend(["  </main>", "</body>", "</html>", ""])
    return "\n".join(lines)


def _html(value: object) -> str:
    return escape("" if value is None else str(value), quote=True)


def _strategy_display_text(value: object) -> str:
    text = "" if value is None else str(value)
    return text.replace("评分", "指标").replace("score", "metric")


def _strategy_v2_card_views(
    cards: list[RecommendationCard],
    stock_page_prefix: str,
) -> list[dict]:
    return [
        _strategy_v2_card_view(
            card,
            stock_page=f"{stock_page_prefix}/{card.ts_code}.html",
        )
        for card in cards
    ]


def _strategy_v2_card_view(
    card: RecommendationCard,
    stock_page: str,
) -> dict:
    payload = card.model_dump(mode="json")
    for key in (
        "action",
        "what_happened",
        "why_it_may_have_happened",
        "what_it_may_mean",
        "main_risk",
        "focus_entry_progress",
        "risk_if_wrong",
        "holding_adjustment",
    ):
        payload[key] = _strategy_display_text(payload.get(key))
    for key in (
        "action_reasoning",
        "required_confirmation",
        "invalidation_conditions",
        "staging_plan",
        "needed_before_focus_entry",
    ):
        payload[key] = [
            _strategy_display_text(item) for item in payload.get(key, [])
        ]
    payload["stock_page"] = stock_page
    return payload


def _strategy_v2_snapshot_for_card(
    card: RecommendationCard,
    snapshots: list[StrategyEvidenceSnapshot],
) -> Optional[StrategyEvidenceSnapshot]:
    for snapshot in snapshots:
        if snapshot.evidence_id == card.evidence_id:
            return snapshot
    for snapshot in snapshots:
        if snapshot.ts_code == card.ts_code:
            return snapshot
    return None


def _strategy_v2_conclusion(card: RecommendationCard) -> str:
    return (
        f"操作建议：{_strategy_display_text(card.action)}，"
        f"仓位 {card.position_min_pct}%-{card.position_max_pct}%。"
        f"{_strategy_display_text(card.what_it_may_mean)}"
    )


def _append_strategy_action_without_jinja(lines: list[str], action) -> None:
    lines.extend(
        [
            f"<p>操作建议：{_html(_strategy_display_text(action.decision.value))}</p>",
            "<p>仓位："
            f"{_html(action.position_min_pct)}%-{_html(action.position_max_pct)}%"
            "</p>",
            "<h4>理由</h4>",
        ]
    )
    _append_html_list(lines, [_strategy_display_text(x) for x in action.reasoning])
    lines.append("<h4>必要条件</h4>")
    _append_html_list(
        lines,
        [_strategy_display_text(x) for x in action.required_confirmation],
    )
    lines.append("<h4>失效点</h4>")
    _append_html_list(
        lines,
        [_strategy_display_text(x) for x in action.invalidation_conditions],
    )
    lines.extend(
        [
            "<h4>看错风险</h4>",
            f"<p>{_html(_strategy_display_text(action.risk_if_wrong))}</p>",
        ]
    )
    if action.holding_adjustment:
        lines.append(
            f"<p>持仓调整：{_html(_strategy_display_text(action.holding_adjustment))}</p>"
        )


def _resolve_trade_date(
    trade_date: Optional[date],
    recommendations: list[Recommendation],
    focus_states: list[FocusState],
    strategy_v2_cards: Optional[list[RecommendationCard]] = None,
    strategy_v2_snapshots: Optional[list[StrategyEvidenceSnapshot]] = None,
    focus_entry_theses: Optional[list[FocusEntryThesis]] = None,
    focus_daily_updates: Optional[list[FocusDailyUpdate]] = None,
    operational_status: Optional[OperationalDailyStatus] = None,
) -> date:
    if trade_date is not None:
        return trade_date
    if recommendations:
        return recommendations[0].trade_date
    if focus_states:
        return focus_states[0].trade_date
    for items in (
        strategy_v2_cards or [],
        strategy_v2_snapshots or [],
        focus_entry_theses or [],
        focus_daily_updates or [],
    ):
        if items:
            return items[0].trade_date
    if operational_status is not None:
        return operational_status.trade_date
    return date.today()


def _stock_conclusion(recommendation: Recommendation) -> str:
    reasons = "；".join(recommendation.reasons)
    risks = "；".join(recommendation.risks)
    return (
        f"{recommendation.action.value}，评分 {recommendation.score}。"
        f"主要依据：{reasons}。主要风险：{risks}。"
    )


def _recommendation_details(
    recommendations: list[Recommendation],
    report_date: date,
    evidence_packages: list[EvidencePackage],
    stock_page_prefix: str,
) -> list[dict]:
    return [
        _recommendation_detail(
            recommendation,
            report_date,
            evidence_packages,
            stock_page=f"{stock_page_prefix}/{recommendation.ts_code}.html",
        )
        for recommendation in recommendations
    ]


def _require_matching_evidence(
    recommendations: list[Recommendation],
    evidence_packages: list[EvidencePackage],
) -> None:
    evidence_by_id = {package.evidence_id: package for package in evidence_packages}
    missing = []
    mismatched = []
    for recommendation in recommendations:
        evidence_id = recommendation.evidence_id
        if not evidence_id:
            missing.append(f"{recommendation.ts_code} (missing evidence_id)")
            continue
        package = evidence_by_id.get(evidence_id)
        if package is None:
            missing.append(f"{recommendation.ts_code} ({evidence_id})")
            continue
        if package.ts_code != recommendation.ts_code:
            mismatched.append(
                f"{recommendation.ts_code} ({evidence_id} belongs to {package.ts_code})"
            )
    if missing or mismatched:
        details = "; ".join(
            part
            for part in (
                _format_evidence_validation_detail(
                    "missing matching evidence package",
                    missing,
                ),
                _format_evidence_validation_detail(
                    "mismatched evidence package",
                    mismatched,
                ),
            )
            if part
        )
        raise ValueError(
            "Production reports require a matching evidence package for every "
            f"recommendation: {details}."
        )


def _format_evidence_validation_detail(label: str, refs: list[str]) -> str:
    if not refs:
        return ""
    return f"{label}: {', '.join(refs)}"


def _recommendation_detail(
    recommendation: Recommendation,
    report_date: date,
    evidence_packages: list[EvidencePackage],
    stock_page: str,
) -> dict:
    evidence = _evidence_for(recommendation, evidence_packages)
    support = evidence.support if evidence else list(recommendation.reasons)
    counter_evidence = evidence.counter_evidence if evidence else list(recommendation.risks)
    confirmation_signals = (
        evidence.expected_confirmation_path
        if evidence
        else ["等待趋势、成交量和反证强度在后续交易日继续确认"]
    )
    invalidation_signals = (
        evidence.invalidation_conditions
        if evidence
        else list(recommendation.risks)
    )
    evidence_id = evidence.evidence_id if evidence else recommendation.evidence_id
    rule_references = evidence.matched_rules if evidence else []
    source_versions = evidence.source_versions if evidence else {}
    data_credibility = evidence.confidence_level if evidence else "unknown"
    what_happened = (
        evidence.thesis
        if evidence
        else f"{recommendation.name}触发观察评分 {recommendation.score}"
    )
    return {
        "trade_date": report_date.isoformat(),
        "ts_code": recommendation.ts_code,
        "name": recommendation.name,
        "action": recommendation.action.value,
        "score": recommendation.score,
        "stock_page": stock_page,
        "what_happened": what_happened,
        "why_observe": list(recommendation.reasons),
        "biggest_risk": recommendation.risks[0] if recommendation.risks else "暂无明确反证",
        "observation_plan": [
            "跟踪 5/20/40 个交易日检查点",
            "确认信号增强时继续观察",
            "失效信号触发时降级或剔除观察",
        ],
        "evidence": {
            "evidence_id": evidence_id,
            "support": list(support),
            "counter_evidence": list(counter_evidence),
            "confirmation_signals": list(confirmation_signals),
            "invalidation_signals": list(invalidation_signals),
            "rule_references": list(rule_references),
            "source_versions": dict(source_versions),
            "data_credibility": data_credibility,
        },
    }


def _evidence_for(
    recommendation: Recommendation,
    evidence_packages: list[EvidencePackage],
) -> Optional[EvidencePackage]:
    for package in evidence_packages:
        if recommendation.evidence_id and package.evidence_id == recommendation.evidence_id:
            return package
    for package in evidence_packages:
        if package.ts_code == recommendation.ts_code:
            return package
    return None
