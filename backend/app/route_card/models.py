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
