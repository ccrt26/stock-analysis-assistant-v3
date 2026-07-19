from datetime import date

import pandas as pd
import pytest

from stock_analyzer.evaluation.v3_forward.dossier_supplements import (
    SUPPLEMENT_SCHEMA_VERSION,
    normalize_official_supplements,
    read_official_supplements,
    write_official_supplements,
)
from stock_analyzer.evaluation.v3_forward.ledger import ImmutableEvidenceConflict


FORMATION_DATE = date(2026, 7, 17)
CUTOFF = pd.Timestamp("2026-07-18T03:59:59+08:00")


def _facts(text: str = "临床试验现场管理服务是公司主要业务之一。") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ts_code": "301257.SZ",
                "fact_category": "business_model",
                "fact_text": text,
                "source_title": "普蕊斯2025年年度报告",
                "source_url": "https://www.cninfo.com.cn/finalpage/2026-04-29/1225226898.PDF",
                "published_at": "2026-04-29T00:00:00+08:00",
                "observed_at": "2026-07-19T09:00:00+08:00",
            }
        ]
    )


def test_official_supplements_accept_only_static_facts_visible_by_cutoff():
    result = normalize_official_supplements(
        _facts(), formation_date=FORMATION_DATE, cutoff=CUTOFF
    )

    assert SUPPLEMENT_SCHEMA_VERSION == "v3-forward-official-supplement-01"
    assert result.iloc[0]["formation_date"] == FORMATION_DATE.isoformat()
    assert result.iloc[0]["schema_version"] == SUPPLEMENT_SCHEMA_VERSION
    assert result.iloc[0]["fact_category"] == "business_model"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("source_url", "https://example.com/report.pdf", "official source"),
        ("published_at", "2026-07-19T00:00:00+08:00", "cutoff"),
        ("fact_category", "price_prediction", "category"),
    ],
)
def test_official_supplements_reject_untrusted_future_or_decision_facts(
    field, value, message
):
    facts = _facts()
    facts.loc[0, field] = value

    with pytest.raises(ValueError, match=message):
        normalize_official_supplements(
            facts, formation_date=FORMATION_DATE, cutoff=CUTOFF
        )


def test_official_supplement_bundle_is_immutable_and_readable(tmp_path):
    first = write_official_supplements(
        output_root=tmp_path,
        formation_date=FORMATION_DATE,
        cutoff=CUTOFF,
        facts=_facts(),
        enforce_real_root=False,
    )
    second = write_official_supplements(
        output_root=tmp_path,
        formation_date=FORMATION_DATE,
        cutoff=CUTOFF,
        facts=_facts(),
        enforce_real_root=False,
    )
    loaded, bundle_hash = read_official_supplements(
        tmp_path, formation_date=FORMATION_DATE, enforce_real_root=False
    )

    assert first.idempotent is False
    assert second.idempotent is True
    assert bundle_hash == first.bundle_content_hash
    assert loaded["fact_text"].tolist() == _facts()["fact_text"].tolist()

    with pytest.raises(ImmutableEvidenceConflict):
        write_official_supplements(
            output_root=tmp_path,
            formation_date=FORMATION_DATE,
            cutoff=CUTOFF,
            facts=_facts("公司业务事实被改写。"),
            enforce_real_root=False,
        )
