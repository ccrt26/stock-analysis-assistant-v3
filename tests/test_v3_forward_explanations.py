from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd

from stock_analyzer.evaluation.v3_forward.inputs import FormationInputs


FORMATION_DATE = date(2026, 7, 17)
CUTOFF = datetime(2026, 7, 17, 23, 59, 59, tzinfo=ZoneInfo("Asia/Shanghai"))


def test_formation_inputs_exposes_strict_explanation_frames():
    profiles = pd.DataFrame(
        {
            "ts_code": ["301257.SZ"],
            "available_at": ["2026-07-13T17:15:56Z"],
        }
    )
    announcements = pd.DataFrame(
        {
            "ts_code": ["301257.SZ"],
            "available_at": ["2026-07-01T16:00:00Z"],
        }
    )
    inputs = FormationInputs(
        formation_date=FORMATION_DATE,
        cutoff=CUTOFF,
        market=pd.DataFrame(),
        stocks=pd.DataFrame(),
        hotspots=pd.DataFrame(),
        memberships=pd.DataFrame(),
        company_facts=pd.DataFrame(),
        names={"301257.SZ": "普蕊斯"},
        health_report={},
        input_manifest={},
        sector_catalogs=pd.DataFrame(),
        company_profiles=profiles,
        announcements=announcements,
    )

    assert inputs.company_profiles.equals(profiles)
    assert inputs.announcements.equals(announcements)
    for frame in (inputs.company_profiles, inputs.announcements):
        visible = pd.to_datetime(frame["available_at"], utc=True)
        assert (visible <= pd.Timestamp(inputs.cutoff).tz_convert("UTC")).all()
