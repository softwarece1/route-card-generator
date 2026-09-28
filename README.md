# Standalone Route Card Generator

Independent extract of the PMF **AI Route Card Generator** (frontend + FastAPI).  
PDF ingest is **offline**: PyMuPDF text → pdfplumber tables (PL/WL) → **Tesseract OCR** when the text layer is sparse.  
Route ops remain **keyword rules** — there is **no LLM / no cloud AI** (CPU-only friendly).

**Offline-friendly:** uses **local PostgreSQL 18** (pgAdmin). Docker is not required.

## Layout

```
route-card-app/
  backend/              # FastAPI + copied app/route_card
  frontend/             # Vite + PrimeReact
  docker-compose.optional.yml   # optional only — prefer local PG 18
```

## Prerequisites (offline PC)

- **PostgreSQL 18** + **pgAdmin** (installed locally)
- Python 3.11+
- Node 20+ (or copy `frontend/node_modules` for fully offline install)
- **Tesseract OCR** (recommended for scanned PDFs) — see Offline OCR below

## 1. Database (pgAdmin / PostgreSQL 18)

Default connection in `backend/.env`:

| Setting | Value |
|---------|--------|
| Host | `localhost` |
| Port | `5432` |
| Database | `route_card` |
| User | `route_card` |
| Password | `route_card` |

### In pgAdmin

1. Connect to your **PostgreSQL 18** server as the `postgres` superuser.
2. Open Query Tool on the `postgres` database.
3. Create the login role:

```sql
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'route_card') THEN
    CREATE ROLE route_card LOGIN PASSWORD 'route_card';
  ELSE
    ALTER ROLE route_card WITH LOGIN PASSWORD 'route_card';
  END IF;
END
$$;
```

4. Create the database:
   - Right-click **Databases** → **Create** → **Database**
   - **Database:** `route_card`
   - **Owner:** `route_card`
   - Save

5. Open Query Tool on database **`route_card`** and run [`backend/setup_pgadmin_grants.sql`](backend/setup_pgadmin_grants.sql).

6. (Optional) Confirm you can connect with user `route_card` / password `route_card` on port **5432**.

Tables/schema are created automatically the first time the backend starts (migration + Pony).

If your Postgres password or port differs, edit `backend/.env` only — do not change code.

## 2. Backend

```bash
cd D:/PMF/route-card-app/backend
py -3.11 -m venv .venv

# Windows (online)
.venv/Scripts/pip install -r requirements.txt

# Windows (offline PC — use wheels from offline_packages/)
.venv/Scripts/pip install --no-index --find-links=offline_packages -r requirements.txt

.venv/Scripts/uvicorn app.main:app --reload --host 0.0.0.0 --port 8008
```

To refresh the offline wheel cache on a machine with internet:

```bash
cd D:/PMF/route-card-app/backend
.venv/Scripts/pip download -r requirements.txt -d offline_packages
```

- Health: http://localhost:8008/health  
- OpenAPI: http://localhost:8008/docs  

**App login (demo):** `admin / admin123` or `engineer / engineer123`

Files fall back to `backend/uploads/route-card/` when MinIO is unavailable (fine offline).

For local/dev without Docker MinIO, set in `backend/.env`:

```env
STORAGE_BACKEND=local
```

(`auto` tries MinIO first with a **2s** connect timeout, then caches “down” for 60s so uploads do not stall ~1 minute each time MinIO is offline.)

Optional DWG: set `ODA_CONVERTER_PATH` if ODA File Converter is installed.

### Offline OCR (graphic NOTES / scanned PDFs)

Many BEL GAs put **NOTE I / NOTE II** as drawing graphics (not searchable text).  
The app already calls **Tesseract** in that case — you only need the OCR **binary** installed.

