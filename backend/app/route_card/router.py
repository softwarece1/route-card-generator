from io import BytesIO
import asyncio

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from fastapi import APIRouter, HTTPException

from .schemas import OarcToSapRequest
from .sap_mapper import build_sap_payload
from app.auth import get_current_user, require_admin, require_dept_head_or_admin
from app.route_card import op_templates, service
from app.route_card.analyze_jobs import AnalysisCancelled, cancel_job, end_job, start_job
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
async def analyze_session(
    session_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Run analysis. Cancels Ollama work if the client disconnects or /analyze/cancel is called.

    Optional JSON body: { \"vlmPageIndexes\": [1,2,3], \"async\": false }
    When async=true, enqueues a durable job and returns {jobId,...}.
    """
    body: dict = {}
    try:
        if (request.headers.get("content-type") or "").startswith("application/json"):
            body = await request.json() or {}
    except Exception:
        body = {}
    vlm_pages = body.get("vlmPageIndexes") or body.get("vlm_page_indexes")
    if vlm_pages is not None and not isinstance(vlm_pages, list):
        raise HTTPException(400, "vlmPageIndexes must be a list of page numbers")
    if body.get("async") or body.get("enqueue"):
        from app.route_card import job_queue

        return job_queue.enqueue_analyze(session_id, current_user, vlm_page_indexes=vlm_pages)

    def work():
        job = start_job(session_id)
        try:
            return service.analyze_session(
                session_id,
                user=current_user,
                cancel_event=job.cancel,
                vlm_page_indexes=vlm_pages,
            )
        finally:
            end_job(session_id)

    task = asyncio.create_task(asyncio.to_thread(work))
    try:
        while not task.done():
            if await request.is_disconnected():
                cancel_job(session_id)
                break
            await asyncio.sleep(0.4)
        return await task
    except AnalysisCancelled:
        raise HTTPException(status_code=409, detail="Analysis cancelled") from None


@router.post("/sessions/{session_id}/analyze/cancel")
def cancel_analyze_session(
    session_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Stop an in-flight analyze for this session (closes Ollama connection)."""
    # Auth: ensure user can access the session when it exists
    try:
        service.get_session(session_id, current_user)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
    stopped = cancel_job(session_id)
    return {"sessionId": session_id, "cancelled": stopped}


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


@router.get("/admin/uploads")
def admin_uploads(
    empId: str | None = Query(None),
    dept: str | None = Query(None),
    status: str | None = Query(None),
    fromDate: str | None = Query(None, description="YYYY-MM-DD inclusive"),
    toDate: str | None = Query(None, description="YYYY-MM-DD inclusive"),
    _admin: dict = Depends(require_admin),
):
    """Session-wise uploaded documents for admin browse / download."""
    return service.list_admin_uploads(
        _admin,
        emp_id=empId,
        dept=dept,
        status=status,
        from_date=fromDate,
        to_date=toDate,
    )


@router.get("/admin/uploads/{session_id}")
def admin_upload_session(session_id: int, _admin: dict = Depends(require_admin)):
    return service.get_admin_upload_session(session_id, _admin)


@router.get("/admin/documents/{document_id}/file")
def admin_document_download(document_id: int, _admin: dict = Depends(require_admin)):
    data, filename, content_type = service.admin_document_file(document_id, _admin)
    inline = "inline" if filename.lower().endswith((".pdf", ".tif", ".tiff")) else "attachment"
    return StreamingResponse(
        BytesIO(data),
        media_type=content_type,
        headers={"Content-Disposition": f'{inline}; filename="{filename}"'},
    )


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
    return service.update_route(route_id, body.model_dump(), user=current_user)


@router.post("/route-cards/{route_id}/draft")
def save_draft(route_id: int, current_user: dict = Depends(get_current_user)):
    return service.set_route_status(route_id, "draft", user=current_user)


@router.post("/route-cards/{route_id}/approve")
def approve_route(
    route_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user),
    adminOverride: bool = Query(False),
):
    return service.set_route_status(
        route_id,
        "approved",
        user=current_user,
        admin_override=adminOverride,
    )


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

@router.get("/sessions/{session_id}/review-flags")
def session_review_flags(session_id: int, current_user: dict = Depends(get_current_user)):
    from app.route_card import review

    service.get_session(session_id, current_user)
    return {"items": review.list_flags_for_session(session_id)}


@router.get("/route-cards/{route_id}/review-flags")
def route_review_flags(route_id: int, current_user: dict = Depends(get_current_user)):
    from app.route_card import review

    return {"items": review.list_flags_for_route(route_id, current_user)}


@router.patch("/review-flags/{flag_id}")
def patch_review_flag(
    flag_id: int,
    resolved: bool = Query(True),
    current_user: dict = Depends(get_current_user),
):
    from app.route_card import audit, review

    out = review.resolve_flag(flag_id, current_user, resolved=resolved)
    audit.record_audit(
        action="resolve_flag" if resolved else "unresolve_flag",
        user=current_user,
        route_card_id=out.get("routeCardId"),
        session_id=out.get("sessionId"),
        detail={"flagId": flag_id},
    )
    return out


@router.get("/sessions/{session_id}/item-link-report")
def item_link_report(session_id: int, current_user: dict = Depends(get_current_user)):
    from app.route_card import review

    service.get_session(session_id, current_user)
    return review.item_link_report_for_session(session_id, current_user)


@router.post("/sessions/{session_id}/clone-route")
def clone_route(
    session_id: int,
    fromRouteCardId: int = Query(...),
    current_user: dict = Depends(get_current_user),
):
    from app.route_card import workflow

    return workflow.clone_route_onto_session(session_id, fromRouteCardId, current_user)


@router.get("/route-cards/compare")
def compare_routes(
    a: int = Query(...),
    b: int = Query(...),
    current_user: dict = Depends(get_current_user),
):
    from app.route_card import workflow

    return workflow.compare_route_cards(a, b)


@router.get("/route-cards/{route_id}/audit")
def route_audit(route_id: int, current_user: dict = Depends(get_current_user)):
    from app.route_card import audit

    return {"items": audit.list_route_audit(route_id)}


@router.get("/my/favorites")
def my_favorites(current_user: dict = Depends(get_current_user)):
    from app.route_card import workflow

    return {"items": workflow.list_favorites(current_user)}


@router.post("/my/favorites")
async def add_favorite(request: Request, current_user: dict = Depends(get_current_user)):
    from app.route_card import workflow

    body = await request.json()
    return workflow.add_favorite(current_user, body or {})


@router.delete("/my/favorites/{fav_id}")
def delete_favorite(fav_id: int, current_user: dict = Depends(get_current_user)):
    from app.route_card import workflow

    return workflow.delete_favorite(fav_id, current_user)


@router.get("/my/recent")
def my_recent(current_user: dict = Depends(get_current_user)):
    from app.route_card import workflow

    return {"items": workflow.list_recent(current_user)}


@router.post("/analyze-jobs/batch")
async def analyze_jobs_batch(request: Request, current_user: dict = Depends(get_current_user)):
    from app.route_card import job_queue

    body = await request.json()
    ids = body.get("sessionIds") or body.get("session_ids") or []
    return job_queue.enqueue_batch([int(x) for x in ids], current_user)


@router.get("/analyze-jobs")
def list_analyze_jobs(
    mineOnly: bool = Query(True),
    current_user: dict = Depends(get_current_user),
):
    from app.route_card import job_queue

    return {"items": job_queue.list_jobs(current_user, mine_only=mineOnly)}


@router.get("/analyze-jobs/stats/queue")
def analyze_queue_stats(current_user: dict = Depends(get_current_user)):
    from app.route_card import job_queue

    return job_queue.queue_stats()


@router.get("/analyze-jobs/{job_id}")
def get_analyze_job(job_id: int, current_user: dict = Depends(get_current_user)):
    from app.route_card import job_queue

    return job_queue.get_job(job_id, current_user)


@router.post("/analyze-jobs/{job_id}/cancel")
def cancel_analyze_job(job_id: int, current_user: dict = Depends(get_current_user)):
    from app.route_card import job_queue

    return job_queue.cancel_db_job(job_id, current_user)


@router.get("/notifications")
def list_notifications(
    unreadOnly: bool = Query(False),
    current_user: dict = Depends(get_current_user),
):
    from app.route_card import notifications

    return notifications.list_notifications(current_user, unread_only=unreadOnly)


@router.post("/notifications/{notification_id}/read")
def read_notification(notification_id: int, current_user: dict = Depends(get_current_user)):
    from app.route_card import notifications

    return notifications.mark_notification_read(notification_id, current_user)


@router.post("/notifications/read-all")
def read_all_notifications(current_user: dict = Depends(get_current_user)):
    from app.route_card import notifications

    return notifications.mark_all_read(current_user)


@router.get("/dept-rules")
def get_dept_rules_api(
    dept: str | None = Query(None),
    current_user: dict = Depends(get_current_user),
):
    from app.route_card import dept_config

    d = dept or current_user.get("dept") or ""
    return dept_config.get_dept_rules(d)


@router.put("/dept-rules")
async def put_dept_rules(request: Request, current_user: dict = Depends(require_dept_head_or_admin)):
    from app.route_card import dept_config

    body = await request.json()
    return dept_config.upsert_dept_rules(
        current_user, body.get("dept") or current_user.get("dept") or "", body.get("rules") or {}
    )


@router.get("/few-shot-examples")
def list_few_shots(
    dept: str | None = Query(None),
    current_user: dict = Depends(get_current_user),
):
    from app.route_card import dept_config

    return {"items": dept_config.list_few_shots(dept or current_user.get("dept"))}


@router.post("/few-shot-examples")
async def create_few_shot(request: Request, current_user: dict = Depends(require_dept_head_or_admin)):
    from app.route_card import dept_config

    body = await request.json()
    return dept_config.create_few_shot(current_user, body or {})


@router.delete("/few-shot-examples/{example_id}")
def delete_few_shot(example_id: int, current_user: dict = Depends(require_dept_head_or_admin)):
    from app.route_card import dept_config

    return dept_config.delete_few_shot(example_id, current_user)


@router.get("/machines")
def list_machines(current_user: dict = Depends(get_current_user)):
    from app.route_card import admin_ops

    return {"items": admin_ops.list_machines()}


@router.post("/machines")
async def create_machine(request: Request, _admin: dict = Depends(require_admin)):
    from app.route_card import admin_ops

    body = await request.json()
    return admin_ops.upsert_machine(body or {})


@router.put("/machines/{machine_id}")
async def update_machine(machine_id: int, request: Request, _admin: dict = Depends(require_admin)):
    from app.route_card import admin_ops

    body = await request.json()
    return admin_ops.upsert_machine(body or {}, machine_id=machine_id)


@router.delete("/machines/{machine_id}")
def delete_machine(machine_id: int, _admin: dict = Depends(require_admin)):
    from app.route_card import admin_ops

    return admin_ops.delete_machine(machine_id)


@router.get("/admin/storage-stats")
def admin_storage_stats(_admin: dict = Depends(require_admin)):
    from app.route_card import admin_ops

    return admin_ops.storage_stats()


@router.post("/admin/cleanup")
def admin_cleanup(
    days: int = Query(90),
    dryRun: bool = Query(True),
    _admin: dict = Depends(require_admin),
):
    from app.route_card import admin_ops

    return admin_ops.cleanup_old_drafts(days=days, dry_run=dryRun)


@router.post("/admin/backup")
def admin_backup(_admin: dict = Depends(require_admin)):
    from app.route_card import admin_ops

    return admin_ops.run_backup()


@router.get("/system/health")
def system_health(current_user: dict = Depends(get_current_user)):
    from app.route_card import admin_ops

    return admin_ops.health_extended()
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
