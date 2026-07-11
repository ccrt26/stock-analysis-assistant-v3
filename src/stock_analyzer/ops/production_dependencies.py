from __future__ import annotations

import importlib
import os
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any, Callable, Literal

from stock_analyzer.config import AppConfig
from stock_analyzer.data.akshare_formal_client import AkshareFormalEndpointClient
from stock_analyzer.data.capability_store import LocalCapabilityStore
from stock_analyzer.data.cninfo_disclosure_client import CninfoDisclosureClient
from stock_analyzer.data.formal_contracts import (
    FORMAL_CONTRACT_VERSION,
    build_screening_contracts,
    build_target_contracts,
)
from stock_analyzer.data.formal_materializer import screen_formal_market
from stock_analyzer.data.formal_routes import build_formal_route_registry
from stock_analyzer.data.readiness import AcquisitionGroupId
from stock_analyzer.data.tushare_formal_client import TushareFormalEndpointClient
from stock_analyzer.ops.formal_run import (
    FormalAcquisitionGroup,
    FormalPipelineDependencies,
)
from stock_analyzer.ops.formal_strategy_runtime import (
    analyze_formal_inputs,
    express_formal_analysis,
    render_formal_report,
    verify_staged_formal_report,
)
from stock_analyzer.ops.redaction import redact_secrets
from stock_analyzer.storage.evidence_store import LocalEvidenceStore


class ProductionDependencyError(RuntimeError):
    def __init__(self, message: str) -> None:
        super().__init__(redact_secrets(message))


@dataclass(frozen=True)
class ProductionExternalRuntime:
    config: AppConfig
    tushare_pro: Any
    akshare_module: Any
    cninfo_http_client: Any
    capability_store: LocalCapabilityStore
    capability_mode: Literal["recorded", "live"] = "live"
    ledger: Any | None = None
    expression_client: Any | None = None
    enable_concepts: bool = False
    activation_failure_point: str | None = None


def load_default_external_runtime(
    config: AppConfig | None = None,
    *,
    module_loader: Callable[[str], Any] = importlib.import_module,
) -> ProductionExternalRuntime:
    config = config or AppConfig.load()
    try:
        tushare = module_loader("tushare")
        akshare = module_loader("akshare")
        httpx = module_loader("httpx")
    except (ImportError, ModuleNotFoundError) as exc:
        raise ProductionDependencyError(
            "optional data dependencies are missing; install the data extra"
        ) from exc
    token = config.resolve_tushare_token()
    if not token:
        raise ProductionDependencyError("Tushare credential is missing")
    try:
        tushare_pro = tushare.pro_api(token)
    except Exception as exc:
        raise ProductionDependencyError("Tushare client initialization failed") from exc
    capability_store = LocalCapabilityStore(
        config.local_warehouse_dir
        / "formal_evidence"
        / "capabilities"
        / FORMAL_CONTRACT_VERSION
        / "latest.json"
    )
    cninfo_http_client = httpx.Client(
        headers={
            "User-Agent": "stock-analysis-assistant-v3/1.0",
            "Referer": f"{config.cninfo_base_url.rstrip('/')}/",
            "Accept": "application/json",
        },
        follow_redirects=True,
    )
    return ProductionExternalRuntime(
        config=config,
        tushare_pro=tushare_pro,
        akshare_module=akshare,
        cninfo_http_client=cninfo_http_client,
        capability_store=capability_store,
        capability_mode="live",
        enable_concepts=_env_flag("STOCK_ANALYZER_ENABLE_CONCEPTS"),
    )


def build_production_formal_dependencies(
    project_root: Path,
    repository: Any,
    trade_date,
    *,
    runtime: ProductionExternalRuntime | None = None,
) -> FormalPipelineDependencies:
    root = Path(project_root)
    runtime = runtime or load_default_external_runtime(
        AppConfig.load({**os.environ, "PROJECT_ROOT": str(root)})
    )
    if runtime.capability_mode not in {"recorded", "live"}:
        raise ProductionDependencyError("capability mode must be recorded or live")
    capabilities = runtime.capability_store.load(
        require_live=runtime.capability_mode == "live"
    )
    primary = TushareFormalEndpointClient(runtime.tushare_pro)
    backup = AkshareFormalEndpointClient(runtime.akshare_module)
    events_backup = CninfoDisclosureClient(
        primary,
        runtime.cninfo_http_client,
        base_url=runtime.config.cninfo_base_url,
        calls_per_minute=runtime.config.cninfo_calls_per_minute,
        timeout_seconds=runtime.config.cninfo_timeout_seconds,
        max_retries=runtime.config.cninfo_max_retries,
    )
    registry = build_formal_route_registry(
        primary,
        backup,
        primary,
        runtime.config.local_warehouse_dir / "manual" / "holdings.json",
        capabilities,
        events_backup_client=events_backup,
        require_live_capability=runtime.capability_mode == "live",
    )
    screening_contracts = build_screening_contracts(trade_date, ())
    target_contracts = build_target_contracts(
        trade_date,
        (),
        include_concepts=runtime.enable_concepts,
    )
    screening_order = (
        AcquisitionGroupId.CALENDAR_UNIVERSE,
        AcquisitionGroupId.MARKET_DECISION,
    )
    target_order = (
        AcquisitionGroupId.BOARD_INDUSTRY,
        AcquisitionGroupId.CANDIDATE_FUNDAMENTAL,
        AcquisitionGroupId.OFFICIAL_EVENTS_RISK,
        AcquisitionGroupId.MANUAL_HOLDINGS,
        *(
            (AcquisitionGroupId.CONCEPT_THEME,)
            if runtime.enable_concepts
            else ()
        ),
    )
    ledger = runtime.ledger or repository
    _require_formal_ledger(ledger)
    expression = (
        partial(express_formal_analysis, client=runtime.expression_client)
        if runtime.expression_client is not None
        else None
    )
    return FormalPipelineDependencies(
        screening_routes=tuple(
            FormalAcquisitionGroup(
                contract=screening_contracts[group_id],
                routes=registry[group_id],
            )
            for group_id in screening_order
        ),
        target_routes=tuple(
            FormalAcquisitionGroup(
                contract=target_contracts[group_id],
                routes=registry[group_id],
            )
            for group_id in target_order
        ),
        screen=partial(screen_formal_market, repository=repository),
        analyze=partial(analyze_formal_inputs, repository=repository),
        llm_express=expression,
        render=render_formal_report,
        verify=verify_staged_formal_report,
        ledger=ledger,
        evidence_store=LocalEvidenceStore(
            runtime.config.local_warehouse_dir / "formal_evidence"
        ),
        log_root=root / "logs" / "run-daily",
        activation_failure_point=runtime.activation_failure_point,
    )


def _require_formal_ledger(ledger: Any) -> None:
    methods = (
        "register_formal_receipt",
        "prepare_formal_run",
        "pending_hash",
        "activate_formal_run",
        "is_formal_run_active",
        "verify_formal_run_active",
        "discard_pending",
    )
    missing = [name for name in methods if not callable(getattr(ledger, name, None))]
    if missing:
        raise ProductionDependencyError(
            "formal ledger methods are missing: " + ", ".join(missing)
        )


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


__all__ = [
    "ProductionDependencyError",
    "ProductionExternalRuntime",
    "build_production_formal_dependencies",
    "load_default_external_runtime",
]
