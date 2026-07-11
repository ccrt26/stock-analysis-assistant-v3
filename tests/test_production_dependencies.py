from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from stock_analyzer.config import AppConfig
from stock_analyzer.data.akshare_formal_client import AkshareFormalEndpointClient
from stock_analyzer.data.capability_store import (
    CapabilityBundle,
    CapabilityEvidenceError,
    LocalCapabilityStore,
    WarehouseCapabilityStore,
)
from stock_analyzer.data.cninfo_disclosure_client import CninfoDisclosureClient
from stock_analyzer.data.formal_routes import formal_route_group_ids
from stock_analyzer.data.readiness import (
    AcquisitionGroupId,
    CapabilityEvidenceKind,
    RouteCapabilityEvidence,
)
from stock_analyzer.ops.activation import InMemoryFormalLedger
from stock_analyzer.ops.production_dependencies import (
    ProductionDependencyError,
    ProductionExternalRuntime,
    build_production_formal_dependencies,
    load_default_external_runtime,
)
from stock_analyzer.ops.codex_expression_client import CodexExpressionClient
from stock_analyzer.ops.job import _default_run_daily
from stock_analyzer.storage.repositories import InMemoryAnalysisRepository
from stock_analyzer.storage.formal_warehouse import FormalWarehouse
from tests.test_akshare_formal_client import RecordedAkshare
from tests.test_formal_materializer import TARGET
from tests.test_tushare_formal_client import RecordedTusharePro