1. Download & install [Tesseract for Windows (UB Mannheim)](https://github.com/UB-Mannheim/tesseract/wiki)  
   - Or: `winget install --id UB-Mannheim.TesseractOCR -e`
2. Confirm the exe exists, then set in `backend/.env`:

```env
OCR_ENABLED=true
TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
OCR_DPI=250
OCR_MAX_PAGES=12
```

3. Restart the backend, **New session**, re-upload the GA, **Start Analyze**.

OCR runs on **CPU** (no GPU). First analyze of a large sheet can take 10–60s.

## Extraction pipeline (offline)

```
PDF bytes
  → PyMuPDF text (title block, etc.)
  → if no NOTES found: Tesseract OCR merged in (graphic NOTE I / NOTE II)
  → spatial word boxes (PyMuPDF dict / Tesseract image_to_data)
  → Drawing mind (CPU spatial; later local_vlm) elaborates AS SHOWN notes
  → pdfplumber tables (Parts List / Wire List)
  → multi-GA merge + cross-ref resolver
  → field parsers → keyword route generator (prefers elaboratedText)
```

Best results still come from **standard BEL-style** GA / PL / WL exports. Layout+OCR improves scans and messy text; it does not fully generalize arbitrary drawing formats.

### Drawing mind (CPU → on-prem VLM)

Elaborates placement notes like *STICK ITEM 2 & 3 AS SHOWN* into surface + offset instructions when dimension/balloon text is OCR-readable.

```env
DRAWING_MIND_ENGINE=cpu_spatial
DRAWING_MIND_SPATIAL_DPI=200
DRAWING_MIND_MAX_PAGES=12
```

Sessions accept **multiple GA uploads** of the same part family; missing referenced GAs are warned. Internal pointers (`FIGURE 1`, `SHEET 2`, `TABLE 1`/`TABEL 1`, `DETAIL B`, interconnection / tooling matrix) are resolved across uploaded sheets using cues like *as per / as indicated / as shown / provided in / refer / see*. See [`backend/docs/DRAWING_MIND.md`](backend/docs/DRAWING_MIND.md).

### Adaptive format templates (offline, no LLM)

Parsers are rule-based. To adapt when layouts change:

1. Analyze a session and review the extract.
2. Click **Save GA / PL / WL format** in Engineer Review.
3. Templates are stored in `backend/data/format_templates.json` (copy this file to the offline PC).
4. Next similar uploads are fingerprinted and matched; learned header aliases are applied before parsing.

APIs: `GET /api/v1/route-card/formats`, `POST /sessions/{id}/formats/learn`, `DELETE /formats/{id}`.

Built-in defaults cover BEL GA / Parts List / Wire List. Learned templates are additive (built-ins cannot be deleted).

### Order prefill / OARC preview (Create Order shape)

On the main page, after analysis click **View OARC preview**. A dialog mirrors PMF Create Order:

- Project & Order Context / Part & Work Scope (empty Prod Order, SO, WBS, Plant)
- Operations + Raw Materials tabs (prefilled from NOTES / PL)
- Document Information — Engineering Drawing & Part List from session uploads
- **Print** (placeholder for later) and **Export JSON**

## 3. Frontend

```bash
cd D:/PMF/route-card-app/frontend
npm install
npm run dev
```

Open http://localhost:5174 → sign in → upload GA PDF → **Start Analyze**.

Vite proxies `/api` to the backend on **port 8008** by default in `vite.config.js`.

If health checks fail with “connection refused on 5433”, an old backend is still running — stop it and start again so it reads `DB_PORT=5432`.

## Workflow

1. Sign in at `/login`  
2. Session created on load  
3. Upload Drawing (+ optional Wire List / Parts List)  
4. Start Analyze → edit ops → Save Draft / Approve  
5. **New session** for the next drawing  

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `password authentication failed` | Check `DB_*` in `backend/.env` matches pgAdmin user |
| `could not connect` / port | Confirm Postgres 18 is running on **5432** (pgAdmin server properties) |
| Network Error in UI | Backend must be on **8008**; restart Vite after changing `vite.config.js` |
| Still on old Docker DB | Stop container: `docker stop route-card-postgres` — app now uses local PG on 5432 |
| Scanned PDF extracts nothing | Install Tesseract + set `TESSERACT_CMD`; confirm `OCR_ENABLED=true` |
| OCR slow on large drawings | Lower `OCR_MAX_PAGES` or `OCR_DPI` in `.env` |

## Optional Docker DB

Only if you do not have local Postgres: `docker compose -f docker-compose.optional.yml up -d` and set `DB_PORT=5433` in `.env`.

## Source

Copied from `pmf-backend/app/route_card/` and the PMF Route Card frontend page.
