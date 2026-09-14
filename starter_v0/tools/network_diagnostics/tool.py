from __future__ import annotations

import json
from typing import Any

from tools._shared import ROOT, err


NETWORK_DATA_FILE = ROOT / "helpdesk_data" / "network_data.json"


def network_diagnostics(asset_id: str = "") -> dict[str, Any]:
    try:
        data = json.loads(NETWORK_DATA_FILE.read_text(encoding="utf-8"))
        wanted_id = (asset_id or "").strip().upper()
        device = next((item for item in data["diagnostics"] if item["asset_id"] == wanted_id), None)
        
        if device is None:
            return {"tool": "network_diagnostics", "asset_id": wanted_id, "error": "asset_not_found"}
            
        return {
            "tool": "network_diagnostics",
            "asset_id": wanted_id,
            "diagnostics": {key: value for key, value in device.items() if key != "asset_id"},
            "snapshot_at": data["snapshot_at"],
        }
    except Exception as exc:
        return err("network_diagnostics", exc)
