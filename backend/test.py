# # # # from __future__ import annotations

# # # # import logging
# # # # import os
# # # # from datetime import date, datetime
# # # # from decimal import Decimal
# # # # from threading import Lock
# # # # from typing import Any, Optional

# # # # import requests
# # # # from fastapi import FastAPI, HTTPException
# # # # from fastapi.middleware.cors import CORSMiddleware
# # # # from fastapi.responses import FileResponse
# # # # from fastapi.staticfiles import StaticFiles
# # # # from pydantic import BaseModel, Field
# # # # from requests import Session
# # # # from requests.auth import HTTPBasicAuth
# # # # from zeep import Client, Settings
# # # # from zeep.helpers import serialize_object
# # # # from zeep.transports import Transport

# # # # logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
# # # # logger = logging.getLogger("sap_oarc_api")

# # # # BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# # # # FRONTEND_DIR = os.path.join(BASE_DIR, os.getenv("FRONTEND_DIR", "frontend _lap"))
# # # # SAP_USERNAME = "BSTCUSR"
# # # # SAP_PASSWORD = "Bstc@1234"
# # # # SAP_VERIFY_SSL = os.getenv("SAP_VERIFY_SSL", "true").lower() == "true"
# # # # SAP_TRUST_ENV = os.getenv("SAP_TRUST_ENV", "true").lower() == "true"
# # # # SAP_TIMEOUT = int(os.getenv("SAP_TIMEOUT", "60"))
# # # # SAP_MAX_ORDERS = int(os.getenv("SAP_MAX_ORDERS", "1111500"))

# # # # # http://perpap2.iscodom.com:8004/sap/bc/srt/wsdl/flv_10002A111AD1/bndg_url/sap/bc/srt/rfc/sap/zpp_ws_org_details/410/zpp_ws_org_details/zpp_ws_org_details?sap-client=410

# # # # WSDL_CONFIG = {
# # # #     "dev": {
# # # #         "list": "http://perpdev1.iscodom.com:8030/sap/bc/srt/wsdl/flv_10002A111AD1/bndg_url/sap/bc/srt/rfc/sap/zpp_oarc_reld_prodorder_list_d/210/zpp_oarc_reld_prodorder_list_d/zpp_oarc_reld_prodorder_list_d?sap-client=210",
# # # #         "detail": "http://perpdev1.iscodom.com:8030/sap/bc/srt/wsdl/flv_10002A111AD1/bndg_url/sap/bc/srt/rfc/sap/zpp_oarc_get_prodorder_data_ds/210/zpp_oarc_get_prodorder_data_ds/zpp_oarc_get_prodorder_data_ds?sap-client=210",
# # # #     },
# # # #     "quality": {
# # # #         "list": "http://perpqa.iscodom.com:8030/sap/bc/srt/wsdl/flv_10002A111AD1/bndg_url/sap/bc/srt/rfc/sap/zpp_oarc_reld_prodorder_list_d/410/zpp_oarc_reld_prodorder_list_d/zpp_oarc_reld_prodorder_list_d?sap-client=410",
# # # #         "detail": "http://perpqa.iscodom.com:8030/sap/bc/srt/wsdl/flv_10002A111AD1/bndg_url/sap/bc/srt/rfc/sap/zpp_oarc_get_prodorder_data_ds/410/zpp_oarc_get_prodorder_data_ds/zpp_oarc_get_prodorder_data_ds?sap-client=410",
# # # #     },
# # # #     "production": {
# # # #         "list": "http://perpap2.iscodom.com:8004/sap/bc/srt/wsdl/flv_10002A111AD1/bndg_url/sap/bc/srt/rfc/sap/zpp_oarc_reld_prodorder_list_d/410/zpp_oarc_reld_prodorder_list_d/zpp_oarc_reld_prodorder_list_d?sap-client=410",
# # # #         "detail": "http://perpap2.iscodom.com:8004/sap/bc/srt/wsdl/flv_10002A111AD1/bndg_url/sap/bc/srt/rfc/sap/zpp_oarc_get_prodorder_data_ds/410/zpp_oarc_get_prodorder_data_ds/zpp_oarc_get_prodorder_data_ds?sap-client=410",
# # # #     },
# # # # }

# # # # for _env in WSDL_CONFIG:
# # # #     for _kind in ("list", "detail"):
# # # #         WSDL_CONFIG[_env][_kind] = os.getenv(f"SAP_ORDER_{_env.upper()}_{_kind.upper()}_WSDL", WSDL_CONFIG[_env][_kind]).strip()


