from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from stock_analyzer.data.formal_routes import formal_route_group_ids
from stock_analyzer.data.readiness import RouteCapabilityEvidence


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class CapabilityEvidenceError(RuntimeError):
    pass


class CapabilityBundle(BaseModel):
    model_config = ConfigDict(frozen=True)

    contract_version: str
    generated_at: datetime
    routes: tuple[RouteCapabilityEvidence, ...]


class LocalCapabilityStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def save(self, bundle: CapabilityBundle) -> None:
        _validate_bundle(bundle)
        payload = bundle.model_dump(mode="json")
        envelope = {
            **payload,
            "bundle_hash": _payload_hash(payload),
        }
        serialized = _json_bytes(envelope)
        if self.path.name == "latest.json":
            _atomic_write(self.path, serialized)
        else:
            _write_immutable(self.path, serialized)

    def load(
        self,
        *,
        require_live: bool,
    ) -> dict[str, RouteCapabilityEvidence]:
        try:
            envelope = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CapabilityEvidenceError("capability bundle is missing or malformed") from exc
        if not isinstance(envelope, dict):
            raise CapabilityEvidenceError("capability bundle must be a JSON object")
        expected_hash = envelope.pop("bundle_hash", None)
        if not isinstance(expected_hash, str) or expected_hash != _payload_hash(envelope):
            raise CapabilityEvidenceError("capability bundle hash mismatch")
        try:
            bundle = CapabilityBundle.model_validate(envelope)
        except ValidationError as exc:
            raise CapabilityEvidenceError("capability bundle schema is invalid") from exc
        _validate_bundle(bundle)
        routes = {item.route_id: item for item in bundle.routes}
        if require_live:
            missing_live = sorted(
                route_id
                for route_id, capability in routes.items()
                if not capability.approved_for_live
            )
            if missing_live:
                raise CapabilityEvidenceError(
                    "live capability evidence required for " + ", ".join(missing_live)
                )
        return routes


def _validate_bundle(bundle: CapabilityBundle) -> None:
    known_groups = formal_route_group_ids()
    seen: set[str] = set()
    for capability in bundle.routes:
        if capability.route_id in seen:
            raise CapabilityEvidenceError(
                f"duplicate route evidence: {capability.route_id}"
            )
        seen.add(capability.route_id)
        if capability.contract_version != bundle.contract_version:
            raise CapabilityEvidenceError(
                f"contract version mismatch for route {capability.route_id}"
            )
        expected_group = known_groups.get(capability.route_id)
        if expected_group is None:
            raise CapabilityEvidenceError(
                f"unknown route evidence: {capability.route_id}"
            )
        if capability.group_id != expected_group:
            raise CapabilityEvidenceError(
                f"route group mismatch for {capability.route_id}"
            )
        if not capability.approved:
            raise CapabilityEvidenceError(
                f"route capability is incomplete: {capability.route_id}"
            )
        if not _SHA256.fullmatch(capability.response_hash):
            raise CapabilityEvidenceError(
                f"response hash is invalid for route {capability.route_id}"
            )
        if capability.response_hash == "0" * 64:
            raise CapabilityEvidenceError(
                f"response hash is required for route {capability.route_id}"
            )
        if capability.group_id.value == "official_events_risk":
            for name, digest in capability.semantic_probe_hashes.items():
                if not _SHA256.fullmatch(digest) or digest == "0" * 64:
                    raise CapabilityEvidenceError(
                        "semantic probe hash is invalid for route "
                        f"{capability.route_id}: {name}"
                    )
        if not capability.tested_library_versions:
            raise CapabilityEvidenceError(
                f"library versions are required for route {capability.route_id}"
            )


def _payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _json_bytes(value: Any) -> bytes:
    return (_canonical_json(value) + "\n").encode("utf-8")


def _write_immutable(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        if path.read_bytes() != payload:
            raise CapabilityEvidenceError(
                f"immutable capability evidence already exists: {path.name}"
            ) from exc


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


__all__ = [
    "CapabilityBundle",
    "CapabilityEvidenceError",
    "LocalCapabilityStore",
]
