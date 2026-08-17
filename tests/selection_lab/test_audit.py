from stock_analyzer.selection_lab.audit import (
    classify_formation_date_uses,
    scan_public_payload,
)


def test_current_prompt_does_not_self_pollute_base_commit_scan():
    documents = {
        "docs/old.md": "开发形成日：2026-01-20",
        "docs/selection_lab/current.md": "最终测试形成日：2026-06-02",
    }

    uses = classify_formation_date_uses(
        documents,
        excluded_paths={"docs/selection_lab/current.md"},
    )

    assert [item.date for item in uses] == ["2026-01-20"]


def test_ordinary_business_date_is_not_a_formation_date():
    uses = classify_formation_date_uses(
        {"docs/a.md": "公告日期为 2026-06-02，不是形成日。"}
    )

    assert uses == []


def test_real_formation_date_context_is_classified():
    uses = classify_formation_date_uses(
        {"docs/a.md": "本轮形成日固定为：2026-04-07，未来已经打开。"}
    )

    assert uses[0].date == "2026-04-07"
    assert uses[0].future_opened is True


def test_public_payload_rejects_local_absolute_path():
    findings = scan_public_payload({"path": "/Users/alice/project/data.parquet"})

    assert "local_absolute_path" in findings


def test_public_payload_rejects_token_key_and_env_file():
    findings = scan_public_payload({"api_token": "secret", "file": ".env.local"})

    assert "token_or_secret" in findings
    assert "env_file" in findings


def test_public_payload_accepts_aggregate_metrics():
    findings = scan_public_payload(
        {"precision_at_5": None, "reason": "no_frozen_candidate_chain"}
    )

    assert findings == []
