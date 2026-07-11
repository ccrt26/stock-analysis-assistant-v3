from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from stock_analyzer.analysis.action_policy import (
    ActionPolicyInput,
    build_action_recommendation,
)
from stock_analyzer.analysis.scoring import score_feature
from stock_analyzer.data.models import FundamentalSummaryRow
from stock_analyzer.domain.models import (
    ActionDecision,
    ActionRecommendation,
    DataAvailability,
    DataRequirementLevel,
    DataRequirementStatus,
    EvidenceAtom,
    EvidenceModule,
    EvidencePolarity,
    FeatureSnapshot,
    ManualHolding,
    ModuleEvidence,
    RecommendationCard,
    StrategyEvidenceSnapshot,
)

_STRATEGY_SOURCE_VERSION = "strategy_v2_task_6"


class StrategyRecommendationResult(BaseModel):
    cards: list[RecommendationCard] = Field(default_factory=list)
    snapshots: list[StrategyEvidenceSnapshot] = Field(default_factory=list)
    data_insufficient_snapshots: list[StrategyEvidenceSnapshot] = Field(
        default_factory=list
    )


def generate_strategy_v2_recommendations(
    features: list[FeatureSnapshot],
    stock_names: dict[str, str],
    trade_date: date | None = None,
    limit: int = 10,
    company_profiles: dict[str, str] | None = None,
    board_context: dict[str, str] | None = None,
    official_events: dict[str, list[str]] | None = None,
    public_information: dict[str, list[str]] | None = None,
    current_holdings: dict[str, ManualHolding] | None = None,
    fundamental_summaries: dict[str, FundamentalSummaryRow] | None = None,
    official_hard_risks: dict[str, bool] | None = None,
) -> StrategyRecommendationResult:
    effective_limit = max(min(limit, 10), 0)
    usable_snapshots: list[StrategyEvidenceSnapshot] = []
    data_insufficient_snapshots: list[StrategyEvidenceSnapshot] = []

    for feature in features:
        snapshot = build_strategy_snapshot(
            feature=feature,
            stock_name=stock_names.get(feature.ts_code, feature.ts_code),
            trade_date=trade_date,
            company_profile=(company_profiles or {}).get(feature.ts_code),
            board_context=_context_for_feature(board_context or {}, feature),
            official_events=(official_events or {}).get(feature.ts_code, []),
            public_information=(public_information or {}).get(feature.ts_code, []),
            current_holding=(current_holdings or {}).get(feature.ts_code),
            fundamental_summary=(fundamental_summaries or {}).get(feature.ts_code),
            official_hard_risk=(official_hard_risks or {}).get(feature.ts_code, False),
        )
        if snapshot.data_insufficient:
            data_insufficient_snapshots.append(snapshot)
        else:
            usable_snapshots.append(snapshot)

    ranked = sorted(
        usable_snapshots,
        key=lambda snapshot: (-snapshot.internal_score, snapshot.ts_code),
    )[:effective_limit]
    return StrategyRecommendationResult(
        cards=[_build_recommendation_card(snapshot) for snapshot in ranked],
        snapshots=ranked,
        data_insufficient_snapshots=data_insufficient_snapshots,
    )