# # # # class OrderSearchRequest(BaseModel):
# # # #     plant_code: str = Field(..., min_length=1, examples=["1190"])
# # # #     from_date: date
# # # #     to_date: date
# # # #     part_number: Optional[str] = None


# # # # def normalize_sap_object(value: Any) -> Any:
# # # #     if isinstance(value, Decimal):
# # # #         return float(value)  # Same contract as original implementation.
# # # #     if isinstance(value, (date, datetime)):
# # # #         return value.isoformat()
# # # #     if isinstance(value, dict):
# # # #         return {key: normalize_sap_object(item) for key, item in value.items()}
# # # #     if isinstance(value, (list, tuple, set)):
# # # #         return [normalize_sap_object(item) for item in value]
# # # #     return value


# # # # def extract_items(container: Any) -> list[dict[str, Any]]:
# # # #     if isinstance(container, dict):
# # # #         container = container.get("item", [])
# # # #     if isinstance(container, dict):
# # # #         container = [container]
# # # #     if not isinstance(container, list):
# # # #         return []
# # # #     return [x for x in container if isinstance(x, dict)]


# # # # def strip_sap_leading_zeros(value: Any) -> Optional[str]:
# # # #     if value is None:
# # # #         return None
# # # #     value = str(value).strip()
# # # #     return value.lstrip("0") or "0" if value else ""


# # # # def sap_status(raw: dict[str, Any]) -> tuple[str, str]:
# # # #     ret = raw.get("Return") or {}
# # # #     if isinstance(ret, list):
# # # #         ret = ret[0] if ret else {}
# # # #     if not isinstance(ret, dict):
# # # #         ret = {}
# # # #     return str(ret.get("Type") or "S"), str(ret.get("Message") or "")


# # # # def format_order_list(raw: dict[str, Any]) -> dict[str, Any]:
# # # #     rows = extract_items(raw.get("ItOrderlist"))
# # # #     orders = []
# # # #     for row in rows:
# # # #         orders.append({
# # # #             "production_order": row.get("Aufnr"),
# # # #             "production_order_display": strip_sap_leading_zeros(row.get("Aufnr")),
# # # #             "plant": row.get("Werks"),
# # # #             "material_number": row.get("Matnr"),
# # # #             "material_number_display": strip_sap_leading_zeros(row.get("Matnr")),
# # # #             "description": row.get("Maktx"),
# # # #             "order_quantity": row.get("Gamng"),
# # # #             "unit": row.get("Gmein"),
# # # #             "finish_date": row.get("Ftrmi"),
# # # #             "delivered_quantity": row.get("Gasmg"),
# # # #             "sales_order": row.get("Kdauf"),
# # # #             "sales_order_item": row.get("Kdpos"),
# # # #             "wbs_element": row.get("Pspel"),
# # # #             "additional_description": row.get("Zmaktx"),
# # # #         })
# # # #     status, message = sap_status(raw)
# # # #     return {"message": message or "Order list fetched", "status": status, "count": len(orders), "orders": orders}


