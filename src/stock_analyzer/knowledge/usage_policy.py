from __future__ import annotations

from enum import Enum
import re

from pydantic import BaseModel


PROGRAM_TRADING_KNOWLEDGE_ID = "src_cn_program_trading_rules_2025"


class KnowledgeUseStatus(str, Enum):
    APPLIED = "applied"
    LIMITED = "limited"
    NOT_APPLICABLE = "not_applicable"
    BLOCKED_BY_DATA = "blocked_by_data"
    CONFLICTED = "conflicted"


class KnowledgeUseResult(BaseModel):
    knowledge_id: str
    status: KnowledgeUseStatus
    explanation: str


class MarketMicrostructureWordingError(ValueError):
    def __init__(self, phrase: str) -> None:
        super().__init__(
            "缺少 Level 2、逐笔委托和账户身份数据，不能把量价现象写成交易主体事实："
            + phrase
        )
        self.knowledge_id = PROGRAM_TRADING_KNOWLEDGE_ID
        self.status = KnowledgeUseStatus.BLOCKED_BY_DATA


_FORBIDDEN_WITHOUT_LEVEL2 = (
    re.compile(r"机构.{0,8}(买入|增持|承接|吸筹|出货)"),
    re.compile(r"主力.{0,8}(买入|流入|吸筹|承接|没有出货|出货)"),
    re.compile(r"(庄家|游资).{0,8}(对倒|吸筹|出货|拉升)"),
    re.compile(r"(可以证明|说明).{0,6}(机构|主力|庄家|游资)"),
)


def validate_market_microstructure_wording(
    text: str,
    *,
    level2_available: bool,
) -> KnowledgeUseResult:
    if level2_available:
        return KnowledgeUseResult(
            knowledge_id=PROGRAM_TRADING_KNOWLEDGE_ID,
            status=KnowledgeUseStatus.APPLIED,
            explanation="存在经过验证的微观交易数据，仍需区分算法推断与账户事实。",
        )
    for pattern in _FORBIDDEN_WITHOUT_LEVEL2:
        match = pattern.search(text)
        if match:
            raise MarketMicrostructureWordingError(match.group(0))
    return KnowledgeUseResult(
        knowledge_id=PROGRAM_TRADING_KNOWLEDGE_ID,
        status=KnowledgeUseStatus.LIMITED,
        explanation=(
            "只有日线或分钟线，可以描述成交、价格路径和相对强弱，"
            "不能识别机构、主力或账户身份。"
        ),
    )


__all__ = [
    "KnowledgeUseResult",
    "KnowledgeUseStatus",
    "MarketMicrostructureWordingError",
    "PROGRAM_TRADING_KNOWLEDGE_ID",
    "validate_market_microstructure_wording",
]
