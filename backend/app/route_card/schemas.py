from typing import Any, Optional

from pydantic import BaseModel, Field


class DrawingUploadResponse(BaseModel):
    id: int
    filename: str
    file_type: str
    size_bytes: int
    size_label: str
    pages: Optional[int] = None
    status: str
    drawing_type: str = "unknown"
    warnings: list[str] = Field(default_factory=list)


class DrawingInfo(BaseModel):
    drawingNumber: str = ""
    revision: str = ""
    partName: str = ""
    partNumber: str = ""
    material: str = ""
    quantity: str = ""
    overallDimensions: str = ""
    tolerance: str = ""
    surfaceFinish: str = ""
    drawingType: str = "unknown"
    docType: str = ""
    version: str = ""
    scale: str = ""
    sheetSize: str = ""
    sheets: str = ""
    weight: str = ""
    drawnBy: str = ""
    checkedBy: str = ""
    approvedBy: str = ""
    unit: str = "mm"


class BomItem(BaseModel):
    itemNo: int
    qty: int
    description: Optional[str] = None
    usedInOps: list[int] = Field(default_factory=list)


class NoteStep(BaseModel):
    sheet: int
    stepNo: int
    text: str
    items: list[int] = Field(default_factory=list)
    torque: list[str] = Field(default_factory=list)
    connectors: list[str] = Field(default_factory=list)
    standards: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)
    elaboratedText: str = ""
    placement: list[dict[str, Any]] = Field(default_factory=list)
    viewRefs: list[dict[str, Any]] = Field(default_factory=list)
    mindEngine: str = ""
    mindConfidence: float | None = None
    sourceDrawingId: int | None = None
    sourceFilename: str = ""


class IntelligenceItem(BaseModel):
    label: str
    value: str
    level: str = "Standard"


class OperationOut(BaseModel):
    id: str
    opNo: int
    operation: str
    workCentre: str = ""
    machine: str = ""
    tool: str = ""
    items: str = ""
    itemsUsed: list[dict[str, Any]] = Field(default_factory=list)
    torqueSpec: str = ""
    reference: str = ""
    setup: str = "1"
    time: str = ""
    inspection: str = ""
    instructionText: str = ""
    status: str = "Planned"
    type: str = "Assembly"
    reason: str = ""
    features: list[str] = Field(default_factory=list)


class InspectionOut(BaseModel):
    id: str
    dimension: str
    nominal: str = ""
    tolerance: str = ""
    method: str = ""
    frequency: str = "100%"
    criticality: str = "Important"


class FeatureCount(BaseModel):
    key: str
    label: str
    count: int


class ManufacturingFeature(BaseModel):
    id: str
    type: str
    dimension: str = ""
    tolerance: str = ""
    operation: str = ""
    category: str = "Assembly"


class RouteCardPayload(BaseModel):
    id: Optional[int] = None
    status: str = "draft"
    drawing: DrawingUploadResponse
    drawingInfo: DrawingInfo
    bomItems: list[BomItem] = Field(default_factory=list)
    featureCounts: list[FeatureCount] = Field(default_factory=list)
    manufacturingFeatures: list[ManufacturingFeature] = Field(default_factory=list)
    intelligenceDimensions: list[IntelligenceItem] = Field(default_factory=list)
    intelligenceRequirements: list[IntelligenceItem] = Field(default_factory=list)
    suggestedOperations: list[OperationOut] = Field(default_factory=list)
    routeOperations: list[OperationOut] = Field(default_factory=list)
    inspectionChars: list[InspectionOut] = Field(default_factory=list)
    referencedDocuments: list[str] = Field(default_factory=list)
    revisions: list[dict[str, Any]] = Field(default_factory=list)
    notes: list[NoteStep] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    analysisTasks: list[dict[str, Any]] = Field(default_factory=list)
    mind: dict[str, Any] = Field(default_factory=dict)
    drawings: list[dict[str, Any]] = Field(default_factory=list)
    crossRefs: list[dict[str, Any]] = Field(default_factory=list)
    viewRefs: list[dict[str, Any]] = Field(default_factory=list)