# # # # def format_order_details(raw: dict[str, Any]) -> dict[str, Any]:
# # # #     header = raw.get("WaHeader") or {}
# # # #     if not isinstance(header, dict):
# # # #         header = {}
# # # #     components = extract_items(raw.get("ItComponents"))
# # # #     operations = extract_items(raw.get("ItOperation"))
# # # #     serials = extract_items(raw.get("ItOrdslno"))
# # # #     status, message = sap_status(raw)
# # # #     formatted_components = [{
# # # #         "item_number": r.get("Posnr"), "material_number": r.get("Matnr"),
# # # #         "material_number_display": strip_sap_leading_zeros(r.get("Matnr")),
# # # #         "description": r.get("Maktx"), "required_quantity": r.get("Bdmng"),
# # # #         "withdrawn_quantity": r.get("Romen"), "unit": r.get("Meins"),
# # # #     } for r in components]
# # # #     print(operations)
# # # #     formatted_operations = [{
# # # #         "operation_number": r.get("Vornr"), "operation_description": r.get("Ltxa1"),
# # # #         "work_center": r.get("Arbpl"), "work_center_plant": r.get("WcWerks"),
# # # #         "setup_time": r.get("Setuptime"), "setup_unit": r.get("Setupuom"),
# # # #         "per_piece_time": r.get("Perpiecetime"), "per_piece_unit": r.get("Perpieceuom"),
# # # #         "jump_quantity": r.get("JmpQty"), "total_quantity": r.get("TotQty"),
# # # #         "allowed_time": r.get("AlTime"), "actual_time": r.get("ActTime"),
# # # #         "operation_instructions": r.get("OperationText"),
# # # #         "confirmation_number": r.get("Rueck"), "component_material": r.get("CompMatnr"),
# # # #         "number_of_parts": r.get("NoParts"),
# # # #     } for r in operations]
# # # #     formatted_serials = [{
# # # #         "production_order": r.get("Aufnr"), "serial_number": r.get("Sernr"),
# # # #         "serial_number_display": strip_sap_leading_zeros(r.get("Sernr")),
# # # #     } for r in serials]
# # # #     return {
# # # #         "message": message or "Production order details fetched", "status": status,
# # # #         "header": { 
# # # #             "production_order": header.get("Aufnr"),
# # # #             "production_order_display": strip_sap_leading_zeros(header.get("Aufnr")),
# # # #             "company_code": header.get("Bukrs"), "plant": header.get("Werks"),
# # # #             "material_number": header.get("Matnr"),
# # # #             "material_number_display": strip_sap_leading_zeros(header.get("Matnr")),
# # # #             "material_description": header.get("Maktx"), "required_quantity": header.get("Gamng"),
# # # #             "unit": header.get("Gmein"), "task_list_type": header.get("Plnty"),
# # # #             "routing_group": header.get("Plnnr"), "group_counter": header.get("Plnal"),
# # # #         },
# # # #         "components": formatted_components, "operations": formatted_operations,
# # # #         "serial_numbers": formatted_serials,
# # # #         "counts": {"components": len(formatted_components), "operations": len(formatted_operations), "serial_numbers": len(formatted_serials)},
# # # #     }

# # # # class SAPService:
# # # #     """Per-request lazy SOAP clients. Never share one Zeep client across worker threads."""

# # # #     def __init__(self) -> None:
# # # #         self._clients: dict[str, Client] = {}

# # # #     @staticmethod
# # # #     def _create_client(wsdl_url: str) -> Client:
# # # #         if not SAP_USERNAME or not SAP_PASSWORD:
# # # #             raise RuntimeError("Configure SAP_USERNAME and SAP_PASSWORD in the environment")
# # # #         session = Session()
# # # #         session.auth = HTTPBasicAuth(SAP_USERNAME, SAP_PASSWORD)
# # # #         session.verify = SAP_VERIFY_SSL
# # # #         session.trust_env = SAP_TRUST_ENV
# # # #         session.headers.update({"User-Agent": "SAP-OARC-FastAPI/1.1"})
# # # #         transport = Transport(session=session, timeout=SAP_TIMEOUT, operation_timeout=SAP_TIMEOUT)
# # # #         try:
# # # #             return Client(wsdl=wsdl_url, transport=transport, settings=Settings(strict=False, xml_huge_tree=False))
# # # #         except requests.RequestException as exc:
# # # #             raise RuntimeError(f"SAP WSDL connection failed: {type(exc).__name__}") from exc

# # # #     def _get_client(self, environment: str, service_type: str) -> Client:
# # # #         key = f"{environment}:{service_type}"
# # # #         if key not in self._clients:
# # # #             logger.info("Loading SAP %s %s WSDL", environment, service_type)
# # # #             self._clients[key] = self._create_client(WSDL_CONFIG[environment][service_type])
# # # #         return self._clients[key]

# # # #     def fetch_order_list(self, environment: str, plant_code: str, from_date: str, to_date: str, part_number: Optional[str] = None) -> dict[str, Any]:
# # # #         client = self._get_client(environment, "list")
# # # #         print(client)
# # # #         print("This is client services",client)
# # # #         response = client.service.ZppOarcReldProdorderList(
# # # #             Begda=from_date, Endda=to_date, Matnr=part_number or None, Werks=plant_code
# # # #         )
# # # #         return normalize_sap_object(serialize_object(response))

# # # #     def fetch_order_details(self, environment: str, production_order: str) -> dict[str, Any]:
# # # #         # Send SAP's original order number, including its leading zeroes.
# # # #         client = self._get_client(environment, "detail")
# # # #         response = client.service.ZppOarcGetProdorderData(Aufnr=production_order)
# # # #         return normalize_sap_object(serialize_object(response))


# # # # def validated_search(payload: OrderSearchRequest) -> tuple[str, str, str, Optional[str]]:
# # # #     plant = payload.plant_code.strip()
# # # #     if not plant:
# # # #         raise HTTPException(status_code=422, detail="Plant code is required")
# # # #     if payload.from_date > payload.to_date:
# # # #         raise HTTPException(status_code=400, detail="From date cannot be after To date")
# # # #     part = (payload.part_number or "").strip() or None
# # # #     return plant, payload.from_date.isoformat(), payload.to_date.isoformat(), part


