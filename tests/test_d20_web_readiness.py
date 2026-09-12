"""Use real ledger/report saving and the Prism browser renderer for the D20 seam."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from tools import render_monitor_web as renderer

ROOT = Path(__file__).resolve().parents[1]


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_same_day_fixed_final_and_current_opinion_render_in_prism(tmp_path):
    fixture = _load(ROOT / "tests/test_forward_monitor.py", "monitor_fixtures")
    sessions = fixture._repair_project(tmp_path)
    before = fixture._prepare(tmp_path, sessions[18])
    ep = before["episodes"][0]
    review = fixture._daily_formal_review(ep["episode_id"], day_number=19, checkpoint=None)
    fixture._record_daily_review_for_snapshot(tmp_path, before, review)
    d20 = fixture._prepare(tmp_path, sessions[19])
    fixture._repair_save_final(tmp_path, d20)
    monitor = tmp_path / "local_archive/forward_monitor"
    history = renderer.scan_history(monitor, sessions[19])[ep["episode_id"]]
    assert len(history) == 2
    assert "finalTwentyDayReview" not in history[0]
    final = history[1]["finalTwentyDayReview"]
    assert final["analysis_date"] == str(sessions[19])
    assert final["final_twenty_day_review"] == fixture._final_review()
    assert final["metrics"]["d20_close_return_since_entry"] == pytest.approx(0.2)
    assert history[1]["currentOpportunity"]["participationReason"]
    assert not renderer.scan_history(monitor, sessions[18])[ep["episode_id"]][0].get("finalTwentyDayReview")
    events = renderer._events_for(ep["action_date"], d20["episodes"][0], history)
    assert any(event[0] == str(sessions[19]) and event[2] == "20日固定结案" for event in events)

    checker = _load(ROOT / "tests/check_prism_atlas_browser.py", "browser_fixtures")
    builder = _load(ROOT / "tools/guanlan-prism/tools/build.py", "prism_builder")
    stock = checker.base_stock(code=ep["ts_code"], name=ep["name"],
                               recDate="2026-08-03", recIndex=0, ref=10.0,
                               days=20, reviews=history)
    second = checker.base_stock(code=ep["ts_code"], name=ep["name"],
                                recDate="2026-08-04", recIndex=1, ref=10.0,
                                days=19, reviews=[history[0]])
    payload = checker.synth_snapshot([stock, second])
    payload.update(analysis_date=str(sessions[19]), as_of=d20["as_of"],
                   date_files=[], review_dates=[str(sessions[19])])
    payload["dates"] = payload["dates"][:20]
    payload["market"] = payload["market"][:20]
    payload["sessionDates"] = [str(day) for day in sessions[:20]]
    for row in payload["stocks"]:
        row["candles"] = [checker.candle(10, 12)] * 20
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        errors = []
        page = browser.new_page()
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.set_content(builder.render_html(payload))
        page.locator(f'[data-open="{ep["ts_code"]}:2026-08-03"]').first.click()
        assert page.locator(".final-review").count() == 1
        assert fixture._final_review()["overall_review"] in page.locator(".final-review").inner_text()
        assert history[1]["currentOpportunity"]["participationReason"] in page.locator(".opinion-panel").inner_text()
        page.locator('[data-day="19"]').first.click()
        assert page.locator(".final-review").count() == 0
        page.locator('[data-action="back"]').first.click()
        page.locator(f'[data-open="{ep["ts_code"]}:2026-08-04"]').first.click()
        assert page.locator(".final-review").count() == 0
        assert errors == []
        page.close()
        browser.close()
