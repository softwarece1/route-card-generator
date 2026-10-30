"""SAP production-order client (ported from main1_fixed search_unique_work_center).

Fetches order lists/details from SAP SOAP (or optional HTTP gateway) so work
centres can be synced progressively into the route-card master.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

import httpx

from app.config.settings import settings

logger = logging.getLogger("route_card.sap_oarc")

try:
    import requests
    from requests import Session
    from requests.auth import HTTPBasicAuth
    from zeep import Client, Settings as ZeepSettings
    from zeep.helpers import serialize_object
    from zeep.transports import Transport

    _ZEEP_OK = True
except ImportError:  # pragma: no cover
    _ZEEP_OK = False
    requests = None  # type: ignore
    Session = None  # type: ignore
    HTTPBasicAuth = None  # type: ignore
    Client = None  # type: ignore
    ZeepSettings = None  # type: ignore
    serialize_object = None  # type: ignore
    Transport = None  # type: ignore


DEFAULT_WSDL = {
    "production": {
        "list": (
            "http://perpap2.iscodom.com:8004/sap/bc/srt/wsdl/flv_10002A111AD1/"
            "bndg_url/sap/bc/srt/rfc/sap/zpp_oarc_reld_prodorder_list_d/410/"
            "zpp_oarc_reld_prodorder_list_d/zpp_oarc_reld_prodorder_list_d?sap-client=410"
        ),
        "detail": (
            "http://perpap2.iscodom.com:8004/sap/bc/srt/wsdl/flv_10002A111AD1/"
            "bndg_url/sap/bc/srt/rfc/sap/zpp_oarc_get_prodorder_data_ds/410/"
            "zpp_oarc_get_prodorder_data_ds/zpp_oarc_get_prodorder_data_ds?sap-client=410"
        ),
    },
}


def _wsdl(kind: str) -> str:
    if kind == "list":
        return (settings.SAP_ORDER_PRODUCTION_LIST_WSDL or DEFAULT_WSDL["production"]["list"]).strip()
    return (settings.SAP_ORDER_PRODUCTION_DETAIL_WSDL or DEFAULT_WSDL["production"]["detail"]).strip()


def normalize_sap_object(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: normalize_sap_object(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [normalize_sap_object(item) for item in value]
    return value


def extract_items(container: Any) -> list[dict[str, Any]]:
    if isinstance(container, dict):
        container = container.get("item", [])
    if isinstance(container, dict):
        container = [container]
    if not isinstance(container, list):
        return []
    return [x for x in container if isinstance(x, dict)]


def strip_sap_leading_zeros(value: Any) -> Optional[str]:
    if value is None:
        return None
    value = str(value).strip()
    return value.lstrip("0") or "0" if value else ""


def sap_status(raw: dict[str, Any]) -> tuple[str, str]:
    ret = raw.get("Return") or {}
    if isinstance(ret, list):
        ret = ret[0] if ret else {}
    if not isinstance(ret, dict):
        ret = {}
    return str(ret.get("Type") or "S"), str(ret.get("Message") or "")


def format_order_list(raw: dict[str, Any]) -> dict[str, Any]:
    rows = extract_items(raw.get("ItOrderlist"))
    orders = []
    for row in rows:
        orders.append(
            {
                "production_order": row.get("Aufnr"),
                "production_order_display": strip_sap_leading_zeros(row.get("Aufnr")),
                "plant": row.get("Werks"),
                "material_number": row.get("Matnr"),
                "description": row.get("Maktx"),
            }
        )
    status, message = sap_status(raw)
    return {
        "message": message or "Order list fetched",
        "status": status,
        "count": len(orders),
        "orders": orders,
    }


def format_order_details(raw: dict[str, Any]) -> dict[str, Any]:
    operations = extract_items(raw.get("ItOperation"))
    status, message = sap_status(raw)
    formatted_operations = [
        {
            "operation_number": r.get("Vornr"),
            "operation_description": r.get("Ltxa1"),
            "work_center": r.get("Arbpl"),
            "work_center_plant": r.get("WcWerks"),
        }
        for r in operations
    ]
    return {
        "message": message or "Production order details fetched",
        "status": status,
        "operations": formatted_operations,
    }


class SAPSoapService:
    """Per-request lazy SOAP clients (same contract as main1_fixed.SAPService)."""

    def __init__(self) -> None:
        self._clients: dict[str, Any] = {}

    def _create_client(self, wsdl_url: str) -> Any:
        if not _ZEEP_OK:
            raise RuntimeError("zeep is not installed; pip install zeep requests")
        user = (settings.SAP_USERNAME or "").strip()
        password = settings.SAP_PASSWORD or ""
        if not user or not password:
            raise RuntimeError("Configure SAP_USERNAME and SAP_PASSWORD in the environment")
        session = Session()
        session.auth = HTTPBasicAuth(user, password)
        session.verify = bool(settings.SAP_VERIFY_SSL)
        session.trust_env = bool(settings.SAP_TRUST_ENV)
        session.headers.update({"User-Agent": "RouteCard-SAP-Sync/1.0"})
        timeout = int(settings.SAP_TIMEOUT_SEC or 60)
        transport = Transport(session=session, timeout=timeout, operation_timeout=timeout)
        try:
            return Client(
                wsdl=wsdl_url,
                transport=transport,
                settings=ZeepSettings(strict=False, xml_huge_tree=False),
            )
        except Exception as exc:
            if requests is not None and isinstance(exc, requests.RequestException):
                raise RuntimeError(f"SAP WSDL connection failed: {type(exc).__name__}") from exc
            raise

    def _get_client(self, service_type: str) -> Any:
        if service_type not in self._clients:
            logger.info("Loading SAP production %s WSDL", service_type)
            self._clients[service_type] = self._create_client(_wsdl(service_type))
        return self._clients[service_type]

    def fetch_order_list(
        self,
        plant_code: str,
        from_date: str,
        to_date: str,
        part_number: Optional[str] = None,
    ) -> dict[str, Any]:
        client = self._get_client("list")
        response = client.service.ZppOarcReldProdorderList(
            Begda=from_date, Endda=to_date, Matnr=part_number or None, Werks=plant_code
        )
        return normalize_sap_object(serialize_object(response))

    def fetch_order_details(self, production_order: str) -> dict[str, Any]:
        client = self._get_client("detail")
        response = client.service.ZppOarcGetProdorderData(Aufnr=production_order)
        return normalize_sap_object(serialize_object(response))


class SAPHttpGateway:
    """Optional proxy to a running main1_fixed-style SAP OARC API."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def fetch_order_list(
        self,
        plant_code: str,
        from_date: str,
        to_date: str,
        part_number: Optional[str] = None,
    ) -> dict[str, Any]:
        payload = {
            "plant_code": plant_code,
            "from_date": from_date,
            "to_date": to_date,
            "part_number": part_number,
        }
        with httpx.Client(timeout=float(settings.SAP_TIMEOUT_SEC or 60)) as client:
            r = client.post(f"{self.base_url}/api/orders/production/search", json=payload)
            r.raise_for_status()
            data = r.json()
        # Gateway already returns formatted list; adapt to raw-style consumer
        return {"_formatted": data}

    def fetch_order_details(self, production_order: str) -> dict[str, Any]:
        with httpx.Client(timeout=float(settings.SAP_TIMEOUT_SEC or 60)) as client:
            r = client.get(f"{self.base_url}/api/orders/production/{production_order}")
            r.raise_for_status()
            return {"_formatted": r.json()}


def get_sap_backend():
    gateway = (settings.SAP_OARC_API_BASE_URL or "").strip()
    if gateway:
        return "http", SAPHttpGateway(gateway)
    return "soap", SAPSoapService()


def list_production_orders(
    plant_code: str,
    from_date: str,
    to_date: str,
    part_number: Optional[str] = None,
) -> dict[str, Any]:
    mode, backend = get_sap_backend()
    raw = backend.fetch_order_list(plant_code, from_date, to_date, part_number)
    if mode == "http" and isinstance(raw, dict) and "_formatted" in raw:
        return raw["_formatted"]
    return format_order_list(raw)


def detail_production_order(production_order: str) -> dict[str, Any]:
    mode, backend = get_sap_backend()
    raw = backend.fetch_order_details(production_order)
    if mode == "http" and isinstance(raw, dict) and "_formatted" in raw:
        return raw["_formatted"]
    return format_order_details(raw)