# # # # def fail_sap(endpoint: str, exc: Exception) -> HTTPException:
# # # #     logger.exception("SAP request failed at %s", endpoint)
# # # #     # Prevent credential-bearing URLs / proxy info from leaking in HTTP responses.
# # # #     return HTTPException(status_code=502, detail=f"SAP {endpoint} request failed. Check server logs ({type(exc).__name__}).")


# # # # def list_for(environment: str, payload: OrderSearchRequest) -> dict[str, Any]:
# # # #     plant, start, end, part = validated_search(payload)
# # # #     try:
# # # #         raw = SAPService().(environment, plant, start, end, part)
# # # #         result = format_order_list(raw)
# # # #         result["criteria"] = payload.model_dump(mode="json")
# # # #         return result
# # # #     except Exception as exc:
# # # #         raise fail_sap(f"{environment} list", exc) from exc


# # # # def details_for(environment: str, production_order: str) -> dict[str, Any]:
# # # #     order = production_order.strip()
# # # #     if not order:
# # # #         raise HTTPException(status_code=400, detail="Production order is required")
# # # #     try:
# # # #         result = format_order_details(SAPService().fetch_order_details(environment, order))
# # # #         if result["status"].upper() in ("E", "A", "X"):
# # # #             logger.warning("SAP %s detail rejected order=%r: %s", environment, order, result["message"])
# # # #         return result
# # # #     except Exception as exc:
# # # #         raise fail_sap(f"{environment} detail", exc) from exc

# # # # test = SAPService()
# # # #     # 2. Prepare your parameters
# # # #     # Note: The method expects strings for dates based on your type hints
# # # # env = "PRODUCTION"          # This must exist in your WSDL_CONFIG
# # # # plant = "1190"
# # # # start_dt = "2023-01-01"     # SAP usually expects YYYY-MM-DD strings
# # # # end_dt = "2023-12-31"
# # # # part = "PART-ABC-123"       # Optional: can be None

# # # # try:
# # # #     print(f"Fetching orders for plant {plant}...")
        
# # # #     # 3. Execute the call
# # # #     orders = test.fetch_order_list(
# # # #             environment=env,
# # # #             plant_code=plant,
# # # #             from_date=start_dt,
# # # #             to_date=end_dt,
# # # #             part_number=part
# # # #     )
# # # import os
# # # import logging
# # # from typing import Any, Optional
# # # from requests import Session
# # # from requests.auth import HTTPBasicAuth
# # # from zeep import Client, Settings
# # # from zeep.transports import Transport
# # # from zeep.helpers import serialize_object

# # # # --- CONFIGURATION ---
# # # # Replace these with your actual credentials or set them in your environment
# # # SAP_USERNAME = "BSTCUSR"
# # # SAP_PASSWORD = "Bstc@1234"
# # # WSDL_URL = "http://perpap2.iscodom.com:8004/sap/bc/srt/wsdl/flv_10002A111AD1/bndg_url/sap/bc/srt/rfc/sap/zpp_ws_org_details/410/zpp_ws_org_details/zpp_ws_org_details?sap-client=410"
# # # SAP_VERIFY_SSL = os.getenv("SAP_VERIFY_SSL", "true").lower() == "true"
# # # SAP_TRUST_ENV = os.getenv("SAP_TRUST_ENV", "true").lower() == "true"
# # # SAP_TIMEOUT = int(os.getenv("SAP_TIMEOUT", "60"))
# # # SAP_MAX_ORDERS = int(os.getenv("SAP_MAX_ORDERS", "1111500"))

# # # logging.basicConfig(level=logging.INFO)
# # # logger = logging.getLogger("sap_test")

# # # def fetch_org_details(plant_code: str):
# # #     """
# # #     Hits the SAP WSDL using the plant code (PWerks) 
# # #     and returns the serialized dictionary response.
# # #     """
# # #     if not SAP_USERNAME or not SAP_PASSWORD:
# # #         raise ValueError("Credentials must be provided.")

# # #     # 1. Setup Session with Authentication
# # #     session = Session()
# # #     session.auth = HTTPBasicAuth(SAP_USERNAME, SAP_PASSWORD)
# # #     session.verify = False  # Set to True if you have valid SSL certs
    
# # #     # 2. Setup Zeep Transport
# # #     transport = Transport(session=session, timeout=60)
    
