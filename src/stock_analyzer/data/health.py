from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

from stock_analyzer.config import AppConfig


class HealthStatus(str, Enum):
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"


class HealthItem(BaseModel):
    category: str
    status: HealthStatus
    message: str


class HealthReport(BaseModel):
    items: list[HealthItem]

    def as_lines(self) -> list[str]:
        return [f"{item.category}: {item.status.value} - {item.message}" for item in self.items]


def run_health_checks(config: AppConfig) -> HealthReport:
    token_status = config.tushare_token_status()
    credential_status = HealthStatus.OK if config.resolve_tushare_token() else HealthStatus.FAIL
    supabase_status = HealthStatus.OK if config.has_supabase_config else HealthStatus.WARN
    return HealthReport(
        items=[
            HealthItem(category="credential", status=credential_status, message=f"tushare token {token_status}"),
            HealthItem(category="network", status=HealthStatus.WARN, message="network probe not executed in unit mode"),
            HealthItem(category="api_response", status=supabase_status, message="supabase env checked"),
            HealthItem(category="field_consumability", status=HealthStatus.WARN, message="no live schema sample loaded"),
        ]
    )
