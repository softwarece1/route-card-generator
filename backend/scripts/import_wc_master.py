"""
Import plant / SBU / work-centre / machine master from export_wc_master.py JSON.

Safe for offline PCs that already have extractions:
  - Upserts by natural keys (plant code, dept code, plant+WC code, …)
  - Never deletes sessions / drawings / documents / extractions / route cards
  - Does not truncate work_centers (only updates matching rows / inserts new)

Prereq on offline PC:
  1. Deploy latest backend code
  2. Run scripts/sql/07_upgrade_to_current_retain_data.sql once (or start
     backend so migrations_route_card.py runs)
  3. Then:
       .venv\\Scripts\\python.exe scripts\\import_wc_master.py path\\to\\wc_master.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _parse_dt(raw: str | None):
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", ""))
    except ValueError:
        return None


def _find_wc(plant: str, code: str, is_shared: bool, dept: str = ""):
    from pony.orm import select

    from app.route_card.models import RcWorkCenter

    code = (code or "").strip()
    plant = (plant or "").strip()
    dept = (dept or "").strip()
    if not code:
        return None
    if is_shared:
        rows = [
            w
            for w in select(w for w in RcWorkCenter if w.code == code and w.is_shared)[:]
        ]
        return rows[0] if rows else None
    if plant:
        rows = [
            w
            for w in select(
                w for w in RcWorkCenter if w.code == code and (w.plant or "") == plant
            )[:]
        ]
        if rows:
            return rows[0]
    if dept:
        rows = [
            w
            for w in select(
                w
                for w in RcWorkCenter
                if w.code == code and (w.sbu or "") == dept and not w.is_shared
            )[:]
        ]
        return rows[0] if rows else None
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Import WC/plant master JSON (keep extractions).")
    parser.add_argument("json_path", help="Path to wc_master_*.json from export_wc_master.py")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print counts only; do not write",
    )
    args = parser.parse_args()

    path = Path(args.json_path)
    if not path.is_file():
        print(f"File not found: {path}")
        return 1

    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("kind") != "route_card_wc_master":
        print("Not a route_card_wc_master export.")
        return 1

    from pony.orm import commit, db_session, select

    from app.database.connection import connect_to_db
    from app.route_card.models import RcSbu, RcMachine, RcWorkCenter

    connect_to_db()

    stats = {
        "plantsUpserted": 0,
        "sbusUpserted": 0,
        "wcsCreated": 0,
        "wcsUpdated": 0,
        "machinesCreated": 0,
        "machinesUpdated": 0,
    }

    with db_session:
        plants_by_code = {
            str(r.get("code") or "").strip(): r
            for r in (data.get("plants") or [])
            if str(r.get("code") or "").strip()
        }

        for row in data.get("sbus") or data.get("departments") or []:
            code = str(row.get("code") or "").strip()
            if not code:
                continue
            existing = RcSbu.get(code=code)
            if args.dry_run:
                stats["sbusUpserted"] += 1
                continue
            if existing:
                existing.name = row.get("name") or code
                # Always bring across plant mapping from source
                existing.plant_id = str(row.get("plantId") or "").strip()
                existing.is_active = bool(row.get("isActive", True))
                existing.sort_order = int(row.get("sortOrder") or 0)
                synced = _parse_dt(row.get("workCenterSyncedAt"))
                if not synced and existing.plant_id:
                    pr = plants_by_code.get(existing.plant_id) or {}
                    synced = _parse_dt(pr.get("workCenterSyncedAt"))
                if synced:
                    existing.work_center_synced_at = synced
            else:
                RcSbu(
                    code=code,
                    name=row.get("name") or code,
                    plant_id=str(row.get("plantId") or "").strip(),
                    is_active=bool(row.get("isActive", True)),
                    sort_order=int(row.get("sortOrder") or 0),
                )
            stats["sbusUpserted"] += 1

        for row in data.get("workCenters") or []:
            code = str(row.get("code") or "").strip()
            if not code:
                continue
            plant = str(row.get("plant") or "").strip()
            dept = str(row.get("sbu") or "").strip()
            is_shared = bool(row.get("isShared"))
            hit = _find_wc(plant, code, is_shared, dept)
            if args.dry_run:
                if hit:
                    stats["wcsUpdated"] += 1
                else:
                    stats["wcsCreated"] += 1
                continue
            fields = dict(
                sbu=dept,
                name=row.get("name") or code,
                mode=row.get("mode") or "hybrid",
                is_shared=is_shared,
                plant=plant,
                sap_code=str(row.get("sapCode") or "").strip(),
                capability_tags=list(row.get("capabilityTags") or []),
                match_keywords=list(row.get("matchKeywords") or []),
                default_tool=row.get("defaultTool") or "",
                is_active=bool(row.get("isActive", True)),
                sort_order=int(row.get("sortOrder") or 0),
                updated_at=datetime.utcnow(),
            )
            if hit:
                for k, v in fields.items():
                    setattr(hit, k, v)
                stats["wcsUpdated"] += 1
            else:
                RcWorkCenter(code=code, created_at=datetime.utcnow(), **fields)
                stats["wcsCreated"] += 1

        commit()

        for row in data.get("machines") or []:
            name = str(row.get("name") or "").strip()
            if not name:
                continue
            wc_plant = str(row.get("wcPlant") or row.get("plant") or "").strip()
            wc_code = str(row.get("wcCode") or "").strip()
            is_shared = bool(row.get("wcIsShared"))
            dept = str(row.get("sbu") or "").strip()
            wc = _find_wc(wc_plant, wc_code, is_shared, dept) if wc_code else None
            code = str(row.get("code") or "").strip()
            plant = str(row.get("plant") or wc_plant).strip()

            existing = None
            if wc:
                cands = [
                    m
                    for m in select(m for m in RcMachine if m.work_center == wc)[:]
                    if (code and (m.code or "") == code) or ((m.name or "") == name)
                ]
                existing = cands[0] if cands else None
            if not existing and code:
                cands = [
                    m
                    for m in select(
                        m
                        for m in RcMachine
                        if (m.code or "") == code and (m.plant or "") == plant
                    )[:]
                ]
                existing = cands[0] if cands else None

            if args.dry_run:
                if existing:
                    stats["machinesUpdated"] += 1
                else:
                    stats["machinesCreated"] += 1
                continue

            fields = dict(
                plant=plant,
                work_centre=str(row.get("workCentre") or (wc.name if wc else name)),
                work_center=wc,
                sbu=dept,
                code=code,
                sap_code=str(row.get("sapCode") or "").strip(),
                name=name,
                description=row.get("description") or "",
                capability_tags=list(row.get("capabilityTags") or []),
                is_manual_placeholder=bool(row.get("isManualPlaceholder")),
                is_active=bool(row.get("isActive", True)),
                sort_order=int(row.get("sortOrder") or 0),
            )
            if existing:
                for k, v in fields.items():
                    setattr(existing, k, v)
                stats["machinesUpdated"] += 1
            else:
                RcMachine(created_at=datetime.utcnow(), **fields)
                stats["machinesCreated"] += 1

        if not args.dry_run:
            commit()

    mode = "DRY-RUN" if args.dry_run else "IMPORTED"
    print(f"{mode} from {path}")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print("Extractions / sessions were not modified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
