"""Plant organization, work centre and machine data from SAP Zppfm001."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException

from app.config.settings import settings

try:
    from requests import Session
    from requests.auth import HTTPBasicAuth
    from zeep import Client, Settings as ZeepSettings
    from zeep.helpers import serialize_object
    from zeep.transports import Transport
except ImportError:  # SOAP dependencies are optional until SAP is used.
    Session = HTTPBasicAuth = Client = ZeepSettings = serialize_object = Transport = None

logger = logging.getLogger("route_card.sap_org")

DEFAULT_WSDL = (
    "http://perpap2.iscodom.com:8004/sap/bc/srt/wsdl/flv_10002A111AD1/"
    "bndg_url/sap/bc/srt/rfc/sap/zpp_ws_org_details/410/"
    "zpp_ws_org_details/zpp_ws_org_details?sap-client=410"
)
MODE_INDICATORS = {
    "ORG": "POrgInd",
    "WORKCENTER": "PWorkcenterInd",
    "MACHINE": "PMachineInd",
}


def extract_items(container: Any) -> list[dict[str, Any]]:
    if isinstance(container, dict):
        container = container.get("item") or []
    if isinstance(container, dict):
        container = [container]
    if not isinstance(container, list):
        return []
    return [row for row in container if isinstance(row, dict)]


def get_unique_plant_sbu(data: dict | None) -> list[dict[str, str]]:
    """Return the supplied Plant/SBU mapping as JSON rows for the frontend."""
    seen = set()
    result = []
    for row in extract_items((data or {}).get("ItZorg")):
        plant_id = str(row.get("Werks") or "").strip()
        if not plant_id:
            continue
        plant_name = str(row.get("Name2") or "").strip()
        company_code = str(row.get("Bukrs") or "").strip()
        company_name = str(row.get("Butxt") or "").strip()
        sbu_co_code = f"{company_code} ({company_name})"
        sbu_name = str(row.get("Gtext") or "").strip()
        key = (plant_id, plant_name, sbu_co_code, sbu_name)
        if key in seen:
            continue
        seen.add(key)
        result.append({
            "Plant ID": plant_id,
            "Plant Name": plant_name,
            "SBU Co Code (with Location)": sbu_co_code,
            "SBU Name": sbu_name,
        })
    return result


def fetch_sap_data(plant_code: str, mode: str) -> dict[str, Any]:
    plant = (plant_code or "").strip()
    if not plant:
        raise HTTPException(400, "Plant code is required")
    if mode not in MODE_INDICATORS:
        raise ValueError("Invalid mode selected.")
    if Client is None:
        raise HTTPException(503, "SAP SOAP dependencies are missing. Install backend/requirements.txt.")
    username = (settings.SAP_USERNAME or "").strip()
    password = settings.SAP_PASSWORD or ""
    if not username or not password:
        raise HTTPException(503, "Configure SAP_USERNAME and SAP_PASSWORD in the backend environment.")

    timeout = int(settings.SAP_TIMEOUT_SEC or 60)
    try:
        with Session() as session:
            session.auth = HTTPBasicAuth(username, password)
            session.verify = bool(settings.SAP_VERIFY_SSL)
            session.trust_env = bool(settings.SAP_TRUST_ENV)
            transport = Transport(session=session, timeout=timeout, operation_timeout=timeout)
            client = Client(
                wsdl=(settings.SAP_ORG_DETAILS_WSDL or DEFAULT_WSDL).strip(),
                transport=transport,
                settings=ZeepSettings(strict=False),
            )
            logger.info("Requesting SAP %s data for plant %s", mode, plant)
            response = client.service.Zppfm001(**{
                "PWerks": plant,
                MODE_INDICATORS[mode]: "X",
            })
            data = serialize_object(response)
    except Exception as exc:
        logger.exception("SAP %s request failed for plant %s", mode, plant)
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        reason = f"HTTP {status_code}" if status_code is not None else type(exc).__name__
        raise HTTPException(
            502, f"SAP {mode} request failed ({reason}). Check SAP credentials and connectivity."
        ) from exc
    if not isinstance(data, dict):
        raise HTTPException(502, "SAP returned an invalid organization service response.")
    status = data.get("Return") or {}
    for row in status if isinstance(status, list) else [status]:
        if isinstance(row, dict) and str(row.get("Type") or "").upper() in {"E", "A", "X"}:
            raise HTTPException(502, str(row.get("Message") or "SAP rejected the request."))
    return data


def fetch_plant_sbu_mapping(plant_code: str) -> dict[str, Any]:
    items = get_unique_plant_sbu(fetch_sap_data(plant_code, "ORG"))
    return {"plant_code": plant_code.strip(), "count": len(items), "items": items}
