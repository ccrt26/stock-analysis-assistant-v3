import pytest

from stock_analyzer.knowledge.usage_policy import (
    KnowledgeUseStatus,
    MarketMicrostructureWordingError,
    validate_market_microstructure_wording,
)


def test_program_trading_rule_blocks_institution_identity_without_level2():
    with pytest.raises(MarketMicrostructureWordingError) as exc:
        validate_market_microstructure_wording(
            "上涨放量，说明机构正在大举买入，而且主力没有出货。",
            level2_available=False,
        )
    assert exc.value.knowledge_id == "src_cn_program_trading_rules_2025"
    assert exc.value.status is KnowledgeUseStatus.BLOCKED_BY_DATA


def test_observable_wording_is_allowed_without_level2():
    result = validate_market_microstructure_wording(
        "上涨日成交更活跃，但现有日线和分钟线不能识别交易主体。",
        level2_available=False,
    )
    assert result.status is KnowledgeUseStatus.LIMITED