def build_strategy_snapshot(
    feature: FeatureSnapshot,
    stock_name: str | None = None,
    trade_date: date | None = None,
    company_profile: str | None = None,
    board_context: str | None = None,
    official_events: list[str] | None = None,
    public_information: list[str] | None = None,
    current_holding: ManualHolding | None = None,
    fundamental_summary: FundamentalSummaryRow | None = None,
    official_hard_risk: bool = False,
) -> StrategyEvidenceSnapshot:
    snapshot_date = trade_date or feature.trade_date
    name = stock_name or feature.ts_code
    official_events = official_events or []
    public_information = public_information or []
    internal_score = score_feature(feature)

    if feature.data_quality != "ok":
        return _build_data_insufficient_snapshot(
            feature=feature,
            name=name,
            trade_date=snapshot_date,
            internal_score=internal_score,
        )

    expected_upside_pct = _expected_upside_pct(feature)
    expected_downside_pct = _expected_downside_pct(feature)
    risk_reward = round(expected_upside_pct / expected_downside_pct, 2)
    hard_risk = official_hard_risk or _has_official_risk(official_events)
    market_support = _market_support(feature, board_context)
    thesis_quality = _thesis_quality(feature, company_profile, official_events)
    technical_invalidation = _technical_invalidation(feature)
    action = build_action_recommendation(
        ActionPolicyInput(
            market_support=market_support,
            thesis_quality=thesis_quality,
            risk_reward=risk_reward,
            volatility_20d=max(feature.volatility_20d, 0.0),
            liquidity_score=_clamp(feature.liquidity_score),
            current_holding=current_holding,
            technical_invalidation=technical_invalidation,
            catalyst_freshness=_catalyst_freshness(
                official_events, public_information
            ),
            hard_risk=hard_risk,
        )
    )
    modules = [
        _company_business_module(
            feature, name, snapshot_date, company_profile
        ),
        _fundamentals_valuation_module(
            feature,
            snapshot_date,
            fundamental_summary,
        ),
        _market_board_module(feature, snapshot_date, board_context),
        _trend_volume_module(feature, snapshot_date),
        _events_catalysts_module(
            feature, snapshot_date, official_events, public_information
        ),
        _risk_counter_module(
            feature=feature,
            trade_date=snapshot_date,
            official_events=official_events,
            current_holding=current_holding,
            action=action,
            official_hard_risk=official_hard_risk,
        ),
    ]

    return StrategyEvidenceSnapshot(
        evidence_id=_evidence_id(snapshot_date, feature.ts_code),
        trade_date=snapshot_date,
        ts_code=feature.ts_code,
        name=name,
        modules=modules,
        action=action,
        thesis=_thesis(feature, name, action),
        expected_upside_pct=expected_upside_pct,
        expected_downside_pct=expected_downside_pct,
        risk_reward=risk_reward,
        focus_entry_progress=_focus_entry_progress(feature),
        display_rank_bucket=_display_rank_bucket(action),
        internal_score=internal_score,
        data_insufficient=False,
        data_insufficient_reason=None,
        source_versions=_source_versions(feature, snapshot_date),
    )


def _build_data_insufficient_snapshot(
    feature: FeatureSnapshot,
    name: str,
    trade_date: date,
    internal_score: float,
) -> StrategyEvidenceSnapshot:
    reason = f"数据不足：{feature.data_quality}，不形成正向推荐卡片。"
    action = build_action_recommendation(
        ActionPolicyInput(
            market_support=0.0,
            thesis_quality=0.0,
            risk_reward=0.0,
            volatility_20d=max(feature.volatility_20d, 0.0),
            liquidity_score=_clamp(feature.liquidity_score),
            current_holding=None,
            technical_invalidation="数据补齐前不形成观察结论",
            catalyst_freshness="none",
            hard_risk=True,
        )
    )
    return StrategyEvidenceSnapshot(
        evidence_id=_evidence_id(trade_date, feature.ts_code),
        trade_date=trade_date,
        ts_code=feature.ts_code,
        name=name,
        modules=_data_insufficient_modules(feature, trade_date, reason),
        action=action,
        thesis=f"{name}数据不足，不形成 Strategy V2 观察结论。",
        expected_upside_pct=None,
        expected_downside_pct=None,
        risk_reward=None,
        focus_entry_progress=None,
        display_rank_bucket="数据不足",
        internal_score=internal_score,
        data_insufficient=True,
        data_insufficient_reason=reason,
        source_versions=_source_versions(feature, trade_date),
    )


def _company_business_module(
    feature: FeatureSnapshot,
    name: str,
    trade_date: date,
    company_profile: str | None,
) -> ModuleEvidence:
    if company_profile:
        support = [
            _atom(
                feature,
                trade_date,
                "company-profile",
                EvidenceModule.COMPANY_BUSINESS,
                EvidencePolarity.SUPPORT,
                "公司业务画像可用",
                f"{name}已有业务画像，可用于解释行业与趋势证据。",
                ["company_profile"],
                ["src_csrc_disclosure_rules"],
                0.42,
                "strategy_v2.company_profile",
            )
        ]
        counter: list[EvidenceAtom] = []
        conclusion = "公司业务信息可辅助理解，但仍需其他模块确认。"
    else:
        support = []
        counter = [
            _atom(
                feature,
                trade_date,
                "company-profile-missing",
                EvidenceModule.COMPANY_BUSINESS,
                EvidencePolarity.COUNTER,
                "公司业务画像缺失",
                "缺少公司主营和业务结构信息，不能把题材理解作为正向证据。",
                ["company_profile"],
                ["src_csrc_disclosure_rules"],
                0.38,
                "strategy_v2.company_profile",
                source_grade="C",
            )
        ]
        conclusion = "公司业务画像不完整，本模块不提供正向结论。"
    return ModuleEvidence(
        module=EvidenceModule.COMPANY_BUSINESS,
        summary=conclusion,
        support=support,
        counter=counter,
        data_requirements=[
            _requirement(
                "company_profile",
                DataRequirementLevel.ENHANCED,
                DataAvailability.AVAILABLE_LOCAL_CACHE
                if company_profile
                else DataAvailability.UNAVAILABLE_AFTER_RECOVERY,
                missing_fields=[] if company_profile else ["company_profile"],
            )
        ],
        conclusion=conclusion,
    )


