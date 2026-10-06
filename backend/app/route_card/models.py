from datetime import datetime

from pony.orm import Json, Optional, PrimaryKey, Required, Set

from ..database.connection import db


class RcUser(db.Entity):
    _table_ = ("route_card", "users")

    id = PrimaryKey(int, auto=True)
    emp_id = Required(str, unique=True)
    name = Required(str)
    dept = Optional(str, default="")
    password_hash = Required(str)
    role = Required(str, default="engineer")  # admin | dept_head | engineer
    is_active = Required(bool, default=True)
    created_at = Required(datetime, default=datetime.utcnow)
    sessions = Set("RcSession")
    drawings = Set("RcDrawing")
    operation_templates = Set("RcOperationTemplate")
    analyze_jobs = Set("RcAnalyzeJob")
    review_flags = Set("RcReviewFlag")
    audit_events = Set("RcAuditEvent")
    notifications = Set("RcNotification")
    favorites = Set("RcUserFavorite")
    few_shot_examples = Set("RcFewShotExample")


class RcDepartment(db.Entity):
    """Department master for signup dropdown."""

    _table_ = ("route_card", "departments")

    id = PrimaryKey(int, auto=True)
    code = Required(str, unique=True)
    name = Required(str)
    is_active = Required(bool, default=True)
    sort_order = Required(int, default=0)
    created_at = Required(datetime, default=datetime.utcnow)


class RcSession(db.Entity):
    _table_ = ("route_card", "sessions")

    id = PrimaryKey(int, auto=True)
    user = Optional(RcUser)
    status = Required(str, default="open")
    created_at = Required(datetime, default=datetime.utcnow)
    updated_at = Required(datetime, default=datetime.utcnow)
    documents = Set("RcDocument")
    drawings = Set("RcDrawing")
    analyze_jobs = Set("RcAnalyzeJob")
    review_flags = Set("RcReviewFlag")


class RcDocument(db.Entity):
    _table_ = ("route_card", "documents")

    id = PrimaryKey(int, auto=True)
    session = Required(RcSession)
    role = Required(str)  # drawing | wirelist | partslist
    filename = Required(str)
    file_type = Required(str)
    content_type = Optional(str)
    object_path = Required(str)
    storage_backend = Required(str, default="minio")
    size_bytes = Required(int, default=0)
    status = Required(str, default="uploaded")
    extraction = Optional(Json)
    warnings = Optional(Json)
    created_at = Required(datetime, default=datetime.utcnow)
    updated_at = Required(datetime, default=datetime.utcnow)


class RcDrawing(db.Entity):
    _table_ = ("route_card", "drawings")

    id = PrimaryKey(int, auto=True)
    session = Optional(RcSession)
    user = Optional(RcUser)
    filename = Required(str)
    file_type = Required(str)
    content_type = Optional(str)
    object_path = Required(str)
    storage_backend = Required(str, default="minio")
    size_bytes = Required(int, default=0)
    pages = Optional(int)
    status = Required(str, default="uploaded")
    drawing_type = Optional(str, default="unknown")
    uploaded_by = Optional(str)
    error_message = Optional(str)
    created_at = Required(datetime, default=datetime.utcnow)
    updated_at = Required(datetime, default=datetime.utcnow)
    extractions = Set("RcExtraction")
    route_cards = Set("RcRouteCard")


class RcExtraction(db.Entity):
    _table_ = ("route_card", "extractions")

    id = PrimaryKey(int, auto=True)
    drawing = Required(RcDrawing)
    title_block = Optional(Json)
    revisions = Optional(Json)
    bom_items = Optional(Json)
    notes = Optional(Json)
    torque_specs = Optional(Json)
    dimensions = Optional(Json)
    references = Optional(Json)
    warnings = Optional(Json)
    raw_text = Optional(str)
    created_at = Required(datetime, default=datetime.utcnow)


class RcRouteCard(db.Entity):
    _table_ = ("route_card", "route_cards")

    id = PrimaryKey(int, auto=True)
    drawing = Required(RcDrawing)
    status = Required(str, default="draft")
    part_info = Optional(Json)
    created_at = Required(datetime, default=datetime.utcnow)
    updated_at = Required(datetime, default=datetime.utcnow)
    operations = Set("RcOperation")
    inspection_chars = Set("RcInspectionChar")
    review_flags = Set("RcReviewFlag")
    audit_events = Set("RcAuditEvent")


class RcOperation(db.Entity):
    _table_ = ("route_card", "operations")

    id = PrimaryKey(int, auto=True)
    route_card = Required(RcRouteCard)
    op_no = Required(int)
    operation = Required(str)
    work_centre = Optional(str)
    machine = Optional(str)
    tool = Optional(str)
    items_used = Optional(Json)
    torque_spec = Optional(str)
    reference = Optional(str)
    setup = Optional(str)
    time = Optional(str)
    inspection = Optional(str)
    instruction_text = Optional(str)
    status = Required(str, default="Planned")


class RcInspectionChar(db.Entity):
    _table_ = ("route_card", "inspection_chars")

    id = PrimaryKey(int, auto=True)
    route_card = Required(RcRouteCard)
    characteristic = Required(str)
    nominal = Optional(str)
    tolerance = Optional(str)
    method = Optional(str)
    frequency = Optional(str)
    criticality = Optional(str)
    source = Optional(str)


