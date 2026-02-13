# AMIE on Azure

Academic Manuscript IP Evaluator (AMIE) deployed on Azure AI + Functions. Upload a manuscript, classify whether it discloses an invention, and run a lightweight novelty assessment against open prior‑art sources.

## What this repo contains
- **React frontend (Vite)**: single-page drag/drop uploader (`src/`) that POSTs PDFs/DOCs to an Azure Function.
- **Ingestion Function** (`backend/ingestion-agent/function_app.py`): HTTP `POST /upload` stores files in Blob Storage (`manuscript-uploads`) and logs metadata to Table Storage (`IngestionRequests`). Also exposes request listing/status endpoints.
- **IDCA script** (`backend/idca/idca.py`): pulls an uploaded PDF from Blob, extracts text, and runs an Azure AI Agents deployment with a strict JSON prompt to classify invention presence and structure. Writes JSON back to the ingestion table.
- **NAA Functions app** (`backend/naa-amie-azure-clean/function_app.py`): performs novelty assessment after IDCA. Uses the IDCA synopsis/claims to search PatentsView, OpenAlex, and Semantic Scholar (`backend/naa-amie-azure-clean/prior_art_open.py`), scores novelty/§102 risk, and stores results to the same table.
- **Docs**: architecture diagrams and sample manuscript PDFs in `docs/`.

## Quickstart (local)
Requirements: Node 18+, Python 3.11+, Azure Functions Core Tools, and access to Azure resources (Blob + Table Storage, Azure AI project/deployment).

1) Install frontend deps and run:
```bash
npm install
npm run dev
```

2) Python deps for Functions/IDCA:
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

3) Set environment (for local runs, e.g. in `.env`):
```
AzureWebJobsStorage=DefaultEndpointsProtocol=...      # Blob + Table storage
PROJECT_ENDPOINT=https://<your-azure-ai-endpoint>
MODEL_DEPLOYMENT=<your-model-deployment-name>
IDCA_AGENT_ID=<agent-id>
```

4) Run services locally (ensure venv is activated):
```bash
start_services.ps1
```

5) Stop services locally (ensure venv is activated):
```bash
stop_services.ps1
```

6) Run IDCA manually (CLI) after uploading a file:
```bash
python backend/idca/idca.py
# Enter request_id printed from the upload response
```

## API surface
- `POST /upload` (ingestion): multipart `file` → returns `request_id`, stores to Blob/Table.
- `GET /requests` | `GET /requests/{id}` | `GET /requests/{id}/status` | `DELETE /requests/{id}` | `POST /requests/{id}/retry`.
- `POST /assess` body `{request_id}`: marks status “analyzing” (pre-NAA).
- `POST /worker/run/{request_id}`: runs novelty analysis and writes results.
- `GET /assess/{request_id}` | `GET /assess/{request_id}/status`: read NAA outputs.

## Flow
1. Frontend uploads manuscript → Blob + ingestion table entry (`status=uploaded`).
2. Operator runs IDCA → extracts PDF text, calls Azure AI Agent → writes `idca_output`, `status=classified`.
3. NAA endpoint consumes `idca_output`, queries open prior‑art APIs, scores novelty, and updates the ingestion table (`status=assessed`, scores, matches).

## Notes
- Open prior‑art search uses public endpoints (PatentsView, OpenAlex, Semantic Scholar); no keys required.
- PDF text extraction uses `PyPDF2`/`pypdf`; scanned PDFs will need OCR.
- Update the frontend upload URL in `src/components/UploadDropzone.jsx` to point at your deployed ingestion Function URL with function code.