def _fundamentals_valuation_module(
    feature: FeatureSnapshot,
    trade_date: date,
    fundamental_summary: FundamentalSummaryRow | None = None,
) -> ModuleEvidence:
    structured_support, structured_counter = _structured_fundamental_atoms(
        feature,
        trade_date,
        fundamental_summary,
    )
    support: list[EvidenceAtom] = list(structured_support)
    counter: list[EvidenceAtom] = [
        _atom(
            feature,
            trade_date,
            "valuation-missing",
            EvidenceModule.FUNDAMENTALS_VALUATION,
            EvidencePolarity.COUNTER,
            "估值字段未补齐",
            "PE/PB 等估值字段未进入当前特征，风险收益估计需保持保守。",
            ["pe", "pb"],
            ["src_fama_french_1992", "src_liu_stambaugh_yuan_2019"],
            0.34,
            "strategy_v2.fundamentals",
            source_grade="C",
        )
    ]
    counter.extend(structured_counter)
    if feature.quality_score >= 0.65:
        support.append(
            _atom(
                feature,
                trade_date,
                "quality-support",
                EvidenceModule.FUNDAMENTALS_VALUATION,
                EvidencePolarity.SUPPORT,
                "质量评分达到观察要求",
                f"质量评分 {feature.quality_score:.2f}，可作为基础质量支持。",
                ["quality_score"],
                ["src_dechow_ge_schrand_2010"],
                _clamp(feature.quality_score),
                "feature_snapshot.quality",
            )
        )
        conclusion = "质量评分支持观察，但估值字段缺失限制结论强度。"
    else:
        counter.append(
            _atom(
                feature,
                trade_date,
                "quality-weak",
                EvidenceModule.FUNDAMENTALS_VALUATION,
                EvidencePolarity.COUNTER,
                "质量评分偏弱",
                f"质量评分 {feature.quality_score:.2f}，未达到观察质量阈值。",
                ["quality_score"],
                ["src_dechow_ge_schrand_2010"],
                0.45,
                "feature_snapshot.quality",
            )
        )
        conclusion = "质量和估值证据不足，本模块不形成正向结论。"
    return ModuleEvidence(
        module=EvidenceModule.FUNDAMENTALS_VALUATION,
        summary=conclusion,
        support=support,
        counter=counter,
        data_requirements=[
            _requirement(
                "daily_basic",
                DataRequirementLevel.REQUIRED,
                DataAvailability.AVAILABLE_LOCAL_CACHE,
            ),
            _requirement(
                "valuation",
                DataRequirementLevel.ENHANCED,
                DataAvailability.UNAVAILABLE_AFTER_RECOVERY,
                missing_fields=["pe", "pb"],
            ),
            _requirement(
                "fundamental_summary",
                DataRequirementLevel.ENHANCED,
                DataAvailability.AVAILABLE_PRIMARY
                if fundamental_summary is not None
                and fundamental_summary.source_grade.value == "primary"
                else DataAvailability.AVAILABLE_BACKUP
                if fundamental_summary is not None
                else DataAvailability.UNAVAILABLE_AFTER_RECOVERY,
                missing_fields=[] if fundamental_summary is not None else ["fundamental_summary"],
            ),
        ],
        conclusion=conclusion,
    )


def _structured_fundamental_atoms(
    feature: FeatureSnapshot,
    trade_date: date,
    summary: FundamentalSummaryRow | None,
) -> tuple[list[EvidenceAtom], list[EvidenceAtom]]:
    if summary is None:
        return [], []
    period = summary.period_end.isoformat() if summary.period_end else "报告期未标注"
    source = summary.source_name
    specifications = (
        ("revenue_yoy", "营业收入同比", summary.revenue_yoy, "%"),
        ("profit_yoy", "利润同比", summary.profit_yoy, "%"),
        ("gross_margin", "毛利率", summary.gross_margin, "%"),
        ("operating_cashflow", "经营现金流", summary.operating_cashflow, ""),
    )
    support: list[EvidenceAtom] = []
    counter: list[EvidenceAtom] = []
    for field, label, value, suffix in specifications:
        if value is None:
            continue
        formatted = f"{value:.2f}{suffix}"
        atom = _atom(
            feature,
            trade_date,
            f"structured-{field}",
            EvidenceModule.FUNDAMENTALS_VALUATION,
            EvidencePolarity.SUPPORT if value >= 0 else EvidencePolarity.COUNTER,
            f"{label}已取得结构化证据",
            f"{period} {source}：{label} {formatted}。",
            [field, "period_end", "source_name"],
            ["src_dechow_ge_schrand_2010"],
            0.55,
            source,
        )
        (support if value >= 0 else counter).append(atom)
    return support, counter


