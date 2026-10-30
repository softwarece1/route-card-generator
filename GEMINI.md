# Antigravity Workspace Guidelines & Speed Protocol

## 1. Execution Speed & Tool Optimization (Cursor Parity)
- **Knowledge Graph First:** For codebase architecture and relationship questions, query `graphify explain "<concept>"`, `graphify path "<A>" "<B>"`, or check `graphify-out/GRAPH_REPORT.md` before searching raw files.
- **Zero Unconstrained Scans:** NEVER run recursive `dir -Recurse`, `find`, or unbounded file searches across the repository. Always specify exact target directories (e.g. `backend/app/route_card` or `frontend/src`).
- **Ignore Bulky Directories:** ALWAYS ignore `.venv/`, `node_modules/`, `uploads/`, `offline_packages/`, `dumps/`, `backups/`, and `__pycache__/`.
- **Targeted File Reads:** Use specific `StartLine` and `EndLine` ranges when reading files. Do not dump entire 800-line files when looking for a function or snippet.
- **Direct Action:** When asked to edit, implement, or inspect, proceed directly with precise file edits and succinct summaries. Avoid excessive intermediate planning commentary.

## 2. Project Architecture & Standards
- **Backend (`backend/app`):**
  - Framework: FastAPI + PonyORM (`@db_session`).
  - Database: PostgreSQL with schema `route_card`.
  - Storage: MinIO S3 object storage for PDF drawings and documents.
  - Operation & Route generation lives in `backend/app/route_card/`.
- **Frontend (`frontend/src`):**
  - Framework: React (JSX) + Vite + PrimeReact + SCSS.
  - UI Styling: Compact controls (small/regular buttons and inputs, avoid oversized elements).
  - Main route card workflow in `frontend/src/pages/RouteCardGenerationAlt.jsx`.

## 3. Communication Style
- Keep responses concise, direct, and structured with GitHub markdown.
- Include direct file links using the `file:///` format for modified and referenced files.
