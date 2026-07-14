import plistlib
from pathlib import Path


def test_research_data_launchd_uses_one_fixed_data_only_service_per_stage():
    expected = {
        "close": {"Hour": 18, "Minute": 30},
        "evening": {"Hour": 21, "Minute": 30},
        "next-morning": {"Hour": 8, "Minute": 0},
    }
    paths = sorted(Path("ops/launchd").glob(
        "com.ccrt.stock-analysis-assistant.research-data-*.plist.example"
    ))
    assert len(paths) == 3
    for path in paths:
        stage = path.name.removeprefix(
            "com.ccrt.stock-analysis-assistant.research-data-"
        ).removesuffix(".plist.example")
        data = plistlib.loads(path.read_bytes())
        command = " ".join(data["ProgramArguments"])
        assert data["Label"].endswith(f"research-data-{stage}")
        assert data["StartCalendarInterval"] == expected[stage]
        assert f"--stage {stage}" in command
        assert "--data-date auto" in command
        assert "date +%H" not in command
        assert "case " not in command
        assert "prepare-deploy" not in command
        assert "run-daily-job" not in command
        assert "Supabase" not in command
        assert "Cloudflare" not in command
