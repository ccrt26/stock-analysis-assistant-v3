"""买入决策 Skill 与执行 Prompt 的语义校验。

检查关键研究方法与旧路由隔离是否落在文字里；不以此声称报告质量已被验证。
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_PATH = REPO_ROOT / ".agents/skills/analyzing-stock-buy-decision/SKILL.md"
PROMPT_PATH = REPO_ROOT / "ops/buy-decision-prompt.md"
CALIBRATION_PATH = REPO_ROOT / "tests/fixtures/buy_decision_calibration.md"


def _read(path: Path) -> str:
    assert path.is_file(), f"missing file: {path}"
    return path.read_text(encoding="utf-8")


def test_skill_states_research_order_and_six_executable_conditions():
    skill = _read(SKILL_PATH)
    for keyword in (
        "尚未买入",
        "截止时点",
        "四类",
        "等回落",
        "等突破",
        "不做",
        "信号在什么时候才真正知道",
        "价格范围或上限",
        "涨跌停",
        "作废",
        "推翻买入判断",
        "正常发展",
        "上涨后回吐",
        "普通波动",
    ):
        assert keyword in skill, f"SKILL.md lacks keyword: {keyword}"


def test_skill_bounds_gaps_and_external_evidence():
    skill = _read(SKILL_PATH)
    for keyword in (
        "fetched_at",
        "available_at",
        "缺口只限制",
        "标题",
        "发布方",
        "读取时间",
        "历史版本不明",
    ):
        assert keyword in skill, f"SKILL.md lacks keyword: {keyword}"
    assert "不承诺收益" in skill
    assert "不算仓位" in skill


def test_prompt_requires_reading_skill_and_freezing_as_of():
    prompt = _read(PROMPT_PATH)
    assert "analyzing-stock-buy-decision/SKILL.md" in prompt
    assert "prepare" in prompt and "calculate" in prompt
    assert "不覆盖" in prompt
    assert "新建 run" in prompt
    assert "report.md" in prompt
    assert "唯一" in prompt


def test_prompt_execution_and_quote_discipline():
    prompt = _read(PROMPT_PATH)
    assert "次一交易日" in prompt
    assert "报价时间" in prompt
    assert "用户输入" in prompt
    assert "由本次研究写明" in prompt
    assert "max_tolerable_loss_pct" in prompt
    assert "不代用户填写" in prompt
    assert "买入交易日计为第一天" in prompt or "买入日计为第一天" in prompt


def test_prompt_keeps_legacy_report_numbers_out_of_general_rules():
    prompt = _read(PROMPT_PATH)
    assert "3—5天" in prompt or "3—5 天" in prompt
    assert "旧材料" in prompt or "旧报告" in prompt


def test_prompt_is_isolated_from_formal_selection_and_review_routes():
    prompt = _read(PROMPT_PATH)
    skill = _read(SKILL_PATH)
    for text in (prompt, skill):
        assert "DailyFormalReview" not in text
        assert "daily-formal-reviews" not in text
        assert "record-daily-formal-reviews" not in text
        assert "forward_selection" not in text
        assert "snapshot-" not in text.replace("snapshot-*.json", "")
    assert "不进入 Forward CSV" in skill or "Forward CSV" in skill
    assert "冻结历史" in prompt and "冻结历史" in skill


def test_calibration_covers_six_synthetic_cases():
    calibration = _read(CALIBRATION_PATH)
    assert "合成" in calibration
    for keyword in (
        "情形一",
        "情形二",
        "情形三",
        "情形四",
        "情形五",
        "情形六",
        "不足 20%",
        "空间大",
        "9.9",
        "便宜本身",
        "10.8",
        "20 个交易日",
    ):
        assert keyword in calibration, f"calibration lacks: {keyword}"
