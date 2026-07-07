from datetime import date

from stock_analyzer.domain.models import ActionLabel, FocusState, Recommendation
from stock_analyzer.reports.generator import render_reports


def test_render_reports_creates_fixed_entry_and_hides_secrets(tmp_path):
    rec = Recommendation(
        trade_date=date(2026, 7, 7),
        ts_code="600000.SH",
        name="浦发银行",
        action=ActionLabel.ENTER_OBSERVATION,
        score=81,
        reasons=["趋势改善"],
        risks=["需要确认"],
    )
    focus = FocusState(
        trade_date=date(2026, 7, 7),
        ts_code="600000.SH",
        state=ActionLabel.ENTER_OBSERVATION,
    )
    render_reports(tmp_path, [rec], [focus])
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    json_text = (tmp_path / "data" / "latest.json").read_text(encoding="utf-8")
    assert "浦发银行" in html
    assert "进入观察" in html
    assert "SUPABASE_SERVICE_ROLE_KEY" not in html
    assert "SUPABASE_SERVICE_ROLE_KEY" not in json_text
    assert "TUSHARE_TOKEN" not in html
    assert "TUSHARE_TOKEN" not in json_text
    assert "浦发银行" in json_text
