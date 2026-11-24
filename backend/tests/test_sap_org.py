"""SAP organization mapping and direct work-centre sync, without live SAP/DB."""

from datetime import datetime
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.route_card import plants, sap_org_client as sap, work_centers
from app.route_card.router import router


ORG_ROW = {
    "Werks": " 1190 ", "Name2": " Plant A ", "Bukrs": " 1000 ",
    "Butxt": " BEL ", "Gtext": " SBU A ", "Kostl": "001",
}
MAPPING = {
    "Plant ID": "1190", "Plant Name": "Plant A",
    "SBU Co Code (with Location)": "1000 (BEL)", "SBU Name": "SBU A",
}


def test_mapping_deduplicates_cost_centres_and_preserves_distinct_sbus():
    data = {"ItZorg": {"item": [
        ORG_ROW, {**ORG_ROW, "Kostl": "002"},
        {**ORG_ROW, "Gtext": "SBU B"}, {**ORG_ROW, "Bukrs": "2000"},
        {**ORG_ROW, "Werks": ""}, None,
    ]}}
    assert sap.get_unique_plant_sbu(data) == [
        MAPPING, {**MAPPING, "SBU Name": "SBU B"},
        {**MAPPING, "SBU Co Code (with Location)": "2000 (BEL)"},
    ]


def test_mapping_accepts_single_sap_item():
    assert sap.get_unique_plant_sbu({"ItZorg": {"item": ORG_ROW}}) == [MAPPING]


@pytest.mark.parametrize("data", [None, {}, {"ItZorg": None}, {"ItZorg": {"item": None}}])
def test_empty_mapping(data):
    assert sap.get_unique_plant_sbu(data) == []


@pytest.fixture
def soap(monkeypatch):
    session = MagicMock()
    session.__enter__.return_value = session
    client = MagicMock()
    client.service.Zppfm001.return_value = {"ItZorg": {"item": ORG_ROW}}
    factory = MagicMock(return_value=client)
    monkeypatch.setattr(sap, "Session", MagicMock(return_value=session))
    monkeypatch.setattr(sap, "HTTPBasicAuth", MagicMock())
    monkeypatch.setattr(sap, "Transport", MagicMock())
    monkeypatch.setattr(sap, "ZeepSettings", MagicMock())
    monkeypatch.setattr(sap, "Client", factory)
    monkeypatch.setattr(sap, "serialize_object", lambda value: value)
    monkeypatch.setattr(sap.settings, "SAP_USERNAME", "test-user")
    monkeypatch.setattr(sap.settings, "SAP_PASSWORD", "test-password")
    return client, session, factory


@pytest.mark.parametrize("mode,indicator", [
    ("ORG", "POrgInd"), ("WORKCENTER", "PWorkcenterInd"), ("MACHINE", "PMachineInd"),
])
def test_direct_sap_service_uses_selected_indicator_and_closes_session(soap, mode, indicator):
    client, session, _ = soap
    assert sap.fetch_sap_data(" 1190 ", mode) == {"ItZorg": {"item": ORG_ROW}}
    client.service.Zppfm001.assert_called_once_with(PWerks="1190", **{indicator: "X"})
    session.__exit__.assert_called_once()


def test_soap_failure_is_reported_as_upstream_error(soap):
    client, session, _ = soap
    client.service.Zppfm001.side_effect = TimeoutError("unreachable")
    with pytest.raises(HTTPException) as exc:
        sap.fetch_sap_data("1190", "ORG")
    assert exc.value.status_code == 502
    session.__exit__.assert_called_once()


def test_http_error_includes_upstream_status_for_frontend(soap):
    error = RuntimeError("Service Unavailable")
    error.response = MagicMock(status_code=503)
    soap[0].service.Zppfm001.side_effect = error
    with pytest.raises(HTTPException) as exc:
        sap.fetch_sap_data("1190", "ORG")
    assert "HTTP 503" in exc.value.detail


@pytest.mark.parametrize("response", [None, {"Return": {"Type": "E", "Message": "Rejected"}}])
def test_invalid_or_rejected_sap_response_is_not_success(soap, response):
    soap[0].service.Zppfm001.return_value = response
    with pytest.raises(HTTPException) as exc:
        sap.fetch_sap_data("1190", "ORG")
    assert exc.value.status_code == 502