# # #     try:
# # #         # 3. Initialize Client
# # #         client = Client(
# # #             wsdl=WSDL_URL, 
# # #             transport=transport, 
# # #             settings=Settings(strict=False)
# # #         )

# # #         # 4. Call the specific operation found in your WSDL: Zppfm001
# # #         # Based on the WSDL, the input element is Zppfm001
# # #         # The field for plant in the schema is PWerks
# # #         logger.info(f"Fetching details for Plant: {plant_code}")
        
# # #         response = client.service.Zppfm001(
# # #             PWerks=plant_code
# # #         )
# # #         print(response)
# # #         # 5. Convert complex Zeep object to a standard Python dictionary
# # #         return serialize_object(response)

# # #     except Exception as e:
# # #         logger.error(f"An error occurred: {e}")
# # #         return None

# # # if __name__ == "__main__":
# # #     # INPUT: Take plant number from user
# # #     user_input = input("Enter Plant Code (e.g., 1190): ").strip()
    
# # #     if user_input:
# # #         result = fetch_org_details(user_input)
        
# # #         if result:
# # #             print("\n--- SAP Response Received ---")
# # #             import pprint
# # #             pprint.pprint(result)
# # #         else:
# # #             print("\nFailed to retrieve data. Check credentials or Plant Code.")
# # #     else:
# # #         print("Invalid Input.")
# # import os
# # import logging
# # import pprint
# # from requests import Session
# # from requests.auth import HTTPBasicAuth
# # from zeep import Client, Settings
# # from zeep.transports import Transport
# # from zeep.helpers import serialize_object

# # # --- CONFIGURATION ---
# # SAP_USERNAME = "BSTCUSR"
# # SAP_PASSWORD = "Bstc@1234"
# # WSDL_URL = "http://perpap2.iscodom.com:8004/sap/bc/srt/wsdl/flv_10002A111AD1/bndg_url/sap/bc/srt/rfc/sap/zpp_ws_org_details/410/zpp_ws_org_details/zpp_ws_org_details?sap-client=410"

# # logging.basicConfig(level=logging.INFO)
# # logger = logging.getLogger("sap_test")

# # def fetch_org_details(plant_code: str):
# #     if not SAP_USERNAME or not SAP_PASSWORD:
# #         raise ValueError("Credentials must be provided.")

# #     session = Session()
# #     session.auth = HTTPBasicAuth(SAP_USERNAME, SAP_PASSWORD)
# #     session.verify = False 
# #     transport = Transport(session=session, timeout=60)

# #     try:
# #         client = Client(
# #             wsdl=WSDL_URL,
# #             transport=transport,
# #             settings=Settings(strict=False)
# #         )

# #         logger.info(f"Fetching details for Plant: {plant_code}")
        
# #         # Calling the service
# #         # Note: PWerks is defined as char4 in WSDL, ensure input is 4 chars
# #         response = client.service.Zppfm001(PWerks=plant_code)
        
# #         return serialize_object(response)

# #     except Exception as e:
# #         logger.error(f"An error occurred: {e}")
# #         return None
# # def process_sap_response(data):
# #     if not data:
# #         print("No data received from SAP.")
# #         return

# #     # 1. Safely handle ItCrhd
# #     # We use 'or {}' to ensure that if 'ItCrhd' is None, it becomes an empty dict
# #     it_crhd = data.get('ItCrhd') or {}
# #     # If it's a dict, get 'item'. If 'item' is None, default to empty list []
# #     work_centers = it_crhd.get('item') if isinstance(it_crhd, dict) else []
# #     if work_centers is None:
# #         work_centers = []

# #     # 2. Safely handle ItMachine
# #     it_machine = data.get('ItMachine') or {}
# #     machines = it_machine.get('item') if isinstance(it_machine, dict) else []
# #     if machines is None:
# #         machines = []

# #     # 3. Safely handle ItZorg
# #     it_zorg = data.get('ItZorg') or {}
# #     zorg_data = it_zorg.get('item') if isinstance(it_zorg, dict) else []
# #     if zorg_data is None:
# #         zorg_data = []

# #     # --- Now you can iterate without crashing ---
# #     print("\n=== WORK CENTERS (ItCrhd) ===")
# #     if not work_centers:
# #         print("No work centers found.")
# #     for wc in work_centers:
# #         print(wc)

# #     print("\n=== MACHINES (ItMachine) ===")
# #     if not machines:
# #         print("No machines found.")
# #     for m in machines:
# #         print(m)