def _market_board_module(
    feature: FeatureSnapshot,
    trade_date: date,
    board_context: str | None,
) -> ModuleEvidence:
    support: list[EvidenceAtom] = []
    counter: list[EvidenceAtom] = []
    industry = feature.industry or "未分行业"
    context = board_context or "未提供板块补充说明"
    if _market_support(feature, board_context) >= 0.7:
        support.append(
            _atom(
                feature,
                trade_date,
                "market-support",
                EvidenceModule.MARKET_BOARD,
                EvidencePolarity.SUPPORT,
                "市场与行业环境支持观察",
                f"市场状态 {feature.market_regime}，行业 {industry}；{context}。",
                ["market_regime", "industry", "relative_strength"],
                ["src_chen_roll_ross_1986", "src_fama_french_1989"],
                _market_support(feature, board_context),
                "feature_snapshot.market",
            )
        )
        conclusion = "市场和板块环境对观察有支持。"
    else:
        counter.append(
            _atom(
                feature,
                trade_date,
                "market-weak",
                EvidenceModule.MARKET_BOARD,
                EvidencePolarity.COUNTER,
                "市场或板块支持不足",
                f"市场状态 {feature.market_regime}，行业 {industry}，仍需板块确认。",
                ["market_regime", "industry", "relative_strength"],
                ["src_chen_roll_ross_1986", "src_fama_french_1989"],
                0.48,
                "feature_snapshot.market",
            )
        )
        conclusion = "市场或板块证据尚未充分确认。"
    return ModuleEvidence(
        module=EvidenceModule.MARKET_BOARD,
        summary=conclusion,
        support=support,
        counter=counter,
        data_requirements=[
            _requirement(
                "market_board",
                DataRequirementLevel.REQUIRED,
                DataAvailability.AVAILABLE_LOCAL_CACHE,
            )
        ],
        conclusion=conclusion,
    )


def _trend_volume_module(feature: FeatureSnapshot, trade_date: date) -> ModuleEvidence:
    support: list[EvidenceAtom] = []
    counter: list[EvidenceAtom] = []
    if feature.trend_20d > 0 and feature.trend_60d > 0:
        support.append(
            _atom(
                feature,
                trade_date,
                "trend-positive",
                EvidenceModule.TREND_VOLUME,
                EvidencePolarity.SUPPORT,
                "20 日与 60 日趋势同步改善",
                f"20 日趋势 {feature.trend_20d:.2%}，60 日趋势 {feature.trend_60d:.2%}。",
                ["trend_20d", "trend_60d"],
                ["RESEARCH_TREND_CONFIRMATION", "src_jegadeesh_titman_1993"],
                _clamp(0.55 + feature.trend_20d + feature.trend_60d),
                "feature_snapshot.trend",
            )
        )
    else:
        counter.append(
            _atom(
                feature,
                trade_date,
                "trend-not-confirmed",
                EvidenceModule.TREND_VOLUME,
                EvidencePolarity.COUNTER,
                "趋势窗口未同步确认",
                "20 日和 60 日趋势没有同时转正。",
                ["trend_20d", "trend_60d"],
                ["RESEARCH_TREND_CONFIRMATION", "src_cn_timeseries_momentum_2017"],
                0.5,
                "feature_snapshot.trend",
            )
        )
    if feature.relative_strength >= 0.6 and feature.liquidity_score >= 0.6:
        support.append(
            _atom(
                feature,
                trade_date,
                "strength-liquidity",
                EvidenceModule.TREND_VOLUME,
                EvidencePolarity.SUPPORT,
                "相对强度和流动性满足观察要求",
                f"相对强度 {feature.relative_strength:.2f}，流动性 {feature.liquidity_score:.2f}。",
                ["relative_strength", "liquidity_score"],
                ["RESEARCH_TREND_CONFIRMATION", "src_acharya_pedersen_2005"],
                _clamp((feature.relative_strength + feature.liquidity_score) / 2),
                "feature_snapshot.trend",
            )
        )
    if feature.volatility_20d > 0.35:
        counter.append(
            _atom(
                feature,
                trade_date,
                "volatility-high",
                EvidenceModule.TREND_VOLUME,
                EvidencePolarity.COUNTER,
                "20 日波动率偏高",
                f"20 日波动率 {feature.volatility_20d:.2f}，不适合追高。",
                ["volatility_20d"],
                ["src_cn_price_limit_hits_2015"],
                _clamp(feature.volatility_20d),
                "feature_snapshot.trend",
            )
        )
    if feature.trend_20d >= 0.18 or feature.trend_60d >= 0.32:
        counter.append(
            _atom(
                feature,
                trade_date,
                "trend-overextended",
                EvidenceModule.TREND_VOLUME,
                EvidencePolarity.COUNTER,
                "短中期涨幅存在过热风险",
                "趋势扩张较快，需要等待回撤或量能确认。",
                ["trend_20d", "trend_60d"],
                ["src_barberis_shleifer_vishny_1998", "src_xiong_yu_2011"],
                0.5,
                "feature_snapshot.trend",
            )
        )
    conclusion = (
        "趋势、强度和流动性支持观察。"
        if support and not counter
        else "趋势证据存在支持，但需要结合反证控制节奏。"
        if support
        else "趋势证据不足。"
    )
    return ModuleEvidence(
        module=EvidenceModule.TREND_VOLUME,
        summary=conclusion,
        support=support,
        counter=counter,
        data_requirements=[
            _requirement(
                "daily_ohlcv",
                DataRequirementLevel.REQUIRED,
                DataAvailability.AVAILABLE_LOCAL_CACHE,
            )
        ],
        conclusion=conclusion,
    )