class RcOperationTemplate(db.Entity):
    """Department-owned pack of reusable operations (1..N steps)."""

    _table_ = ("route_card", "operation_templates")

    id = PrimaryKey(int, auto=True)
    dept = Required(str)
    name = Required(str)
    description = Optional(str, default="")
    placement = Required(str, default="any")  # pre | post | any
    # Root template id this pack was duplicated from (None = original)
    copied_from_id = Optional(int)
    created_by = Optional(RcUser)
    created_at = Required(datetime, default=datetime.utcnow)
    updated_at = Required(datetime, default=datetime.utcnow)
    is_active = Required(bool, default=True)
    steps = Set("RcOperationTemplateStep")


class RcOperationTemplateStep(db.Entity):
    _table_ = ("route_card", "operation_template_steps")

    id = PrimaryKey(int, auto=True)
    template = Required(RcOperationTemplate)
    sort_order = Required(int, default=0)
    operation = Required(str)
    work_centre = Optional(str, default="")
    setup = Optional(str, default="")
    time = Optional(str, default="")
    instruction_text = Optional(str)
    inspection = Optional(str, default="")
    machine = Optional(str, default="")
    tool = Optional(str, default="")
    generates_output_serial = Required(bool, default=False)
    requires_input_material = Required(bool, default=False)
    manual_operation = Required(bool, default=True)


class RcAnalyzeJob(db.Entity):
    """Durable analyze queue row (one VLM at a time via worker)."""

    _table_ = ("route_card", "analyze_jobs")

    id = PrimaryKey(int, auto=True)
    session = Required(RcSession)
    user = Optional(RcUser)
    status = Required(str, default="queued")  # queued|running|done|failed|cancelled
    progress = Required(int, default=0)
    message = Optional(str, default="")
    error_message = Optional(str)
    vlm_page_indexes = Optional(Json)  # list[int] or null = auto
    created_at = Required(datetime, default=datetime.utcnow)
    started_at = Optional(datetime)
    finished_at = Optional(datetime)


class RcReviewFlag(db.Entity):
    _table_ = ("route_card", "review_flags")

    id = PrimaryKey(int, auto=True)
    session = Optional(RcSession)
    route_card = Optional(RcRouteCard)
    user = Optional(RcUser)
    kind = Required(str)  # low_confidence | warning | missing_pl | empty_ops | as_shown | pl_ga_mismatch
    severity = Required(str, default="medium")  # high | medium | low
    message = Required(str)
    source = Optional(str, default="")
    resolved = Required(bool, default=False)
    resolved_at = Optional(datetime)
    resolved_by = Optional(str)
    created_at = Required(datetime, default=datetime.utcnow)


class RcAuditEvent(db.Entity):
    _table_ = ("route_card", "audit_events")

    id = PrimaryKey(int, auto=True)
    route_card = Optional(RcRouteCard)
    session = Optional(int)
    user = Optional(RcUser)
    action = Required(str)
    detail = Optional(Json)
    comment = Optional(str)
    created_at = Required(datetime, default=datetime.utcnow)


class RcNotification(db.Entity):
    _table_ = ("route_card", "notifications")

    id = PrimaryKey(int, auto=True)
    user = Required(RcUser)
    title = Required(str)
    body = Optional(str, default="")
    link = Optional(str, default="")
    read_at = Optional(datetime)
    created_at = Required(datetime, default=datetime.utcnow)


class RcUserFavorite(db.Entity):
    _table_ = ("route_card", "user_favorites")

    id = PrimaryKey(int, auto=True)
    user = Required(RcUser)
    part_number = Optional(str, default="")
    label = Optional(str, default="")
    session_id = Optional(int)
    route_card_id = Optional(int)
    created_at = Required(datetime, default=datetime.utcnow)


class RcDeptRules(db.Entity):
    _table_ = ("route_card", "dept_rules")

    id = PrimaryKey(int, auto=True)
    dept = Required(str, unique=True)
    rules = Optional(Json)  # autoTemplateIds, keywords, wcAliases, promptAddendum, phrasing
    updated_at = Required(datetime, default=datetime.utcnow)
    updated_by = Optional(str)


class RcFewShotExample(db.Entity):
    _table_ = ("route_card", "few_shot_examples")

    id = PrimaryKey(int, auto=True)
    dept = Required(str)
    doc_type = Optional(str, default="drawing")
    title = Required(str)
    input_excerpt = Optional(str)
    output_excerpt = Required(str)
    created_by = Optional(RcUser)
    created_at = Required(datetime, default=datetime.utcnow)
    is_active = Required(bool, default=True)


class RcMachine(db.Entity):
    _table_ = ("route_card", "machines")

    id = PrimaryKey(int, auto=True)
    plant = Optional(str, default="")
    work_centre = Required(str)
    name = Required(str)
    description = Optional(str, default="")
    is_active = Required(bool, default=True)
    sort_order = Required(int, default=0)
    created_at = Required(datetime, default=datetime.utcnow)