NOW = datetime(2026, 7, 10, 16, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


class RecordedHttpResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload


class RecordedCninfoHttp:
    def __init__(
        self,
        *,
        invalid_timestamp=False,
        no_empty=False,
        no_populated=False,
        route_empty=False,
    ):
        self.invalid_timestamp = invalid_timestamp
        self.no_empty = no_empty
        self.no_populated = no_populated
        self.route_empty = route_empty
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return RecordedHttpResponse(
            {
                "stockList": [
                    {
                        "code": code,
                        "orgId": f"org-{code}",
                        "zwjc": f"录制公司-{code}",
                        "category": "A股",
                    }
                    for code in ("600000", "600001")
                ]
            }
        )

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        data = kwargs["data"]
        code = data["stock"].split(",", 1)[0] if data["stock"] else "600000"
        populated = not self.no_populated and not data["category"] and (
            data["stock"] == "" or code == "600000" or self.no_empty
        )
        if self.route_empty and data["stock"]:
            populated = False
        if not populated:
            return RecordedHttpResponse(
                {"totalAnnouncement": 0, "announcements": []}
            )
        published = int(
            datetime(2026, 7, 10, 15, 31, 2, 123000, tzinfo=NOW.tzinfo).timestamp()
            * 1000
        )
        if self.invalid_timestamp:
            published = "2026-07-10"
        row = {
            "secCode": code,
            "secName": f"录制公司-{code}",
            "orgId": f"org-{code}",
            "announcementId": f"recorded-{code}",
            "announcementTitle": "录制精确时间公告",
            "announcementTime": published,
            "adjunctUrl": f"finalpage/2026-07-10/recorded-{code}.PDF",
        }
        return RecordedHttpResponse(
            {"totalAnnouncement": 1, "announcements": [row]}
        )


class RecordedExpressionClient:
    def express(self, payload):
        from tests.test_formal_narrative import _valid_narrative

        return _valid_narrative(payload)


def recorded_external_runtime(tmp_path, *, mode="recorded"):
    capability_path = tmp_path / "capabilities.json"
    routes = tuple(
        RouteCapabilityEvidence(
            route_id=route_id,
            group_id=group_id,
            contract_version="formal-v2",
            full_contract_tested=True,
            field_semantics_verified=True,
            full_universe_verified=True,
            post_close_verified=True,
            tested_at=NOW,
            evidence_kind=CapabilityEvidenceKind.RECORDED,
            response_hash=f"{index + 1:064x}",
            tested_library_versions={"recorded": "2026-07-10"},
            semantic_probe_hashes=(
                {
                    "populated_precise_time": "e" * 64,
                    "empty_coverage": "f" * 64,
                }
                if group_id is AcquisitionGroupId.OFFICIAL_EVENTS_RISK
                else {}
            ),
        )
        for index, (route_id, group_id) in enumerate(formal_route_group_ids().items())
        if group_id is not AcquisitionGroupId.MANUAL_HOLDINGS
    )
    store = LocalCapabilityStore(capability_path)
    store.save(
        CapabilityBundle(
            contract_version="formal-v2",
            generated_at=NOW,
            routes=routes,
        )
    )
    manual = tmp_path / "local_warehouse" / "manual"
    manual.mkdir(parents=True)
    (manual / "holdings.json").write_text("[]\n", encoding="utf-8")
    config = AppConfig(
        project_root=tmp_path,
        reports_dir=tmp_path / "reports",
        local_warehouse_dir=tmp_path / "local_warehouse",
        local_archive_dir=tmp_path / "local_archive",
    )
    return ProductionExternalRuntime(
        config=config,
        tushare_pro=RecordedTusharePro(),
        akshare_module=RecordedAkshare(),
        cninfo_http_client=RecordedCninfoHttp(),
        capability_store=store,
        capability_mode=mode,
        ledger=InMemoryFormalLedger(),
        expression_client=RecordedExpressionClient(),
    )


def test_recorded_runtime_builds_complete_real_dependencies_without_high_level_monkeypatch(tmp_path):
    runtime = recorded_external_runtime(tmp_path)
    dependencies = build_production_formal_dependencies(
        tmp_path,
        InMemoryAnalysisRepository(),
        TARGET,
        runtime=runtime,
    )

    assert {group.contract.group_id for group in dependencies.screening_routes} == {
        AcquisitionGroupId.CALENDAR_UNIVERSE,
        AcquisitionGroupId.MARKET_DECISION,
    }
    assert {group.contract.group_id for group in dependencies.target_routes} == {
        AcquisitionGroupId.BOARD_INDUSTRY,
        AcquisitionGroupId.CANDIDATE_FUNDAMENTAL,
        AcquisitionGroupId.OFFICIAL_EVENTS_RISK,
        AcquisitionGroupId.MANUAL_HOLDINGS,
    }
    assert callable(dependencies.screen) and callable(dependencies.analyze)
    assert callable(dependencies.render) and callable(dependencies.verify)
    assert isinstance(dependencies.evidence_store, FormalWarehouse)
    assert runtime.tushare_pro.calls == []
    assert runtime.akshare_module.calls == []


def test_production_factory_rejects_runtime_without_expression_client(tmp_path):
    runtime = replace(recorded_external_runtime(tmp_path), expression_client=None)
    assert runtime.expression_client is None

    with pytest.raises(ProductionDependencyError, match="Codex expression client"):
        build_production_formal_dependencies(
            tmp_path,
            InMemoryAnalysisRepository(),
            TARGET,
            runtime=runtime,
        )


def test_default_external_runtime_constructs_codex_expression_client(tmp_path):
    config = AppConfig(
        project_root=tmp_path,
        tushare_token="recorded-token",
        local_warehouse_dir=tmp_path / "local_warehouse",
    )
    modules = {
        "tushare": type("Tushare", (), {"pro_api": staticmethod(lambda token: object())}),
        "akshare": object(),
        "httpx": type("Httpx", (), {"Client": staticmethod(lambda **kwargs: object())}),
    }

    runtime = load_default_external_runtime(config, module_loader=modules.__getitem__)

    assert isinstance(runtime.expression_client, CodexExpressionClient)
    assert isinstance(runtime.capability_store, WarehouseCapabilityStore)
    assert isinstance(runtime.capability_store.warehouse, FormalWarehouse)


def test_factory_uses_direct_cninfo_for_event_backup_and_akshare_elsewhere(tmp_path):
    runtime = recorded_external_runtime(tmp_path)
    dependencies = build_production_formal_dependencies(
        tmp_path,
        InMemoryAnalysisRepository(),
        TARGET,
        runtime=runtime,
    )

    targets = {
        group.contract.group_id: group.routes
        for group in dependencies.target_routes
    }
    assert isinstance(
        targets[AcquisitionGroupId.OFFICIAL_EVENTS_RISK].backup.client,
        CninfoDisclosureClient,
    )
    assert isinstance(
        targets[AcquisitionGroupId.BOARD_INDUSTRY].backup.client,
        AkshareFormalEndpointClient,
    )


def test_default_runtime_builds_cninfo_http_client_without_secret_headers(tmp_path):
    captured = {}

    class FakeTushare:
        @staticmethod
        def pro_api(token):
            return object()

    class FakeHttpx:
        class Client:
            def __init__(self, **kwargs):
                captured.update(kwargs)
                self.headers = kwargs.get("headers", {})

    modules = {
        "tushare": FakeTushare(),
        "akshare": object(),
        "httpx": FakeHttpx(),
    }
    runtime = load_default_external_runtime(
        AppConfig(
            project_root=tmp_path,
            local_warehouse_dir=tmp_path / "local_warehouse",
            tushare_token="secret-sentinel",
        ),
        module_loader=modules.__getitem__,
    )

    assert runtime.cninfo_http_client is not None
    assert captured["follow_redirects"] is True
    header_names = {name.lower() for name in captured["headers"]}
    assert header_names == {"user-agent", "referer", "accept"}
    assert "secret-sentinel" not in str(captured)


def test_live_runtime_rejects_recorded_capability_before_provider_call(tmp_path):
    runtime = recorded_external_runtime(tmp_path, mode="live")
    with pytest.raises(CapabilityEvidenceError, match="live capability evidence required"):
        build_production_formal_dependencies(
            tmp_path,
            InMemoryAnalysisRepository(),
            TARGET,
            runtime=runtime,
        )
    assert runtime.tushare_pro.calls == []
    assert runtime.akshare_module.calls == []


def test_factory_requires_strong_formal_activation_readback(tmp_path):
    runtime = recorded_external_runtime(tmp_path)
    runtime.ledger.verify_formal_run_active = None

    with pytest.raises(
        ProductionDependencyError,
        match="verify_formal_run_active",
    ):
        build_production_formal_dependencies(
            tmp_path,
            InMemoryAnalysisRepository(),
            TARGET,
            runtime=runtime,
        )


def test_default_factory_reports_missing_optional_packages_without_secret_values(tmp_path):
    config = AppConfig(
        project_root=tmp_path,
        tushare_token="secret-sentinel",
        tushare_token_path=tmp_path / "must-not-read-token",
    )

    def missing_module(name):
        raise ModuleNotFoundError(name)

    with pytest.raises(ProductionDependencyError, match="optional data dependencies") as raised:
        load_default_external_runtime(config, module_loader=missing_module)
    assert "secret-sentinel" not in str(raised.value)

    class FailingTushare:
        @staticmethod
        def pro_api(token):
            raise RuntimeError(f"provider echoed {token}")

    modules = {
        "tushare": FailingTushare(),
        "akshare": object(),
        "httpx": object(),
    }
    with pytest.raises(ProductionDependencyError, match="client initialization failed") as raised:
        load_default_external_runtime(config, module_loader=modules.__getitem__)
    assert "secret-sentinel" not in str(raised.value)


def test_job_default_run_uses_factory_and_stable_formal_date_run_id(monkeypatch, tmp_path):
    runtime = recorded_external_runtime(tmp_path)
    captured = []
    expected = object()

    def recording_runner(trade_date, report_cutoff, dependencies, run_id=None):
        captured.append((trade_date, report_cutoff, dependencies, run_id))
        return expected

    monkeypatch.setattr("stock_analyzer.ops.job.run_formal_strategy_v2", recording_runner)

    result = _default_run_daily(
        tmp_path,
        InMemoryAnalysisRepository(),
        TARGET,
        runtime=runtime,
    )

    assert result is expected
    assert captured[0][0] == TARGET
    assert captured[0][1].tzinfo is not None
    assert captured[0][1].hour == 18
    assert captured[0][1].minute == 30
    assert captured[0][3] == "formal-2026-07-10"
    assert runtime.tushare_pro.calls == []
    assert runtime.akshare_module.calls == []
