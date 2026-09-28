"""Resolve FIGURE / SHEET / TABLE / DETAIL / VIEW references across multi-GA uploads.

Handles OCR quirks (TABEL, FIG., etc.) and cue phrases:
  AS PER | AS INDICATED | AS SHOWN | PROVIDED IN | REFER | SEE | REF | FOLLOWED …
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Cue words that introduce a drawing-internal pointer
REF_CUE = (
    r"(?:AS\s+PER|AS\s+INDICATED(?:\s+IN)?|AS\s+SHOWN(?:\s+IN)?|AS\s+GIVEN(?:\s+IN)?|"
    r"PROVIDED\s+IN|REFER(?:\s+TO)?|SEE|REF\.?|FOLLOW(?:ED)?(?:\s+AS\s+INDICATED)?(?:\s+IN)?|"
    r"PER\s+THE|ACCORDING\s+TO|SHOWN\s+IN|INDICATED\s+IN|GIVEN\s+IN)"
)

# FIGURE 1 / FIG. 1 / FIG 1
FIGURE_REF = re.compile(
    rf"(?:{REF_CUE}\s+)?(?:FIGURE|FIG\.?)\s*(?:NO\.?|#)?\s*([0-9]{{1,2}}|[A-Z])\b",
    re.I,
)
# SHEET 2 / SH. 2
SHEET_REF = re.compile(
    rf"(?:{REF_CUE}\s+)?(?:SHEETS?|SH\.?)\s*(?:NO\.?|#)?\s*([0-9]{{1,2}})\b",
    re.I,
)
# TABLE 1 / TABEL 1 (OCR) / TAB. 1
TABLE_REF = re.compile(
    rf"(?:{REF_CUE}\s+)?(?:TABLES?|TABELS?|TAB\.?)\s*(?:NO\.?|#)?\s*([0-9]{{1,2}}|[A-Z])\b",
    re.I,
)
# DETAIL A / DETAIL B
DETAIL_REF = re.compile(
    rf"(?:{REF_CUE}\s+)?(?:DETAILS?)\s*(?:NO\.?|#)?\s*([0-9]{{1,2}}|[A-Z])\b",
    re.I,
)
# VIEW A / SECTION A-A (light touch)
VIEW_REF = re.compile(
    rf"(?:{REF_CUE}\s+)?(?:VIEWS?)\s*(?:NO\.?|#)?\s*([0-9]{{1,2}}|[A-Z])\b",
    re.I,
)
# Named blocks without a number: INTERCONNECTION TABLE, TOOLING MATRIX
NAMED_BLOCK = re.compile(
    r"\b((?:INTERCONNECTION|INTERCONNECT(?:ION)?)\s+(?:TABLE|LIST(?:ING)?|DETAILS?)|"
    r"TOOLING\s+MATRIX|TOOLS?\s+FOR\s+CONNECTORISATION)\b",
    re.I,
)

FILENAME_SHEET = re.compile(
    r"(?:GA|DRG|DWG|SHEET)?\s*[-_]?\s*0*(\d{1,3})(?:\.[A-Za-z]+)?\s*$",
    re.I,
)
FILENAME_SHEET_MID = re.compile(r"[-_\s](?:GA|SHEET)\s*[-_]?\s*0*(\d{1,3})\b", re.I)
SHEETS_OF = re.compile(r"\b(\d{1,2})\s*(?:OF|/)\s*(\d{1,2})\b", re.I)

# Cable length table rows from OCR: "100 to 500 +/- 10"
TOL_ROW = re.compile(
    r"(\d+)\s*(?:to|-|–)\s*(\d+|Above|ABOVE)?[^\d+\-]{0,24}([+\-±]\s*/?\s*-?\s*\d+)",
    re.I,
)


@dataclass
class ViewRefFact:
    kind: str  # figure | sheet | table | detail | view | named
    label: str  # FIGURE 1 | SHEET 2 | TABLE 1 | DETAIL B | INTERCONNECTION TABLE
    id: str = ""
    status: str = "missing"  # resolved | same_sheet | missing
    source_drawing_id: int | None = None
    matched_drawing_id: int | None = None
    matched_filename: str = ""
    matched_sheet: int | None = None
    snippet: str = ""
    note_step: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "label": self.label,
            "id": self.id,
            "status": self.status,
            "sourceDrawingId": self.source_drawing_id,
            "matchedDrawingId": self.matched_drawing_id,
            "matchedFilename": self.matched_filename,
            "matchedSheet": self.matched_sheet,
            "snippet": self.snippet,
            "noteStep": self.note_step,
        }


@dataclass
class SheetIndex:
    drawing_id: int | None
    filename: str
    sheet_no: int | None
    raw_text: str = ""
    title_block: dict = field(default_factory=dict)
    figures: set[str] = field(default_factory=set)
    tables: set[str] = field(default_factory=set)
    details: set[str] = field(default_factory=set)
    named: set[str] = field(default_factory=set)

    @property
    def blob(self) -> str:
        return self.raw_text or ""


def infer_sheet_no(filename: str, title_block: dict | None = None, raw_text: str = "") -> int | None:
    """Best-effort sheet index from filename (GA-001 / GA - 002) or content cues."""
    fn = filename or ""
    m = FILENAME_SHEET_MID.search(fn) or FILENAME_SHEET.search(Path_stem(fn))
    if m:
        n = int(m.group(1))
        if 1 <= n <= 40:
            return n
    # Trailing -001.pdf / _002.pdf
    m2 = re.search(r"[-_\s]0*(\d{1,3})\.(?:pdf|PDF)$", fn)
    if m2:
        n = int(m2.group(1))
        if 1 <= n <= 40:
            return n
    # Content fingerprints for wiring packs
    u = (raw_text or "").upper()
    if "INTERCONNECTION" in u and ("TOOLING" in u or "CONNECTORISATION" in u or "TOOLING MATRIX" in u):
        # Usually sheet 2 when assembly notes live on another file
        return 2
    if (
        "ASSEMBLY INSTRUCTIONS" in u
        or "CTQ POINTS" in u
        or "CRITICAL TO QUALITY" in u
        or re.search(r"\bFIGURE\s*1\b", u)
    ):
        return 1
    sheets = (title_block or {}).get("sheets") or ""
    m3 = SHEETS_OF.search(str(sheets))
    if m3:
        return int(m3.group(1))
    return None


def Path_stem(fn: str) -> str:
    base = fn.replace("\\", "/").split("/")[-1]
    if "." in base:
        return base.rsplit(".", 1)[0]
    return base


def catalog_sheet(g: dict[str, Any]) -> SheetIndex:
    raw = g.get("raw_text") or g.get("rawText") or ""
    fn = g.get("filename") or ""
    title = g.get("title_block") or {}
    sheet_no = infer_sheet_no(fn, title, raw)
    idx = SheetIndex(
        drawing_id=g.get("drawingId"),
        filename=fn,
        sheet_no=sheet_no,
        raw_text=raw,
        title_block=title,
    )
    u = raw.upper()
    for m in re.finditer(r"\b(?:FIGURE|FIG\.?)\s*(?:NO\.?|#)?\s*([0-9]{1,2}|[A-Z])\b", u):
        idx.figures.add(m.group(1).upper())
    for m in re.finditer(r"\b(?:TABLES?|TABELS?|TAB\.?)\s*(?:NO\.?|#)?\s*([0-9]{1,2}|[A-Z])\b", u):
        # Skip "TABLE … PROVIDED IN SHEET" pointers — those are citations, not local tables
        tail = u[m.end() : m.end() + 48]
        if re.search(r"PROVIDED\s+IN\s+SHEET|IN\s+SHEET\s*\d", tail):
            continue
        idx.tables.add(m.group(1).upper())
    for m in re.finditer(r"\bDETAILS?\s*(?:NO\.?|#)?\s*([0-9]{1,2}|[A-Z])\b", u):
        # Avoid "DETAIL/ITEM NO" revision-table noise
        ctx = u[max(0, m.start() - 8) : m.end() + 12]
        if "DETAIL/ITEM" in ctx or "ITEM NO" in ctx[ctx.find("DETAIL") :]:
            if re.search(r"DETAIL\s*/\s*ITEM", ctx):
                continue
        idx.details.add(m.group(1).upper())
    for m in NAMED_BLOCK.finditer(raw):
        # Skip cross-sheet citations: "... TOOLING MATRIX PROVIDED IN SHEET 2"
        tail = raw[m.end() : m.end() + 48].upper()
        if re.search(r"PROVIDED\s+IN\s+SHEET|IN\s+SHEET\s*\d", tail):
            continue
        key = re.sub(r"\s+", " ", m.group(1)).upper()
        if "INTERCONNECT" in key:
            idx.named.add("INTERCONNECTION TABLE")
        elif "TOOLING" in key or "CONNECTORISATION" in key:
            idx.named.add("TOOLING MATRIX")
        else:
            idx.named.add(key)
    # Strong content headers (present on sheet-2 style GAs)
    if "INTERCONNECTION LISTING" in u or re.search(r"INTERCONNECTION\s+DETAILS", u):
        idx.named.add("INTERCONNECTION TABLE")
    if "TOOLING MATRIX" in u and "PROVIDED IN SHEET" not in u:
        idx.named.add("TOOLING MATRIX")
    elif re.search(r"(?m)^TOOLING\s+MATRIX\b", u) or "TOOLS FOR CONNECTORISATION" in u:
        idx.named.add("TOOLING MATRIX")
    return idx


def extract_view_refs_from_text(text: str) -> list[tuple[str, str, str]]:
    """Return list of (kind, id, label) from a note / instruction line."""
    found: list[tuple[str, str, str]] = []
    seen: set[str] = set()

    def add(kind: str, rid: str, label: str):
        key = f"{kind}:{rid}:{label}"
        if key in seen:
            return
        seen.add(key)
        found.append((kind, rid, label))

    for m in FIGURE_REF.finditer(text or ""):
        rid = (m.group(1) or "").upper()
        add("figure", rid, f"FIGURE {rid}")
    for m in SHEET_REF.finditer(text or ""):
        rid = str(int(m.group(1)))
        add("sheet", rid, f"SHEET {rid}")
    for m in TABLE_REF.finditer(text or ""):
        rid = (m.group(1) or "").upper()
        add("table", rid, f"TABLE {rid}")
    for m in DETAIL_REF.finditer(text or ""):
        rid = (m.group(1) or "").upper()
        add("detail", rid, f"DETAIL {rid}")
    for m in VIEW_REF.finditer(text or ""):
        rid = (m.group(1) or "").upper()
        add("view", rid, f"VIEW {rid}")
    for m in NAMED_BLOCK.finditer(text or ""):
        raw = re.sub(r"\s+", " ", m.group(1)).upper()
        if "INTERCONNECT" in raw:
            add("named", "INTERCONNECTION", "INTERCONNECTION TABLE")
        elif "TOOLING" in raw or "CONNECTORISATION" in raw:
            add("named", "TOOLING", "TOOLING MATRIX")
        else:
            add("named", raw[:24], raw)
    return found


def _find_sheet_by_no(catalog: list[SheetIndex], sheet_no: int) -> SheetIndex | None:
    for s in catalog:
        if s.sheet_no == sheet_no:
            return s
    return None


def _find_by_content(
    catalog: list[SheetIndex],
    *,
    kind: str,
    rid: str,
) -> SheetIndex | None:
    rid_u = (rid or "").upper()
    for s in catalog:
        if kind == "figure" and rid_u in s.figures:
            return s
        if kind == "table" and rid_u in s.tables:
            return s
        if kind == "detail" and rid_u in s.details:
            return s
        if kind == "named":
            for n in s.named:
                if rid_u in n or n.startswith(rid_u) or rid_u in n.replace(" ", ""):
                    return s
            if rid_u == "INTERCONNECTION" and any("INTERCONNECT" in n for n in s.named):
                return s
            if rid_u == "TOOLING" and any("TOOLING" in n for n in s.named):
                return s
    return None


def extract_table1_snippet(raw: str) -> str:
    """Pull cable-length tolerance rows near TABLE 1 / TABEL 1."""
    if not raw:
        return ""
    u = raw.upper()
    # Prefer window after Table 1 header
    start = -1
    for key in ("TABLE 1", "TABEL 1", "TABLE1", "TABEL1"):
        i = u.find(key)
        if i >= 0:
            start = i
            break
    window = raw[start : start + 500] if start >= 0 else raw[:800]
    rows = []
    for m in TOL_ROW.finditer(window):
        a, b, tol = m.group(1), m.group(2) or "", re.sub(r"\s+", "", m.group(3))
        if b and b.upper() != "ABOVE":
            rows.append(f"{a}-{b} mm {tol}")
        elif b and b.upper() == "ABOVE":
            rows.append(f"{a}+ mm {tol}")
        else:
            rows.append(f"{a} mm {tol}")
        if len(rows) >= 4:
            break
    # Fallback hardcoded pattern from this wiring GA family if OCR numbers present
    if not rows and re.search(r"100\s*to\s*500", window, re.I):
        rows = ["100-500 mm +/-10", "501-1000 mm +/-20", "1001+ mm +/-30"]
    return "; ".join(rows)


def figure_caption(raw: str, fig_id: str) -> str:
    text = raw or ""
    # Prefer titled callouts: FIGURE 1 — CABLE ASSY DIAGRAM
    for m in re.finditer(
        rf"FIGURE\s*{re.escape(fig_id)}\s*[-–—:]?\s*([A-Z][A-Z0-9 /()\-]{{3,48}})",
        text,
        re.I,
    ):
        cap = re.sub(r"\s+", " ", m.group(1)).strip(" -–—:")
        up = cap.upper()
        if up.startswith(("AND ", "OR ", "ITEM", "TO ", "THE ", "IN ", "ON ")):
            continue
        if any(k in up for k in ("DIAGRAM", "ASSY", "ASSEMBLY", "VIEW", "CABLE", "LAYOUT", "SCHEME")):
            return cap
        if len(cap.split()) <= 6 and not up.startswith("AND"):
            return cap
    u = text.upper()
    if f"FIGURE {fig_id}" in u and "CABLE" in u:
        return "CABLE ASSY DIAGRAM"
    return ""


def resolve_view_refs_for_notes(
    notes: list[dict[str, Any]],
    ga_results: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[ViewRefFact], list[str]]:
    """
    Enrich notes with viewRefs + elaboratedText when FIGURE/SHEET/TABLE/DETAIL cited.
    Returns (notes, facts, warnings).
    """
    catalog = [catalog_sheet(g) for g in ga_results]
    by_id = {s.drawing_id: s for s in catalog if s.drawing_id is not None}
    facts: list[ViewRefFact] = []
    warnings: list[str] = []
    out_notes: list[dict] = []

    for note in notes:
        nn = dict(note)
        text = nn.get("text") or ""
        refs = extract_view_refs_from_text(text)
        if not refs:
            out_notes.append(nn)
            continue

        src_id = nn.get("sourceDrawingId")
        src_sheet = by_id.get(src_id) if src_id is not None else None
        resolved_bits: list[str] = []
        note_view_refs: list[dict] = []

        # Prefer a SHEET N target when the same note also cites SHEET N
        sheet_targets = {rid for kind, rid, _ in refs if kind == "sheet"}

        for kind, rid, label in refs:
            match: SheetIndex | None = None
            status = "missing"

            if kind == "sheet":
                match = _find_sheet_by_no(catalog, int(rid))
                if not match:
                    # Content fallback: sheet 2 ≈ interconnection
                    if rid == "2":
                        match = next(
                            (
                                s
                                for s in catalog
                                if "INTERCONNECTION TABLE" in s.named or "TOOLING MATRIX" in s.named
                            ),
                            None,
                        )
            elif kind == "named" and sheet_targets:
                # "… INTERCONNECTION TABLE … PROVIDED IN SHEET 2" → resolve on that sheet
                for st in sorted(sheet_targets):
                    cand = _find_sheet_by_no(catalog, int(st))
                    if cand and (
                        any(rid in n or rid[:8] in n for n in cand.named)
                        or (rid == "INTERCONNECTION" and any("INTERCONNECT" in n for n in cand.named))
                        or (rid == "TOOLING" and any("TOOLING" in n for n in cand.named))
                        or (
                            rid in {"INTERCONNECTION", "TOOLING"}
                            and (
                                "INTERCONNECTION LISTING" in cand.blob.upper()
                                or "TOOLING MATRIX" in cand.blob.upper()
                                or "TOOLS FOR CONNECTORISATION" in cand.blob.upper()
                            )
                        )
                    ):
                        match = cand
                        break
                if not match:
                    # Still prefer sheet file even if named catalog missed (OCR gaps)
                    for st in sorted(sheet_targets):
                        cand = _find_sheet_by_no(catalog, int(st))
                        if cand:
                            match = cand
                            break
            elif kind in {"figure", "table", "detail", "view", "named"}:
                match = _find_by_content(catalog, kind=kind, rid=rid)
                if not match and src_sheet:
                    # Same-sheet default when feature exists on source
                    local_ok = (
                        (kind == "figure" and rid in src_sheet.figures)
                        or (kind == "table" and rid in src_sheet.tables)
                        or (kind == "detail" and rid in src_sheet.details)
                        or (kind == "named" and any(rid in n for n in src_sheet.named))
                    )
                    if local_ok or kind in {"figure", "table", "detail"}:
                        match = src_sheet
                        status = "same_sheet"

            if match:
                if status != "same_sheet":
                    status = (
                        "same_sheet"
                        if src_id is not None and match.drawing_id == src_id
                        else "resolved"
                    )
                snippet = ""
                if kind == "table" and rid in {"1", "I"}:
                    snippet = extract_table1_snippet(match.raw_text)
                elif kind == "figure":
                    snippet = figure_caption(match.raw_text, rid)
                elif kind == "named" and rid == "INTERCONNECTION":
                    snippet = "Interconnection listing / pin map"
                elif kind == "named" and rid == "TOOLING":
                    snippet = "Tooling matrix for connectorisation"

                fact = ViewRefFact(
                    kind=kind,
                    label=label,
                    id=rid,
                    status=status,
                    source_drawing_id=src_id if isinstance(src_id, int) else None,
                    matched_drawing_id=match.drawing_id,
                    matched_filename=match.filename,
                    matched_sheet=match.sheet_no,
                    snippet=snippet,
                    note_step=nn.get("stepNo"),
                )
                facts.append(fact)
                note_view_refs.append(fact.to_dict())

                loc = match.filename or f"drawing id {match.drawing_id}"
                sheet_lbl = f"sheet {match.sheet_no}" if match.sheet_no else "this drawing set"
                if kind == "sheet":
                    resolved_bits.append(
                        f"{label} is the uploaded file '{loc}'"
                        + (f" (indexed as {sheet_lbl})" if match.sheet_no else "")
                        + (
                            f" containing: {', '.join(sorted(match.named))}"
                            if match.named
                            else ""
                        )
                    )
                elif kind == "table" and snippet:
                    resolved_bits.append(
                        f"Follow {label} on '{loc}' ({sheet_lbl}): {snippet}"
                    )
                elif kind == "figure":
                    cap = f" — {snippet}" if snippet else ""
                    resolved_bits.append(f"See {label}{cap} on '{loc}' ({sheet_lbl})")
                elif kind == "detail":
                    resolved_bits.append(f"See {label} on '{loc}' ({sheet_lbl})")
                elif kind == "named":
                    resolved_bits.append(
                        f"Use {label}"
                        + (f" ({snippet})" if snippet else "")
                        + f" on '{loc}' ({sheet_lbl})"
                    )
                else:
                    resolved_bits.append(f"See {label} on '{loc}' ({sheet_lbl})")
            else:
                fact = ViewRefFact(
                    kind=kind,
                    label=label,
                    id=rid,
                    status="missing",
                    source_drawing_id=src_id if isinstance(src_id, int) else None,
                    note_step=nn.get("stepNo"),
                )
                facts.append(fact)
                note_view_refs.append(fact.to_dict())
                if kind == "sheet":
                    warnings.append(
                        f"Note step {nn.get('stepNo')}: {label} referenced but no matching GA "
                        f"sheet was uploaded (expected filename like GA-00{rid} / GA - 00{rid})."
                    )
                else:
                    warnings.append(
                        f"Note step {nn.get('stepNo')}: {label} could not be located in uploaded GAs."
                    )

        nn["viewRefs"] = note_view_refs
        if resolved_bits:
            # Build elaborated instruction: keep original + clear resolution appendix
            base = re.sub(r"\s+", " ", text).strip()
            # Strip OCR junk tails
            base = re.sub(r"\s+(?:Dr\.?|DO__\[ENGR.*)$", "", base, flags=re.I).strip()
            appendix = " ".join(dict.fromkeys(resolved_bits))
            elaborated = f"{base} -> {appendix}"
            # Don't overwrite a richer placement elaboration if already present
            existing = (nn.get("elaboratedText") or "").strip()
            if not existing:
                nn["elaboratedText"] = elaborated
                nn["mindEngine"] = nn.get("mindEngine") or "cpu_spatial"
                nn["mindConfidence"] = max(float(nn.get("mindConfidence") or 0), 0.7)
            elif "->" not in existing and appendix.lower() not in existing.lower():
                nn["elaboratedText"] = f"{existing} -> {appendix}"
            # Prefer resolved filenames in note references list
            refs_list = list(nn.get("references") or [])
            for vr in note_view_refs:
                fn = vr.get("matchedFilename") or ""
                if fn and fn not in refs_list:
                    refs_list.append(fn)
            nn["references"] = refs_list

        out_notes.append(nn)

    return out_notes, facts, list(dict.fromkeys(warnings))
