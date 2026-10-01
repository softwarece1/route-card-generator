from io import BytesIO

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import StreamingResponse
from fastapi import APIRouter, HTTPException

from .schemas import OarcToSapRequest
from .sap_mapper import build_sap_payload
from app.auth import get_current_user, require_admin, require_dept_head_or_admin
from app.route_card import op_templates, service
from app.route_card.schemas import (
    AdminUserRoleUpdate,
    FormatLearnRequest,
    ManagedUserCreate,
    ManagedUserResetPassword,
    ManagedUserUpdate,
    OpTemplateCreate,
    OpTemplateDuplicate,
    OpTemplateUpdate,
    RouteCardUpdate,
)

router = APIRouter(prefix="/api/v1/route-card", tags=["route-card"])


@router.post("/sessions")
def create_session(current_user: dict = Depends(get_current_user)):
    return service.create_session(current_user)


@router.get("/sessions/{session_id}")
def get_session(session_id: int, current_user: dict = Depends(get_current_user)):
    return service.get_session(session_id, current_user)


@router.post("/sessions/{session_id}/documents/{role}")
async def upload_session_document(
    session_id: int,
    role: str,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    data, filename, ext = await service.read_upload(file, role=role.lower())
    return service.upload_session_document(
        session_id, role.lower(), data, filename, ext, user=current_user
    )


@router.delete("/sessions/{session_id}/documents/{role}")
def delete_session_document(
    session_id: int,
    role: str,
    documentId: int | None = Query(None),
    current_user: dict = Depends(get_current_user),
):
    return service.delete_session_document(
        session_id, role.lower(), user=current_user, document_id=documentId
    )


@router.get("/sessions/{session_id}/documents/{role}/file")
def download_session_document(
    session_id: int,
    role: str,
    documentId: int | None = Query(None),
    current_user: dict = Depends(get_current_user),
):
    data, filename, content_type = service.session_document_file(
        session_id, role.lower(), current_user, document_id=documentId
    )
    inline = "inline" if filename.lower().endswith(".pdf") else "attachment"
    return StreamingResponse(
        BytesIO(data),
        media_type=content_type,
        headers={"Content-Disposition": f'{inline}; filename="{filename}"'},
    )


@router.post("/sessions/{session_id}/analyze")
def analyze_session(session_id: int, current_user: dict = Depends(get_current_user)):
    return service.analyze_session(session_id, user=current_user)


@router.get("/my/extractions")
def my_extractions(current_user: dict = Depends(get_current_user)):
    """Orders / extractions for the signed-in user."""
    return service.list_my_extractions(current_user)


@router.get("/my/extractions/{session_id}")
def my_extraction_detail(session_id: int, current_user: dict = Depends(get_current_user)):
    return service.get_extraction_detail(session_id, current_user)


@router.get("/admin/users")
def admin_users(_admin: dict = Depends(require_admin)):
    return service.list_admin_users(_admin)


@router.get("/dept/users")
def dept_users(current_user: dict = Depends(require_dept_head_or_admin)):
    """Users in caller's department (admin sees all) with extraction counts."""
    return service.list_dept_users(current_user)


@router.post("/users")
def create_user(
    body: ManagedUserCreate,
    current_user: dict = Depends(require_dept_head_or_admin),
):
    """Admin creates dept_head/engineer; dept_head creates engineers in own dept."""
    return service.create_managed_user(current_user, body.model_dump())


@router.patch("/users/{user_id}")
def update_user(
    user_id: int,
    body: ManagedUserUpdate,
    current_user: dict = Depends(require_dept_head_or_admin),
):
    """Update empId / name / dept / role (role+dept changes are admin-only)."""
    return service.update_managed_user(
        current_user, user_id, body.model_dump(exclude_unset=True)
    )


@router.post("/users/{user_id}/reset-password")
def reset_user_password(
    user_id: int,
    body: ManagedUserResetPassword,
    current_user: dict = Depends(require_dept_head_or_admin),
):
    """Admin or dept_head resets password (dept_head: engineers in own dept only)."""
    return service.reset_managed_user_password(current_user, user_id, body.password)


@router.patch("/admin/users/{user_id}")
def admin_update_user_role(
    user_id: int,
    body: AdminUserRoleUpdate,
    _admin: dict = Depends(require_admin),
):
    return service.update_admin_user_role(_admin, user_id, body.role)


@router.get("/admin/extractions")
def admin_extractions(
    empId: str | None = Query(None),
    dept: str | None = Query(None),
    status: str | None = Query(None),
    fromDate: str | None = Query(None, description="YYYY-MM-DD inclusive"),
    toDate: str | None = Query(None, description="YYYY-MM-DD inclusive"),
    _admin: dict = Depends(require_admin),
):
    return service.list_admin_extractions(
        _admin,
        emp_id=empId,
        dept=dept,
        status=status,
        from_date=fromDate,
        to_date=toDate,
    )


@router.get("/admin/extractions/{session_id}")
def admin_extraction_detail(session_id: int, _admin: dict = Depends(require_admin)):
    return service.get_extraction_detail(session_id, _admin)


@router.get("/formats")
def list_formats(current_user: dict = Depends(get_current_user)):
    return service.get_format_templates()


@router.post("/sessions/{session_id}/formats/learn")
def learn_format(
    session_id: int,
    body: FormatLearnRequest,
    current_user: dict = Depends(get_current_user),
):
    return service.learn_format_from_session(session_id, body.model_dump(), user=current_user)


@router.delete("/formats/{template_id}")
def delete_format(template_id: str, _admin: dict = Depends(require_admin)):
    return service.remove_format_template(template_id)


@router.post("/drawings")
async def upload_drawing(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    data, filename, ext = await service.read_upload(file, role="drawing")
    return service.create_drawing(
        data, filename, ext, uploaded_by=current_user.get("empId") or current_user.get("username")
    )


@router.post("/drawings/{drawing_id}/analyze")
def analyze_drawing(drawing_id: int, current_user: dict = Depends(get_current_user)):
    return service.analyze_drawing(drawing_id)


@router.get("/drawings/{drawing_id}")
def get_drawing(drawing_id: int, current_user: dict = Depends(get_current_user)):
    return service.get_drawing_payload(drawing_id)


@router.get("/drawings/{drawing_id}/file")
def download_drawing_file(drawing_id: int, current_user: dict = Depends(get_current_user)):
    data, filename, content_type = service.drawing_file_meta(drawing_id)
    inline = "inline" if filename.lower().endswith(".pdf") else "attachment"
    return StreamingResponse(
        BytesIO(data),
        media_type=content_type,
        headers={"Content-Disposition": f'{inline}; filename="{filename}"'},
    )


@router.post("/drawings/{drawing_id}/route-card")
def generate_route_card(drawing_id: int, current_user: dict = Depends(get_current_user)):
    return service.regenerate_route(drawing_id)


@router.put("/route-cards/{route_id}")
def update_route_card(
    route_id: int,
    body: RouteCardUpdate,
    current_user: dict = Depends(get_current_user),
):
    return service.update_route(route_id, body.model_dump())


@router.post("/route-cards/{route_id}/draft")
def save_draft(route_id: int, current_user: dict = Depends(get_current_user)):
    return service.set_route_status(route_id, "draft")


@router.post("/route-cards/{route_id}/approve")
def approve_route(route_id: int, current_user: dict = Depends(get_current_user)):
    return service.set_route_status(route_id, "approved")


@router.get("/route-cards/{route_id}/pmf-oarc")
def export_pmf_oarc(
    route_id: int,
    required_qty: int = 1,
    plant: str = "",
    production_order: str = "",
    sale_order: str = "",
    wbs: str = "",
    project_name: str = "",
    current_user: dict = Depends(get_current_user),
):
    """Download-ready JSON for PMF Create Order (operations, LongText, raw materials)."""
    return service.export_route_card_pmf_oarc(
        route_id,
        required_qty=required_qty,
        plant=plant or None,
        production_order=production_order,
        sale_order=sale_order,
        wbs=wbs,
        project_name=project_name,
    )


@router.get("/operation-templates")
def list_operation_templates(
    scope: str | None = Query("own", description="own | other | all"),
    dept: str | None = Query(None),
    current_user: dict = Depends(get_current_user),
):
    return op_templates.list_templates(current_user, scope=scope, dept=dept)


@router.get("/operation-templates/{template_id}")
def get_operation_template(
    template_id: int,
    current_user: dict = Depends(get_current_user),
):
    return op_templates.get_template(template_id, current_user)


@router.post("/operation-templates")
def create_operation_template(
    body: OpTemplateCreate,
    current_user: dict = Depends(require_dept_head_or_admin),
):
    return op_templates.create_template(body.model_dump(), current_user)


@router.put("/operation-templates/{template_id}")
def update_operation_template(
    template_id: int,
    body: OpTemplateUpdate,
    current_user: dict = Depends(require_dept_head_or_admin),
):
    return op_templates.update_template(
        template_id, body.model_dump(exclude_unset=True), current_user
    )


@router.delete("/operation-templates/{template_id}")
def delete_operation_template(
    template_id: int,
    current_user: dict = Depends(require_dept_head_or_admin),
):
    return op_templates.delete_template(template_id, current_user)


@router.post("/operation-templates/{template_id}/duplicate")
def duplicate_operation_template(
    template_id: int,
    body: OpTemplateDuplicate = OpTemplateDuplicate(),
    current_user: dict = Depends(require_dept_head_or_admin),
):
    return op_templates.duplicate_template(
        template_id, body.model_dump(exclude_unset=True), current_user
    )

@router.post("/oarc/to-sap")
def convert_oarc_to_sap(payload: OarcToSapRequest) -> dict:
    """
    Convert frontend OARC JSON into SAP-style JSON.
    """
    try:
        data = payload.model_dump(
            by_alias=True,
            exclude_none=False,
        )

        return build_sap_payload(data)

    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"OARC to SAP mapping failed: {exc}",
        ) from exc