def _events_catalysts_module(
    feature: FeatureSnapshot,
    trade_date: date,
    official_events: list[str],
    public_information: list[str],
) -> ModuleEvidence:
    support: list[EvidenceAtom] = []
    counter: list[EvidenceAtom] = []
    for index, event in enumerate(official_events):
        if _contains_risk_text(event):
            counter.append(
                _atom(
                    feature,
                    trade_date,
                    f"official-risk-{index}",
                    EvidenceModule.EVENTS_CATALYSTS,
                    EvidencePolarity.COUNTER,
                    "官方风险事件需要优先处理",
                    event,
                    ["official_events"],
                    ["OFFICIAL_DELISTING_RISK_EXCLUDE", "src_cn_csrc_penalty_portal"],
                    0.9,
                    "official_event_feed",
                    source_grade="A",
                )
            )
        else:
            support.append(
                _atom(
                    feature,
                    trade_date,
                    f"official-catalyst-{index}",
                    EvidenceModule.EVENTS_CATALYSTS,
                    EvidencePolarity.SUPPORT,
                    "官方催化信息可用",
                    event,
                    ["official_events"],
                    ["src_fama_fisher_jensen_roll_1969"],
                    0.7,
                    "official_event_feed",
                    source_grade="A",
                )
            )
    for index, item in enumerate(public_information):
        counter.append(
            _atom(
                feature,
                trade_date,
                f"public-observation-{index}",
                EvidenceModule.EVENTS_CATALYSTS,
                EvidencePolarity.COUNTER,
                "公开信息仅作为观察材料",
                item,
                ["public_information"],
                ["src_tetlock_2007", "src_short_disclose_distort_2024"],
                0.28,
                "public_information",
                source_grade="C",
            )
        )
    if not official_events:
        counter.append(
            _atom(
                feature,
                trade_date,
                "official-catalyst-missing",
                EvidenceModule.EVENTS_CATALYSTS,
                EvidencePolarity.COUNTER,
                "缺少新鲜官方催化",
                "当前没有官方事件作为催化确认，不能把传闻或观察材料作为正向依据。",
                ["official_events"],
                ["src_chan_2003"],
                0.32,
                "strategy_v2.events",
                source_grade="C",
            )
        )
    conclusion = (
        "官方催化存在，但仍需跟踪兑现。"
        if support
        else "催化证据不足，本模块仅提示观察约束。"
    )
    return ModuleEvidence(
        module=EvidenceModule.EVENTS_CATALYSTS,
        summary=conclusion,
        support=support,
        counter=counter,
        data_requirements=[
            _requirement(
                "events_catalysts",
                DataRequirementLevel.OBSERVATION,
                DataAvailability.AVAILABLE_LOCAL_CACHE
                if official_events or public_information
                else DataAvailability.UNAVAILABLE_AFTER_RECOVERY,
                missing_fields=[] if official_events else ["official_events"],
            )
        ],
        conclusion=conclusion,
    )


