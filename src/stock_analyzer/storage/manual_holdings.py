from __future__ import annotations

import json
from pathlib import Path

from stock_analyzer.domain.models import ManualActionRecord, ManualHolding


class ManualHoldingStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.holdings_path = root / "holdings.json"
        self.actions_path = root / "actions.jsonl"

    def load_holdings(self) -> list[ManualHolding]:
        if not self.holdings_path.exists():
            return []
        payload = json.loads(self.holdings_path.read_text(encoding="utf-8"))
        return [ManualHolding.model_validate(item) for item in payload]

    def save_holdings(self, holdings: list[ManualHolding]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = [holding.model_dump(mode="json") for holding in holdings]
        self.holdings_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def load_actions(self) -> list[ManualActionRecord]:
        if not self.actions_path.exists():
            return []
        return [
            ManualActionRecord.model_validate(json.loads(line))
            for line in self.actions_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def append_action(self, action: ManualActionRecord) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with self.actions_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(action.model_dump(mode="json"), ensure_ascii=False))
            handle.write("\n")
