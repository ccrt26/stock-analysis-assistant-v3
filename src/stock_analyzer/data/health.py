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
    credential_status = HealthStatus.OK if config.tushare_token_path.exists() else HealthStatus.FAIL
    supabase_status = (
        HealthStatus.OK if config.supabase_url and config.supabase_service_role_key else HealthStatus.WARN
    )
    return HealthReport(
        items=[
            HealthItem(category="credential", status=credential_status, message="checked local token path"),
            HealthItem(category="network", status=HealthStatus.WARN, message="network probe not executed in unit mode"),
            HealthItem(category="api_response", status=supabase_status, message="supabase env checked"),
            HealthItem(category="field_consumability", status=HealthStatus.WARN, message="no live schema sample loaded"),
        ]
    )