def _risk_counter_module(
    feature: FeatureSnapshot,
    trade_date: date,
    official_events: list[str],
    current_holding: ManualHolding | None,
    action: ActionRecommendation,
    official_hard_risk: bool = False,
) -> ModuleEvidence:
    support: list[EvidenceAtom] = []
    counter: list[EvidenceAtom] = []
    if official_hard_risk or _has_official_risk(official_events):
        counter.append(
            _atom(
                feature,
                trade_date,
                "official-risk",
                EvidenceModule.RISK_COUNTER,
                EvidencePolarity.COUNTER,
                "官方风险事件压制观察结论",
                "存在官方风险事件时，先降低风险暴露优先级。",
                ["official_events"],
                ["OFFICIAL_DELISTING_RISK_EXCLUDE", "src_cn_csrc_penalty_portal"],
                0.9,
                "strategy_v2.risk",
                source_grade="A",
            )
        )
    if feature.liquidity_score < 0.6:
        counter.append(
            _atom(
                feature,
                trade_date,
                "liquidity-risk",
                EvidenceModule.RISK_COUNTER,
                EvidencePolarity.COUNTER,
                "流动性不足",
                f"流动性评分 {feature.liquidity_score:.2f}，可能放大冲击成本。",
                ["liquidity_score"],
                ["COUNTER_LOW_LIQUIDITY_NOISE", "src_acharya_pedersen_2005"],
                0.6,
                "feature_snapshot.risk",
            )
        )
    if feature.volatility_20d > 0.35:
        counter.append(
            _atom(
                feature,
                trade_date,
                "volatility-risk",
                EvidenceModule.RISK_COUNTER,
                EvidencePolarity.COUNTER,
                "波动风险偏高",
                f"20 日波动率 {feature.volatility_20d:.2f}，仓位上限需要收紧。",
                ["volatility_20d"],
                ["src_markowitz_1952"],
                0.58,
                "feature_snapshot.risk",
            )
        )
    if feature.trend_20d >= 0.18 or feature.trend_60d >= 0.32:
        counter.append(
            _atom(
                feature,
                trade_date,
                "overextension-risk",
                EvidenceModule.RISK_COUNTER,
                EvidencePolarity.COUNTER,
                "趋势延伸后追高风险上升",
                "趋势扩张过快时，风险收益比可能被压缩。",
                ["trend_20d", "trend_60d"],
                ["src_barberis_shleifer_vishny_1998", "src_xiong_yu_2011"],
                0.55,
                "feature_snapshot.risk",
            )
        )
    if not official_events:
        counter.append(
            _atom(
                feature,
                trade_date,
                "catalyst-failure-risk",
                EvidenceModule.RISK_COUNTER,
                EvidencePolarity.COUNTER,
                "催化落空风险",
                "没有官方催化时，趋势修复需要更多成交和板块确认。",
                ["official_events"],
                ["src_chan_2003"],
                0.42,
                "strategy_v2.risk",
                source_grade="C",
            )
        )
    if current_holding and current_holding.position_pct >= 15.0:
        counter.append(
            _atom(
                feature,
                trade_date,
                "holding-concentration-risk",
                EvidenceModule.RISK_COUNTER,
                EvidencePolarity.COUNTER,
                "持仓集中度偏高",
                f"当前持仓 {current_holding.position_pct:.1f}%，不应提高目标上限。",
                ["manual_holding.position_pct"],
                ["src_markowitz_1952", "src_treynor_black_1973"],
                0.7,
                "manual_holding",
            )
        )
    if not counter:
        support.append(
            _atom(
                feature,
                trade_date,
                "risk-contained",
                EvidenceModule.RISK_COUNTER,
                EvidencePolarity.SUPPORT,
                "主要硬风险未触发",
                "未见官方风险、低流动性、高波动或持仓集中约束。",
                ["liquidity_score", "volatility_20d", "official_events"],
                ["src_markowitz_1952"],
                0.55,
                "strategy_v2.risk",
            )
        )
    conclusion = (
        f"风险模块要求遵守动作策略：{action.decision.value}。"
        if action.decision != ActionDecision.NO_PARTICIPATION
        else "风险模块不支持形成参与结论。"
    )
    return ModuleEvidence(
        module=EvidenceModule.RISK_COUNTER,
        summary=conclusion,
        support=support,
        counter=counter,
        data_requirements=[
            _requirement(
                "risk_counter",
                DataRequirementLevel.REQUIRED,
                DataAvailability.AVAILABLE_LOCAL_CACHE,
            )
        ],
        conclusion=conclusion,
    )


def _data_insufficient_modules(
    feature: FeatureSnapshot, trade_date: date, reason: str
) -> list[ModuleEvidence]:
    modules: list[ModuleEvidence] = []
    for module in EvidenceModule:
        atom = _atom(
            feature,
            trade_date,
            "data-insufficient",
            module,
            EvidencePolarity.COUNTER,
            "数据不足",
            reason,
            ["data_quality"],
            [],
            1.0,
            "feature_snapshot.data_quality",
            source_grade="A",
        )
        modules.append(
            ModuleEvidence(
                module=module,
                summary=reason,
                support=[],
                counter=[atom],
                data_requirements=[
                    _requirement(
                        module.value,
                        DataRequirementLevel.REQUIRED,
                        DataAvailability.UNAVAILABLE_AFTER_RECOVERY,
                        missing_fields=[feature.data_quality],
                        blocks_complete_analysis=True,
                    )
                ],
                conclusion="数据不足，不形成正向结论。",
            )
        )
    return modules


