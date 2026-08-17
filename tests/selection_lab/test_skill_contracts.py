from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILLS = (
    ROOT / ".agents/skills/orchestrating-stock-research/SKILL.md",
    ROOT / ".agents/skills/researching-sectors-industries/SKILL.md",
    ROOT / ".agents/skills/researching-company-events/SKILL.md",
    ROOT / ".agents/skills/analyzing-price-trading/SKILL.md",
)
OPPORTUNITY_TYPES = (
    "company_catalyst",
    "sector_diffusion",
    "independent_price_anomaly",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_four_skill_contracts_share_exact_opportunity_type_vocabulary():
    for path in SKILLS:
        text = _read(path)
        for opportunity_type in OPPORTUNITY_TYPES:
            assert opportunity_type in text, f"{path}: {opportunity_type}"
        assert "机会类型不是 Gate、配额、评分、优先级、投票或补位规则" in text


def test_orchestrator_outputs_full_assignment_contract_twice():
    text = _read(SKILLS[0])
    for field in (
        "opportunity_type",
        "opportunity_type_status",
        "secondary_opportunity_types",
        "opportunity_type_confidence",
        "opportunity_type_as_of",
        "opportunity_type_evidence",
        "opportunity_type_assignment_reason",
    ):
        assert text.count(field) >= 2, field


def test_sector_and_price_contracts_remove_implicit_company_event_gate():
    sector = _read(SKILLS[1])
    price = _read(SKILLS[3])

    assert "sector_diffusion 不要求形成日存在新公司公告" in sector
    assert "independent_price_anomaly 可无新公司公告" in price


def test_current_architecture_documents_isolated_blocked_lab():
    architecture = _read(ROOT / "docs/architecture/current-v3-architecture.md")
    readme = _read(ROOT / "README.md")

    for text in (architecture, readme):
        assert "selection_lab" in text
        assert "实验阻塞" in text
        assert "不拥有自动选股权" in text
