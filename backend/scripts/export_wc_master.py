"""
Export plant / SBU / work-centre / machine master data for offline sync.

Does NOT export sessions, drawings, documents, extractions, or route cards.

Usage (from backend/, with .venv active):
  .venv\\Scripts\\python.exe scripts\\export_wc_master.py
  .venv\\Scripts\\python.exe scripts\\export_wc_master.py --out exports\\wc_master.json

Then copy the JSON to the offline PC and run:
  .venv\\Scripts\\python.exe scripts\\import_wc_master.py exports\\wc_master.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# Allow `python scripts/export_wc_master.py` from backend/
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _iso(dt) -> str | None:
    if not dt:
        return None
    if isinstance(dt, datetime):
        return dt.isoformat()
    return str(dt)


def main() -> int:
    parser = argparse.ArgumentParser(description="Export WC/plant master (no extractions).")
    parser.add_argument(
        "--out",
        default="",
        help="Output JSON path (default: exports/wc_master_<timestamp>.json)",
    )
    args = parser.parse_args()

    from pony.orm import db_session, select

    from app.database.connection import connect_to_db
    from app.route_card.models import RcDepartment, RcMachine, RcPlant, RcWorkCenter

    connect_to_db()

    with db_session:
        plants = [
            {
                "code": p.code,
                "name": p.name,
                "description": p.description or "",
                "isActive": bool(p.is_active),
                "sortOrder": int(p.sort_order or 0),
                "workCenterSyncedAt": _iso(p.work_center_synced_at),
            }
            for p in select(p for p in RcPlant)[:]
        ]
        departments = [
            {
                "code": d.code,
                "name": d.name,
                "plantId": (d.plant_id or "").strip(),
                "isActive": bool(d.is_active),
                "sortOrder": int(d.sort_order or 0),
            }
            for d in select(d for d in RcDepartment)[:]
        ]
        work_centers = []
        for w in select(w for w in RcWorkCenter)[:]:
            work_centers.append(
                {
                    "dept": (w.dept or "").strip(),
                    "code": w.code,
                    "name": w.name,
                    "mode": w.mode or "hybrid",
                    "isShared": bool(w.is_shared),
                    "plant": (w.plant or "").strip(),
                    "sapCode": (w.sap_code or "").strip(),
                    "capabilityTags": list(w.capability_tags or []),
                    "matchKeywords": list(w.match_keywords or []),
                    "defaultTool": w.default_tool or "",
                    "isActive": bool(w.is_active),
                    "sortOrder": int(w.sort_order or 0),
                }
            )
        machines = []
        for m in select(m for m in RcMachine)[:]:
            wc = m.work_center
            machines.append(
                {
                    "plant": (m.plant or "").strip(),
                    "workCentre": m.work_centre or "",
                    "wcPlant": (wc.plant or "").strip() if wc else (m.plant or "").strip(),
                    "wcCode": (wc.code if wc else "") or "",
                    "wcIsShared": bool(wc.is_shared) if wc else False,
                    "dept": (m.dept or "").strip(),
                    "code": (m.code or "").strip(),
                    "sapCode": (m.sap_code or "").strip(),
                    "name": m.name,
                    "description": m.description or "",
                    "capabilityTags": list(m.capability_tags or []),
                    "isManualPlaceholder": bool(m.is_manual_placeholder),
                    "isActive": bool(m.is_active),
                    "sortOrder": int(m.sort_order or 0),
                }
            )

    payload = {
        "exportedAt": datetime.utcnow().isoformat() + "Z",
        "kind": "route_card_wc_master",
        "version": 1,
        "note": "Master data only — safe to import without touching extractions.",
        "plants": plants,
        "departments": departments,
        "workCenters": work_centers,
        "machines": machines,
    }

    out = Path(args.out) if args.out else (
        ROOT / "exports" / f"wc_master_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        f"Wrote {out}\n"
        f"  plants={len(plants)} departments={len(departments)} "
        f"workCenters={len(work_centers)} machines={len(machines)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
