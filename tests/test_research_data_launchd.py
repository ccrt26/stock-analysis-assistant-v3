from pathlib import Path


def test_research_data_launchd_is_data_only_and_resolves_previous_trading_day_in_code():
    text = Path(
        "ops/launchd/com.ccrt.stock-analysis-assistant.research-data.plist.example"
    ).read_text(encoding="utf-8")
    assert "data run-stage" in text
    assert "--data-date auto" in text
    assert "date -v-1d" not in text
    assert "08:00" in text
    assert "18:30" in text
    assert "21:30" in text
    assert "stage=\"next-morning\"" in text
    assert "stage=\"close\"" in text
    assert "stage=\"evening\"" in text
    assert "prepare-deploy" not in text
    assert "run-daily-job" not in text
    assert "Supabase" not in text
    assert "Cloudflare" not in text