class OperationUpdate(BaseModel):
    id: Optional[str] = None
    opNo: int
    operation: str
    workCentre: str = ""
    machine: str = ""
    tool: str = ""
    items: str = ""
    itemsUsed: list[dict[str, Any]] = Field(default_factory=list)
    torqueSpec: str = ""
    reference: str = ""
    setup: str = "1"
    time: str = ""
    inspection: str = ""
    instructionText: str = ""
    status: str = "Planned"


class RouteCardUpdate(BaseModel):
    operations: list[OperationUpdate]
    inspection: Optional[list[InspectionOut]] = None


class FormatLearnRequest(BaseModel):
    """Save / update an offline format template from a reviewed session."""

    role: str = "drawing"  # drawing | wirelist | partslist
    docType: str = ""  # GA | PL | WL (optional; inferred from role)
    name: str = ""
    notes: str = ""
    updateId: Optional[str] = None
    aliases: dict[str, Any] = Field(default_factory=dict)


class OpTemplateStepIn(BaseModel):
    operation: str = Field(..., min_length=1, max_length=512)
    workCentre: str = ""
    setup: str = ""
    time: str = ""
    instructionText: str = ""
    inspection: str = ""
    machine: str = ""
    tool: str = ""
    generates_output_serial: bool = False
    requires_input_material: bool = False
    manual_operation: bool = True


class OpTemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str = ""
    placement: str = "any"  # pre | post | any
    dept: Optional[str] = None  # admin may set; dept_head forced to own
    steps: list[OpTemplateStepIn] = Field(default_factory=list)


class OpTemplateUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    placement: Optional[str] = None
    steps: Optional[list[OpTemplateStepIn]] = None


class OpTemplateDuplicate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)


class AdminUserRoleUpdate(BaseModel):
    role: str = Field(..., min_length=1, max_length=32)


class ManagedUserCreate(BaseModel):
    empId: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=255)
    dept: Optional[str] = Field(None, max_length=128)
    role: str = Field("engineer", min_length=1, max_length=32)
    password: str = Field(..., min_length=4, max_length=128)


class ManagedUserUpdate(BaseModel):
    empId: Optional[str] = Field(None, min_length=1, max_length=64)
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    dept: Optional[str] = Field(None, max_length=128)
    role: Optional[str] = Field(None, min_length=1, max_length=32)


class ManagedUserResetPassword(BaseModel):
    password: str = Field(..., min_length=4, max_length=128)


from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class OarcToSapRequest(BaseModel):
    """
    JSON generated by the frontend buildOarcJson() function.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        extra="allow",
    )

    source: str | None = None

    project_name: str | None = Field(
        default=None,
        alias="Project Name",
    )

    sale_order: str | None = Field(
        default=None,
        alias="Sale Order",
    )

    part_number: str | None = Field(
        default=None,
        alias="Part No",
    )

    part_description: str | None = Field(
        default=None,
        alias="Part Desc",
    )

    required_quantity: float | int | None = Field(
        default=None,
        alias="Required Qty",
    )

    plant: str | None = Field(
        default=None,
        alias="Plant",
    )

    wbs: str | None = Field(
        default=None,
        alias="WBS",
    )

    rtg_seq_no: str | None = Field(
        default=None,
        alias="Rtg Seq No",
    )

    sequence_no: str | None = Field(
        default=None,
        alias="Sequence No",
    )

    launched_quantity: float | int | None = Field(
        default=None,
        alias="Launched Qty",
    )

    production_order: str | None = Field(
        default=None,
        alias="Prod Order No",
    )

    priority: str | None = None

    total_operations: int | None = Field(
        default=None,
        alias="Total Operations",
    )

    operations: list[dict[str, Any]] = Field(
        default_factory=list,
        alias="Operations",
    )

    raw_materials: list[dict[str, Any]] = Field(
        default_factory=list,
        alias="Raw Materials",
    )

    document_verification: dict[str, Any] = Field(
        default_factory=dict,
        alias="Document Verification",
    )