def _build_recommendation_card(
    snapshot: StrategyEvidenceSnapshot,
) -> RecommendationCard:
    trend_module = _module(snapshot, EvidenceModule.TREND_VOLUME)
    market_module = _module(snapshot, EvidenceModule.MARKET_BOARD)
    risk_module = _module(snapshot, EvidenceModule.RISK_COUNTER)
    main_risk_atom = (
        risk_module.counter[0]
        if risk_module and risk_module.counter
        else _first_counter(snapshot.modules)
    )
    return RecommendationCard(
        trade_date=snapshot.trade_date,
        ts_code=snapshot.ts_code,
        name=snapshot.name,
        display_rank_bucket=snapshot.display_rank_bucket,
        action=snapshot.action.decision.value,
        position_min_pct=snapshot.action.position_min_pct,
        position_max_pct=snapshot.action.position_max_pct,
        action_reasoning=list(snapshot.action.reasoning),
        required_confirmation=list(snapshot.action.required_confirmation),
        invalidation_conditions=list(snapshot.action.invalidation_conditions),
        risk_if_wrong=snapshot.action.risk_if_wrong,
        staging_plan=list(snapshot.action.staging_plan),
        holding_adjustment=snapshot.action.holding_adjustment,
        what_happened=trend_module.summary if trend_module else snapshot.thesis,
        why_it_may_have_happened=(
            market_module.summary if market_module else "市场和板块证据仍需确认。"
        ),
        what_it_may_mean=(
            f"{snapshot.action.decision.value}；{snapshot.action.reasoning[0]}"
        ),
        main_risk=_atom_text(main_risk_atom)
        if main_risk_atom
        else snapshot.action.risk_if_wrong,
        focus_entry_progress=snapshot.focus_entry_progress,
        needed_before_focus_entry=list(snapshot.action.required_confirmation),
        evidence_id=snapshot.evidence_id,
    )


def _module(
    snapshot: StrategyEvidenceSnapshot, module: EvidenceModule
) -> ModuleEvidence | None:
    for item in snapshot.modules:
        if item.module == module:
            return item
    return None


def _first_counter(modules: list[ModuleEvidence]) -> EvidenceAtom | None:
    for module in modules:
        if module.counter:
            return module.counter[0]
    return None


def _atom_text(atom: EvidenceAtom) -> str:
    return f"{atom.headline}：{atom.detail}" if atom.detail else atom.headline


def _atom(
    feature: FeatureSnapshot,
    trade_date: date,
    suffix: str,
    module: EvidenceModule,
    polarity: EvidencePolarity,
    headline: str,
    detail: str,
    data_fields: list[str],
    rules: list[str],
    strength: float,
    source_name: str,
    source_grade: str = "B",
) -> EvidenceAtom:
    return EvidenceAtom(
        id=f"{trade_date.isoformat()}-{feature.ts_code}-{module.value}-{suffix}",
        module=module,
        polarity=polarity,
        headline=headline,
        detail=detail,
        source_grade=source_grade,
        source_name=source_name,
        source_url=None,
        data_fields=data_fields,
        knowledge_rule_ids=rules,
        strength=round(_clamp(strength), 2),
        as_of_date=trade_date,
    )


def _requirement(
    family: str,
    level: DataRequirementLevel,
    availability: DataAvailability,
    missing_fields: list[str] | None = None,
    blocks_complete_analysis: bool = False,
) -> DataRequirementStatus:
    return DataRequirementStatus(
        family=family,
        level=level,
        availability=availability,
        missing_fields=missing_fields or [],
        blocks_complete_analysis=blocks_complete_analysis,
    )


def _context_for_feature(
    board_context: dict[str, str], feature: FeatureSnapshot
) -> str | None:
    if feature.ts_code in board_context:
        return board_context[feature.ts_code]
    if feature.industry and feature.industry in board_context:
        return board_context[feature.industry]
    return None


def _evidence_id(trade_date: date, ts_code: str) -> str:
    return f"{trade_date.isoformat()}-{ts_code}"


def _source_versions(feature: FeatureSnapshot, trade_date: date) -> dict[str, str]:
    return {
        "feature_snapshot": feature.trade_date.isoformat(),
        "strategy_v2": _STRATEGY_SOURCE_VERSION,
        "trade_date": trade_date.isoformat(),
    }


