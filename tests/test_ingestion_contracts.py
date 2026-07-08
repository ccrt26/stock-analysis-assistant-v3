from datetime import date

from stock_analyzer.config import AppConfig
from stock_analyzer.data.models import DataStatus, MarketDataBundle, SourceGrade, SourceStatus


def test_tushare_token_prefers_env_and_masks_value(tmp_path):
    token_file = tmp_path / "token.txt"
    token_file.write_text("file-token-123", encoding="utf-8")
    config = AppConfig.load(
        {
            "TUSHARE_TOKEN": "env-token-456",
            "TUSHARE_TOKEN_PATH": str(token_file),
        }
    )

    assert config.resolve_tushare_token() == "env-token-456"
    assert "env-token-456" not in config.tushare_token_status()
    assert config.tushare_token_status() == "present:env"


def test_tushare_token_falls_back_to_file_without_printing_value(tmp_path):
    token_file = tmp_path / "token.txt"
    token_file.write_text("file-token-123\n", encoding="utf-8")
    config = AppConfig.load({"TUSHARE_TOKEN_PATH": str(token_file)})

    assert config.resolve_tushare_token() == "file-token-123"
    assert config.tushare_token_status() == "present:file"


def test_market_data_bundle_requires_live_current_source_for_decisions():
    bundle = MarketDataBundle(
        trade_date=date(2026, 7, 8),
        data_status=DataStatus.CACHE_ONLY_CURRENT_DATE,
        source_grade=SourceGrade.HISTORICAL_CACHE,
        source_versions={"cache": "2026-07-07"},
        stock_basic=[],
        daily_bars=[],
        daily_basic=[],
        source_runs=[],
    )

    assert bundle.can_generate_decisions is False
    assert bundle.to_pipeline_inputs() == ([], {}, {})