# #     print("\n=== ZORG (ItZorg) ===")
# #     if not zorg_data:
# #         print("No Zorg data found.")
# #     for z in zorg_data:
# #         print(z)
# # if __name__ == "__main__":
# #     user_input = input("Enter Plant Code (e.g., 1190): ").strip()
    
# #     # SAP WSDL specifies PWerks is char4. 
# #     # If your input is '1190', it works. If '120', pad it:
# #     if len(user_input) < 4:
# #         user_input = user_input.zfill(4)

# #     if user_input:
# #         result = fetch_org_details(user_input)
# #         process_sap_response(result)
# #     else:
# #         print("Invalid Input.")
# import os
# import logging
# import pprint
# from typing import Any, Optional, Dict, List
# from requests import Session
# from requests.auth import HTTPBasicAuth
# from zeep import Client, Settings
# from zeep.transports import Transport
# from zeep.helpers import serialize_object

# # --- CONFIGURATION ---
# SAP_USERNAME = "BSTCUSR"
# SAP_PASSWORD = "Bstc@1234"
# WSDL_URL = "http://perpap2.iscodom.com:8004/sap/bc/srt/wsdl/flv_10002A111AD1/bndg_url/sap/bc/srt/rfc/sap/zpp_ws_org_details/410/zpp_ws_org_details/zpp_ws_org_details?sap-client=410"

# logging.basicConfig(level=logging.INFO)
# logger = logging.getLogger("sap_client")

# def fetch_sap_data(plant_code: str, mode: str) -> Optional[Dict]:
#     """
#     Fetches data from SAP based on the selected mode.
#     Modes: 'ORG', 'WORKCENTER', 'MACHINE'
#     """
#     session = Session()
#     session.auth = HTTPBasicAuth(SAP_USERNAME, SAP_PASSWORD)
#     session.verify = False 
#     transport = Transport(session=session, timeout=60)

#     # UPDATED: These names MUST match the SAP Signature exactly as shown in your error
#     # Signature: PMachineInd, POrgInd, PWerks, PWorkcenterInd
#     mode_map = {
#         'ORG': 'POrgInd',
#         'WORKCENTER': 'PWorkcenterInd',
#         'MACHINE': 'PMachineInd'
#     }

#     if mode not in mode_map:
#         raise ValueError("Invalid mode selected.")

#     indicator_param = mode_map[mode]
    
#     # Construct the payload using the correct SAP parameter names
#     payload = {
#         "PWerks": plant_code,
#         indicator_param: 'X'
#     }

#     try:
#         client = Client(wsdl=WSDL_URL, transport=transport, settings=Settings(strict=False))
#         logger.info(f"Requesting {mode} data for Plant: {plant_code}")
        
#         # The **payload unpacks: {'PWerks': '1191', 'PWorkcenterInd': 'X'}
#         response = client.service.Zppfm001(**payload)
#         return serialize_object(response)

#     except Exception as e:
#         logger.error(f"SAP Connection Error: {e}")
#         return None
# def process_and_display(data: Dict):
#     if not data:
#         print("\n[!] No data returned from SAP.")
#         return

#     # --- 1. ORG DETAILS (IT_ZORG) ---
#     # Expected: BUKRS, GSBER, WERKS, KOSTL, BUTXT, GTEXT, NAME2, MCTXT
#     it_zorg = data.get('ItZorg') or {}
#     zorg_items = it_zorg.get('item') if isinstance(it_zorg, dict) else []
#     if zorg_items is None: zorg_items = []

#     if zorg_items:
#         print("\n" + "="*30)
#         print("   ORGANIZATION DETAILS (ZORG)")
#         print("="*30)
#         for row in zorg_items:
#             print(f"CoCode: {row.get('Bukrs')} ({row.get('Butxt')}) | "
#                   f"BusArea: {row.get('Gsber')} ({row.get('Gtext')}) | "
#                   f"Plant: {row.get('Werks')} ({row.get('Name2')}) | "
#                   f"CostCtr: {row.get('Kostl')} ({row.get('Mctxt')})")

#     # --- 2. WORK CENTERS (IT_CRHD) ---
#     # Expected: ARBPL, WERKS, KTEXT
#     it_crhd = data.get('ItCrhd') or {}
#     crhd_items = it_crhd.get('item') if isinstance(it_crhd, dict) else []
#     if crhd_items is None: crhd_items = []

#     if crhd_items:
#         print("\n" + "="*30)
#         print("      WORK CENTERS (CRHD)")
#         print("="*30)
#         for row in crhd_items:
#             print(f"WC: {row.get('Arbpl')} | Plant: {row.get('Werks')} | Desc: {row.get('Ktext')}")