def _market_support(feature: FeatureSnapshot, board_context: str | None) -> float:
    regime = feature.market_regime.lower()
    if regime in {"bull", "uptrend", "strong"} or "强" in feature.market_regime:
        base = 0.72
    elif regime in {"bear", "downtrend", "weak"} or "弱" in feature.market_regime:
        base = 0.35
    elif regime in {"sideways", "neutral"}:
        base = 0.58
    else:
        base = 0.52
    context_bonus = 0.05 if board_context else 0.0
    return _clamp(
        base
        + (feature.relative_strength - 0.5) * 0.4
        + max(feature.trend_60d, 0.0) * 0.6
        - max(feature.volatility_20d - 0.35, 0.0) * 0.25
        + context_bonus
    )


def _thesis_quality(
    feature: FeatureSnapshot,
    company_profile: str | None,
    official_events: list[str],
) -> float:
    trend_bonus = 0.12 if feature.trend_20d > 0 and feature.trend_60d > 0 else 0.0
    profile_bonus = 0.05 if company_profile else 0.0
    event_bonus = (
        0.05 if official_events and not _has_official_risk(official_events) else 0.0
    )
    return _clamp(
        0.35
        + feature.quality_score * 0.35
        + feature.relative_strength * 0.25
        + trend_bonus
        + profile_bonus
        + event_bonus
    )


def _expected_upside_pct(feature: FeatureSnapshot) -> float:
    upside = (
        max(feature.trend_20d, 0.0) * 70
        + max(feature.trend_60d, 0.0) * 35
        + feature.relative_strength * 4
        + feature.quality_score * 2
    )
    return round(max(upside, 4.0), 2)


def _expected_downside_pct(feature: FeatureSnapshot) -> float:
    downside = feature.volatility_20d * 18 + max(-feature.trend_20d, 0.0) * 30
    return round(max(downside, 3.0), 2)


def _technical_invalidation(feature: FeatureSnapshot) -> str:
    if feature.trend_20d > 0:
        return "跌破 20 日趋势并伴随相对强度转弱"
    return "20 日趋势继续为负且相对强度未修复"


def _catalyst_freshness(
    official_events: list[str], public_information: list[str]
) -> str:
    if official_events:
        return "fresh_official"
    if public_information:
        return "observation_only"
    return "none"


def _display_rank_bucket(action: ActionRecommendation) -> str:
    decision = action.decision
    if decision == ActionDecision.NO_PARTICIPATION:
        return "不参与"
    if decision == ActionDecision.REDUCE_OR_AVOID:
        return "降低风险"
    if decision == ActionDecision.AVOID_CHASING:
        return "避免追高"
    if decision == ActionDecision.SMALL_EXPLORATORY:
        return "小仓试探"
    if decision == ActionDecision.CONDITIONAL_ADD:
        return "确认后加仓"
    if decision == ActionDecision.CONTINUE_WATCHING:
        return "继续观察"
    if decision == ActionDecision.INCREASE_ATTENTION:
        return "提高关注"
    if decision == ActionDecision.CONFIRM_REMOVAL:
        return "确认移出"
    return "等待确认"


def _focus_entry_progress(feature: FeatureSnapshot) -> str:
    support_count = sum(
        [
            feature.trend_20d > 0,
            feature.trend_60d > 0,
            feature.relative_strength >= 0.6,
            feature.liquidity_score >= 0.6,
            feature.quality_score >= 0.65,
        ]
    )
    return f"观察第 1/5 个交易日，最近 5 项支持 {support_count} 项。"


def _thesis(feature: FeatureSnapshot, name: str, action: ActionRecommendation) -> str:
    industry = feature.industry or "未分行业"
    decision = action.decision
    if decision in {
        ActionDecision.NO_PARTICIPATION,
        ActionDecision.REDUCE_OR_AVOID,
        ActionDecision.CONFIRM_REMOVAL,
    }:
        return (
            f"{name}处于{industry}，当前风险或反证使数据不支持参与；"
            f"当前动作策略为{decision.value}。"
        )
    if decision == ActionDecision.AVOID_CHASING:
        return (
            f"{name}处于{industry}，现有证据只支持谨慎观察，"
            f"风险收益或波动状态不支持追高；当前动作策略为{decision.value}。"
        )
    if decision == ActionDecision.WAIT_FOR_CONFIRMATION:
        return (
            f"{name}处于{industry}，数据仅支持等待确认，"
            f"尚不支持形成参与结论；当前动作策略为{decision.value}。"
        )
    return (
        f"{name}处于{industry}，趋势、板块和风险证据支持 2-8 周观察；"
        f"当前动作策略为{decision.value}。"
    )


def _has_official_risk(events: list[str]) -> bool:
    return any(_contains_risk_text(event) for event in events)


def _contains_risk_text(text: str) -> bool:
    risk_terms = ("风险", "处罚", "立案", "退市", "亏损", "减持", "诉讼")
    return any(term in text for term in risk_terms)


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))