def test_missing_credentials_are_reported_without_connecting(soap, monkeypatch):
    monkeypatch.setattr(sap.settings, "SAP_PASSWORD", "")
    with pytest.raises(HTTPException) as exc:
        sap.fetch_sap_data("1190", "ORG")
    assert exc.value.status_code == 503
    soap[2].assert_not_called()


@pytest.fixture
def sync_stubs(monkeypatch):
    fetch = MagicMock(side_effect=lambda plant, mode: (
        {"ItZorg": {"item": ORG_ROW}} if mode == "ORG" else {"ItCrhd": {"item": [
            {"Arbpl": "WC1", "Ktext": "Assembly", "Werks": "1190"},
            {"Arbpl": " wc1 ", "Ktext": "Assembly", "Werks": "1190"},
            {"Arbpl": "WC2", "Ktext": "Testing", "Werks": "1190"},
            {"Arbpl": "OTHER", "Werks": "1200"}, {"Arbpl": ""},
        ]}}
    ))
    upsert = MagicMock(side_effect=[({}, True), ({}, False)])
    stamp = MagicMock()
    monkeypatch.setattr(sap, "fetch_sap_data", fetch)
    monkeypatch.setattr(work_centers, "ensure_sap_work_center", upsert)
    monkeypatch.setattr(plants, "mark_work_center_synced", stamp)
    monkeypatch.setattr(plants, "get_work_center_synced_at", lambda plant: datetime(2026, 11, 19))
    return fetch, upsert, stamp


def test_sync_imports_direct_work_centres_with_descriptions_and_mapping(sync_stubs):
    fetch, upsert, stamp = sync_stubs
    result = work_centers.sync_work_centers_from_sap({"role": "admin"}, plant_code="1190")
    assert [call.args for call in fetch.call_args_list] == [("1190", "ORG"), ("1190", "WORKCENTER")]
    assert [(call.kwargs["sap_code"], call.kwargs["name"]) for call in upsert.call_args_list] == [
        ("WC1", "Assembly"), ("WC2", "Testing"),
    ]
    assert result["plant_sbu"] == [MAPPING]
    assert result["created_count"] == result["existing_count"] == 1
    assert result["work_centers"] == ["WC1", "WC2"]
    assert result["status"] == "S"
    stamp.assert_called_once_with("1190")


def test_partial_sync_reports_work_centre_failures_without_stamping_success(sync_stubs):
    _, upsert, stamp = sync_stubs
    upsert.side_effect = [({}, True), HTTPException(400, "Invalid work centre")]
    result = work_centers.sync_work_centers_from_sap({"role": "admin"}, plant_code="1190")
    assert result["status"] == "P"
    assert result["failed_work_centers"] == [{"work_center": "WC2", "message": "Invalid work centre"}]
    assert result["plant_sbu"] == [MAPPING]
    stamp.assert_not_called()


def test_empty_work_centres_do_not_stamp_success(sync_stubs):
    fetch, upsert, stamp = sync_stubs
    fetch.side_effect = [{"ItZorg": {"item": ORG_ROW}}, {"ItCrhd": None}]
    result = work_centers.sync_work_centers_from_sap({"role": "admin"}, plant_code="1190")
    assert result["count"] == 0
    assert result["plant_sbu"] == [MAPPING]
    upsert.assert_not_called()
    stamp.assert_not_called()


@pytest.fixture
def api_client(monkeypatch):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: {"role": "admin", "sbu": "SBU A"}
    monkeypatch.setattr(plants, "resolve_sync_plant_code", lambda user, plant: plant or "1190")
    with TestClient(app) as client:
        yield client, app


def test_mapping_endpoint_exposes_rows_for_frontend(api_client, sync_stubs):
    client, _ = api_client
    response = client.get("/api/v1/route-card/plant-sbu", params={"plant": "1190"})
    assert response.status_code == 200
    assert response.json() == {"plant_code": "1190", "count": 1, "items": [MAPPING]}


def test_sync_endpoint_needs_only_plant_code(api_client, sync_stubs):
    response = api_client[0].post("/api/v1/route-card/work-centers/sync-from-sap", json={"plantCode": "1190"})
    assert response.status_code == 200
    assert response.json()["plant_sbu"] == [MAPPING]
    assert response.json()["created_count"] == 1


def test_mapping_endpoint_preserves_role_access(api_client, sync_stubs):
    client, app = api_client
    app.dependency_overrides[get_current_user] = lambda: {"role": "engineer"}
    assert client.get("/api/v1/route-card/plant-sbu").status_code == 403
    sync_stubs[0].assert_not_called()