#     # --- 3. MACHINE DETAILS (IT_MACHINE) ---
#     # Expected: EQUNR, EQTYP, HERST, TYPBZ, SERGE, CALDUEDATE, ARBPL, WERKS, EQKTX
#     it_machine = data.get('ItMachine') or {}
#     machine_items = it_machine.get('item') if isinstance(it_machine, dict) else []
#     if machine_items is None: machine_items = []

#     if machine_items:
#         print("\n" + "="*30)
#         print("       MACHINE DETAILS (MACHINE)")
#         print("="*30)
#         for row in machine_items:
#             print(f"EqNo: {row.get('Equnr')} | Desc: {row.get('Eqktx')} | "
#                   f"Model: {row.get('Typbz')} | Serial: {row.get('Serge')} | "
#                   f"WC: {row.get('Arbpl')} | Calib Date: {row.get('Calduedate')}")

#     if not any([zorg_items, crhd_items, machine_items]):
#         print("\n[!] SAP returned valid response, but all tables were empty for this plant.")

# if __name__ == "__main__":
#     print("BEL SAP Data Retrieval System")
#     print("1. Organization (Plant & Business Area)")
#     print("2. Work Centers")
#     print("3. Machine & Equipment")
    
#     choice = input("\nSelect Mode (1/2/3): ").strip()
#     mode_map = {"1": "ORG", "2": "WORKCENTER", "3": "MACHINE"}
    
#     if choice in mode_map:
#         user_plant = input("Enter Plant Code (e.g., 1190): ").strip()
#         if user_plant:
#             result = fetch_sap_data(user_plant, mode_map[choice])
#             process_and_display(result)
#         else:
#             print("Error: Plant code cannot be empty.")
#     else:
#         print("Error: Invalid selection.")
import os
import logging
import io  # Added to capture text buffer
from typing import Any, Optional, Dict, List
from requests import Session
from requests.auth import HTTPBasicAuth
from zeep import Client, Settings
from zeep.transports import Transport
from zeep.helpers import serialize_object

# --- CONFIGURATION ---
SAP_USERNAME = "BSTCUSR"
SAP_PASSWORD = "Bstc@1234"
WSDL_URL = "http://perpap2.iscodom.com:8004/sap/bc/srt/wsdl/flv_10002A111AD1/bndg_url/sap/bc/srt/rfc/sap/zpp_ws_org_details/410/zpp_ws_org_details/zpp_ws_org_details?sap-client=410"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sap_client")

def get_unique_plant_sbu(data):
    # Get organization details from SAP response
    org_data = (data or {}).get("ItZorg") or {}
    records = org_data.get("item") or []

    if isinstance(records, dict):
        records = [records]

    unique_records = set()
    result = []

    for row in records:
        plant_id = str(row.get("Werks") or "").strip()
        plant_name = str(row.get("Name2") or "").strip()

        company_code = str(row.get("Bukrs") or "").strip()
        company_name = str(row.get("Butxt") or "").strip()

        sbu_name = str(row.get("Gtext") or "").strip()

        # Company code with SAP company description
        sbu_co_code = f"{company_code} ({company_name})"

        # Ignore records without a plant ID
        if not plant_id:
            continue

        # Avoid duplicate plant-SBU combinations
        unique_key = (
            plant_id,
            plant_name,
            sbu_co_code,
            sbu_name
        )

        if unique_key not in unique_records:
            unique_records.add(unique_key)

            result.append({
                "Plant ID": plant_id,
                "Plant Name": plant_name,
                "SBU Co Code (with Location)": sbu_co_code,
                "SBU Name": sbu_name
            })

    # Generate Markdown table
    lines = [
        "| Plant ID | Plant Name | SBU Co Code (with Location) | SBU Name |",
        "|---|---|---|---|"
    ]

    for row in result:
        lines.append(
            f"| {row['Plant ID']} "
            f"| {row['Plant Name']} "
            f"| {row['SBU Co Code (with Location)']} "
            f"| {row['SBU Name']} |"
        )

    return "\n".join(lines)

def fetch_sap_data(plant_code: str, mode: str) -> Optional[Dict]:
    session = Session()
    session.auth = HTTPBasicAuth(SAP_USERNAME, SAP_PASSWORD)
    session.verify = False
    transport = Transport(session=session, timeout=60)

    mode_map = {
        'ORG': 'POrgInd',
        'WORKCENTER': 'PWorkcenterInd',
        'MACHINE': 'PMachineInd'
    }

    if mode not in mode_map:
        raise ValueError("Invalid mode selected.")

    indicator_param = mode_map[mode]
    payload = {
        "PWerks": plant_code,
        indicator_param: 'X'
    }

    try:
        client = Client(wsdl=WSDL_URL, transport=transport, settings=Settings(strict=False))
        logger.info(f"Requesting {mode} data for Plant: {plant_code}")
        response = client.service.Zppfm001(**payload)
        
        return serialize_object(response)
    except Exception as e:
        logger.error(f"SAP Connection Error: {e}")
        return None

