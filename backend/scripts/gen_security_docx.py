"""Generate a fresh Static Code Analysis vulnerability report (current open issues only)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "Route_Card_Generator_Static_Code_Analysis_Report.docx"
OUT_ALT = ROOT / "docs" / "Route_Card_Generator_SAST_Vulnerability_Report.docx"


def set_cell_shading(cell, hex_color: str) -> None:
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), hex_color)
    shd.set(qn("w:val"), "clear")
    tcPr.append(shd)


def add_para(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.font.size = Pt(11)
    run.font.name = "Calibri"


def add_kv(doc: Document, label: str, value: str) -> None:
    p = doc.add_paragraph()
    r = p.add_run(f"{label}: ")
    r.bold = True
    r.font.name = "Calibri"
    r.font.size = Pt(11)
    v = p.add_run(value)
    v.font.name = "Calibri"
    v.font.size = Pt(11)


def add_table(doc: Document, headers: list[str], rows: list[list[str]], header_fill="1F4E79"):
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(headers):
        cell = table.rows[0].cells[i]
        cell.text = h
        for p in cell.paragraphs:
            for r in p.runs:
                r.bold = True
                r.font.color.rgb = RGBColor(255, 255, 255)
                r.font.size = Pt(9)
                r.font.name = "Calibri"
        set_cell_shading(cell, header_fill)
    for ri, row in enumerate(rows):
        for ci, val in enumerate(row):
            cell = table.rows[ri + 1].cells[ci]
            cell.text = str(val)
            for p in cell.paragraphs:
                for r in p.runs:
                    r.font.size = Pt(9)
                    r.font.name = "Calibri"
            if headers[ci].lower() == "severity":
                if val == "High":
                    set_cell_shading(cell, "F8D7DA")
                elif val == "Medium":
                    set_cell_shading(cell, "FFF3CD")
                elif val == "Low":
                    set_cell_shading(cell, "D1ECF1")
                elif val == "Informational":
                    set_cell_shading(cell, "E2E3E5")
    return table


def add_finding(
    doc: Document,
    *,
    vid: str,
    title: str,
    severity: str,
    category: str,
    cwe: str,
    description: str,
    evidence: str,
    impact: str,
    recommendation: str,
) -> None:
    doc.add_heading(f"{vid} — {title}", level=2)
    add_kv(doc, "Severity", severity)
    add_kv(doc, "Category", category)
    add_kv(doc, "CWE", cwe)
    p = doc.add_paragraph()
    r = p.add_run("Description")
    r.bold = True
    add_para(doc, description)
    p = doc.add_paragraph()
    r = p.add_run("Evidence")
    r.bold = True
    add_para(doc, evidence)
    p = doc.add_paragraph()
    r = p.add_run("Impact")
    r.bold = True
    add_para(doc, impact)
    p = doc.add_paragraph()
    r = p.add_run("Recommendation")
    r.bold = True
    add_para(doc, recommendation)


def main() -> None:
    doc = Document()
    for section in doc.sections:
        section.top_margin = Cm(2.0)
        section.bottom_margin = Cm(2.0)
        section.left_margin = Cm(2.2)
        section.right_margin = Cm(2.2)

    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = title.add_run("STATIC CODE ANALYSIS REPORT")
    r.bold = True
    r.font.size = Pt(22)
    r.font.color.rgb = RGBColor(31, 78, 121)

    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    rr = sub.add_run("Route Card Generator — Vulnerability Findings")
    rr.font.size = Pt(14)

    sub2 = doc.add_paragraph()
    sub2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    rr2 = sub2.add_run("SAST (Bandit) and Secure Code Review — Current Open Issues")
    rr2.font.size = Pt(11)
    rr2.font.color.rgb = RGBColor(90, 90, 90)

    doc.add_paragraph()
    add_table(
        doc,
        ["Field", "Value"],
        [
            ["Document title", "Static Code Analysis Report — Route Card Generator"],
            ["Application", "Route Card Generator"],
            ["Deployment context", "Intranet / plant LAN"],
            ["Assessment type", "Bandit SAST + targeted secure code review"],
            ["Scope of findings", "Open vulnerabilities in the current codebase only"],
            ["Report date", date.today().isoformat()],
            ["Classification", "Internal — Confidential"],
            ["Audience", "Information Security"],
            ["Code baseline", "Branch llm_heavy_workflow (current working tree)"],
            ["Bandit version", "1.9.x (project .venv)"],
        ],
    )

    doc.add_heading("1. Executive Summary", level=1)
    add_para(
        doc,
        "This report presents currently open application-security findings identified by "
        "Bandit static analysis and a focused secure code review of the Route Card Generator "
        "backend. Previously remediated defects are excluded. Only issues that remain in the "
        "present source tree are listed.",
    )
    add_para(
        doc,
        "Bandit scanned approximately 18,800 lines under backend/app and reported 0 High, "
        "2 Medium, and 41 Low alerts. After analyst triage, six open findings are raised for "
        "security review (1 Medium, 5 Low). Remaining Bandit Low alerts are summarised as "
        "informational noise in Section 6.",
    )

    doc.add_heading("1.1 Findings summary", level=2)
    add_table(
        doc,
        ["Severity", "Open findings", "Description"],
        [
            ["High", "0", "No High-severity open issues identified in this scan"],
            ["Medium", "1", "Dynamic SQL construction in schema migrations (Bandit B608)"],
            ["Low", "5", "Hardcoded secrets/constants, public enumeration, defaults, CSP, error detail"],
            ["Informational", "See §6", "Bandit B110/B105/B404/B603 noise after triage"],
        ],
    )

    doc.add_heading("2. Scope and Methodology", level=1)
    doc.add_heading("2.1 Scope", level=2)
    for item in [
        "backend/app Python sources (full Bandit scan).",
        "Authentication, authorisation, upload, and configuration paths reviewed for issues not already corrected.",
        "Frontend credential storage spot-check (JWT must not be stored in localStorage).",
    ]:
        doc.add_paragraph(item, style="List Bullet")
    doc.add_heading("2.2 Out of scope", level=2)
    for item in [
        "Issues already corrected in the current baseline (drawing ACL, public health disclosure, login token body, same-host CORS, SPA path jail, Content-Disposition sanitisation, reference upload size limit, PBKDF2 iteration increase, docs disabled in prod).",
        "Dynamic penetration testing of a live host.",
        "Infrastructure and third-party dependency CVE inventory.",
    ]:
        doc.add_paragraph(item, style="List Bullet")
    doc.add_heading("2.3 Method", level=2)
    add_para(
        doc,
        "Primary tool: Bandit (python -m bandit -r app). Supporting review: manual inspection "
        "of Bandit Medium/Low hits and selected API routes. Severity uses High / Medium / Low "
        "qualitative ratings for application security reporting.",
    )

    doc.add_heading("3. Findings Register", level=1)
    add_table(
        doc,
        ["ID", "Severity", "Category", "Title", "Source"],
        [
            ["V-01", "Medium", "Injection", "Dynamic SQL in schema migration scripts", "Bandit B608"],
            ["V-02", "Low", "Secrets", "Hardcoded legacy seed password constant in source", "Bandit B105 + review"],
            ["V-03", "Low", "Configuration", "Development SECRET_KEY default shipped in settings", "Code review"],
            ["V-04", "Low", "Information disclosure", "Unauthenticated emp-status and SBU listing", "Code review"],
            ["V-05", "Low", "Browser security", "CSP style-src allows unsafe-inline", "Code review"],
            ["V-06", "Low", "Information disclosure", "Exception detail returned from OARC mapping API", "Code review"],
        ],
    )

    doc.add_heading("4. Detailed Findings", level=1)

    add_finding(
        doc,
        vid="V-01",
        title="Dynamic SQL in schema migration scripts",
        severity="Medium",
        category="Injection (CWE-89)",
        cwe="CWE-89",
        description=(
            "Bandit B608 reports string-interpolated SQL in migrations_route_card.py. "
            "Column-rename DDL is built with f-strings using table and column names from an "
            "internal migration tuple. Values are not taken from HTTP request parameters; "
            "however, dynamic SQL construction remains a maintainability and scanner-risk "
            "concern if future changes introduce untrusted identifiers."
        ),
        evidence=(
            "Bandit B608 — backend/app/database/migrations_route_card.py:240 and :1160 "
            "(DO $$ … ALTER TABLE route_card.{table} RENAME COLUMN …)"
        ),
        impact=(
            "Current exploitability for remote SQL injection is assessed as low because "
            "identifiers are developer-controlled literals executed only during migration. "
            "Risk increases if the pattern is copied into request-handling code."
        ),
        recommendation=(
            "Replace f-string DDL with an allow-listed identifier validator (whitelist of "
            "table/column names) or static SQL per rename. Re-run Bandit to clear B608."
        ),
    )

    add_finding(
        doc,
        vid="V-02",
        title="Hardcoded legacy seed password constant in source",
        severity="Low",
        category="Use of hard-coded credentials (CWE-798)",
        cwe="CWE-798",
        description=(
            "Source contains LEGACY_SEED_PASSWORD = \"Adm!n@123bel\" used to detect accounts "
            "still on a historical seed password. Bandit B105 flags this literal. The value "
            "is a real historical credential pattern and should not remain in distributed source "
            "if avoidable."
        ),
        evidence="backend/app/route_card/work_centers.py — LEGACY_SEED_PASSWORD (approx. line 1358)",
        impact=(
            "Anyone with source or binary access learns a password formerly used for seeded "
            "accounts. Accounts still using that password remain at risk until rotated."
        ),
        recommendation=(
            "Move the comparison material to a salted/hash-only check, an environment-supplied "
            "value, or remove the constant after migration completes. Ensure no accounts still "
            "verify against this password in production."
        ),
    )

    add_finding(
        doc,
        vid="V-03",
        title="Development SECRET_KEY default shipped in settings",
        severity="Low",
        category="Configuration / Cryptographic key management",
        cwe="CWE-1188 / CWE-321",
        description=(
            "settings.SECRET_KEY defaults to a well-known development placeholder. Production "
            "startup refuses this value when APP_ENV is prod, but non-prod or mis-set APP_ENV "
            "can still run with the placeholder, weakening JWT integrity."
        ),
        evidence="backend/app/config/settings.py — SECRET_KEY default; backend/app/security_startup.py",
        impact="Forged session tokens if the placeholder key is used on a reachable host.",
        recommendation=(
            "Require SECRET_KEY from environment with no insecure default, or fail startup "
            "whenever the placeholder is detected regardless of APP_ENV on plant builds."
        ),
    )

    add_finding(
        doc,
        vid="V-04",
        title="Unauthenticated emp-status and SBU listing",
        severity="Low",
        category="Information disclosure / Account enumeration",
        cwe="CWE-204",
        description=(
            "GET /api/v1/auth/emp-status/{emp_id} reports whether an employee ID is registered. "
            "GET /api/v1/auth/sbus lists active SBUs. Both are reachable without authentication "
            "(rate-limited) to support self-signup."
        ),
        evidence="backend/app/auth/routes.py — emp_status, list_sbus (rate limit 30/min)",
        impact="Limited enumeration of employee IDs and organisational structure on the plant network.",
        recommendation=(
            "If policy requires, restrict these endpoints to authenticated managers or return "
            "non-confirming responses. Retain rate limiting as a minimum control."
        ),
    )

    add_finding(
        doc,
        vid="V-05",
        title="Content-Security-Policy allows unsafe-inline styles",
        severity="Low",
        category="Browser security misconfiguration",
        cwe="CWE-1021",
        description=(
            "Response CSP sets style-src 'self' 'unsafe-inline'. Script policy may use hashes "
            "for known bootstrap scripts, but inline styles remain permitted for UI framework "
            "compatibility."
        ),
        evidence="backend/app/middleware/security_headers.py",
        impact="Increases the impact of XSS by allowing attacker-controlled inline CSS/script patterns where applicable.",
        recommendation="Introduce nonces or hashes for required styles and remove style-src 'unsafe-inline' when the UI build allows.",
    )

    add_finding(
        doc,
        vid="V-06",
        title="Exception detail returned from OARC mapping API",
        severity="Low",
        category="Information disclosure",
        cwe="CWE-209",
        description=(
            "POST /api/v1/route-card/oarc/to-sap catches exceptions and returns "
            "detail=f\"OARC to SAP mapping failed: {exc}\" to the client, potentially exposing "
            "internal error strings."
        ),
        evidence="backend/app/route_card/router.py — convert_oarc_to_sap",
        impact="Aids troubleshooting for attackers and may leak implementation details.",
        recommendation="Return a generic client message; log the exception server-side only.",
    )

    doc.add_heading("5. Bandit Scan Metrics", level=1)
    add_para(
        doc,
        "Command: python -m bandit -r app (working directory backend/). "
        "Output artifact: docs/bandit-fresh.json",
    )
    add_table(
        doc,
        ["Metric", "Value"],
        [
            ["High", "0"],
            ["Medium", "2 (both B608 — raised as V-01)"],
            ["Low", "41"],
            ["Dominant Low tests", "B110 try/except/pass (29), B105 (6), B404/B603 (4), B112 (2)"],
        ],
    )

    doc.add_heading("6. Informational Bandit Alerts (Not Raised as Vulnerabilities)", level=1)
    add_para(
        doc,
        "The following Low-severity Bandit alerts were reviewed and are not opened as "
        "vulnerabilities in this report:",
    )
    add_table(
        doc,
        ["Test", "Count", "Analyst note"],
        [
            ["B110", "29", "Bare except/pass in startup and cleanup paths; no direct exploit path"],
            ["B105 ('bearer')", "3", "False positive — OAuth token_type literal, not a password"],
            ["B105 (placeholder checks)", "2", "Constants used to detect insecure defaults at startup"],
            ["B404 / B603", "4", "subprocess for pg_dump and ODA converter uses argv lists; no shell=True; admin/CAD only"],
            ["B112", "2", "try/except/continue in parsers; informational"],
        ],
    )

    doc.add_heading("7. Recommendations Priority", level=1)
    add_table(
        doc,
        ["Priority", "Finding", "Action"],
        [
            ["P1", "V-01", "Allow-list migration SQL identifiers; clear Bandit B608"],
            ["P2", "V-02", "Remove or externalise LEGACY_SEED_PASSWORD; verify no live accounts use it"],
            ["P2", "V-03", "Eliminate insecure SECRET_KEY default on plant builds"],
            ["P3", "V-04", "Tighten signup directory APIs per policy"],
            ["P3", "V-05 / V-06", "CSP hardening and generic API error messages"],
        ],
    )

    doc.add_heading("8. Conclusion", level=1)
    add_para(
        doc,
        "No High-severity open vulnerabilities were identified in the current Bandit scan. "
        "One Medium finding (dynamic migration SQL) and five Low findings remain for security "
        "and engineering attention. Previously corrected issues are intentionally omitted from "
        "this report. The security team should track V-01 through V-06 to closure or formal "
        "risk acceptance.",
    )

    doc.add_heading("9. Document Control", level=1)
    add_table(
        doc,
        ["Version", "Date", "Description"],
        [["1.0", date.today().isoformat(), "Fresh SAST/vulnerability report — open findings only"]],
    )

    try:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        doc.save(OUT)
        print(OUT)
        print("bytes", OUT.stat().st_size)
    except PermissionError:
        doc.save(OUT_ALT)
        print(OUT_ALT)
        print("bytes", OUT_ALT.stat().st_size)
        print("NOTE: primary locked; wrote alternate")


if __name__ == "__main__":
    main()