def process_and_display(data: Dict, plant_code: str):
    if not data:
        print("\n[!] No data returned from SAP.")
        return

    # Create a string buffer to store the output instead of printing directly
    output = io.StringIO()

    def write_line(text):
        print(text)           # Print to console
        output.write(text + "\n") # Write to buffer

    # --- 1. ORG DETAILS (IT_ZORG) ---
    it_zorg = data.get('ItZorg') or {}
    zorg_items = it_zorg.get('item') if isinstance(it_zorg, dict) else []
    if zorg_items is None: zorg_items = []

    if zorg_items:
        write_line("\n" + "="*30)
        write_line("   ORGANIZATION DETAILS (ZORG)")
        write_line("="*30)
        for row in zorg_items:
            write_line(f"CoCode: {row.get('Bukrs')} ({row.get('Butxt')}) | "
                       f"BusArea: {row.get('Gsber')} ({row.get('Gtext')}) | "
                       f"Plant: {row.get('Werks')} ({row.get('Name2')}) | "
                       f"CostCtr: {row.get('Kostl')} ({row.get('Mctxt')})")

    # --- 2. WORK CENTERS (IT_CRHD) ---
    it_crhd = data.get('ItCrhd') or {}
    crhd_items = it_crhd.get('item') if isinstance(it_crhd, dict) else []
    if crhd_items is None: crhd_items = []

    if crhd_items:
        write_line("\n" + "="*30)
        write_line("      WORK CENTERS (CRHD)")
        write_line("="*30)
        for row in crhd_items:
            write_line(f"WC: {row.get('Arbpl')} | Plant: {row.get('Werks')} | Desc: {row.get('Ktext')}")

    # --- 3. MACHINE DETAILS (IT_MACHINE) ---
    it_machine = data.get('ItMachine') or {}
    machine_items = it_machine.get('item') if isinstance(it_machine, dict) else []
    if machine_items is None: machine_items = []

    if machine_items:
        write_line("\n" + "="*30)
        write_line("       MACHINE DETAILS (MACHINE)")
        write_line("="*30)
        for row in machine_items:
            write_line(f"EqNo: {row.get('Equnr')} | Desc: {row.get('Eqktx')} | "
                       f"Model: {row.get('Typbz')} | Serial: {row.get('Serge')} | "
                       f"WC: {row.get('Arbpl')} | Calib Date: {row.get('Calduedate')}")

    if not any([zorg_items, crhd_items, machine_items]):
        write_line("\n[!] SAP returned valid response, but all tables were empty for this plant.")

    # --- SAVE TO FILE ---
    filename = f"SAP_Report_{plant_code}.txt"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(output.getvalue())
    
    print(f"\n[SUCCESS] Data has been saved to: {os.path.abspath(filename)}")
    output.close()


if __name__ == "__main__":
    print("BEL SAP Data Retrieval System")
    print("1. Organization (Unique Plant & SBU Mapping)")
    print("2. Work Centers")
    print("3. Machine & Equipment")

    choice = input("\nSelect Mode (1/2/3): ").strip()

    mode_map = {
        "1": "ORG",
        "2": "WORKCENTER",
        "3": "MACHINE"
    }

    if choice in mode_map:
        user_plant = input(
            "Enter Plant Code (e.g., 1190): "
        ).strip()

        if user_plant:
            result = fetch_sap_data(
                user_plant,
                mode_map[choice]
            )

            if result is not None:

                if choice == "1":
                    # Get unique Plant-to-SBU mapping
                    table = get_unique_plant_sbu(result)

                    print("\nUNIQUE PLANT & SBU MAPPING")
                    print(table)

                    # Save mapping into a separate file
                    filename = f"Plant_SBU_{user_plant}.md"

                    with open(
                        filename, "w", encoding="utf-8"
                    ) as file:
                        file.write(table)

                    print(f"\nSaved to: {filename}")

                else:
                    # Existing Work Center / Machine output
                    process_and_display(result, user_plant)

            else:
                print("SAP returned no data.")

        else:
            print("Error: Plant code cannot be empty.")

    else:
        print("Error: Invalid selection.")
