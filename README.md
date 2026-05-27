# AMIE on Azure

AMIE is an Azure-hosted manuscript analysis pipeline that takes an uploaded source document, determines whether it discloses an invention, retrieves and evaluates reference manuscripts, and produces a final assessment report.

Live frontend:
- [https://amie-azure-gtm4.vercel.app/](https://amie-azure-gtm4.vercel.app/)

The system is built around:
- Azure Function Apps for each major stage of the workflow
- Azure Storage for uploads, transient reference-manuscript storage, queueing, and request tracking
- Microsoft AI Foundry agents for the LLM-driven parts of the pipeline

## What The Project Does

At a high level, AMIE processes one uploaded manuscript through four agent stages:

1. Ingestion
   The manuscript is uploaded from the frontend and stored in Azure Blob Storage.
2. IDCA
   The Invention Detection and Classification Agent determines whether the manuscript discloses a concrete invention and extracts a structured representation.
3. NAA
   The Novelty Assessment pipeline expands the structure into search criteria, finds reference manuscripts, stores them, and assesses structural overlap.
4. AA
   The Aggregation Agent produces the final human-readable report returned to the UI.

## Architecture

### Frontend

- `frontend/`
- React + Vite web app
- Primary user entrypoint for uploads and result viewing
- Production deployment is the Vercel app linked above

### Azure Function Apps

#### 1. Ingestion Function App

- `backend/ingestion-agent/`
- Public upload and status API used by the current web frontend
- Accepts the upload, writes the source manuscript to Blob Storage, creates the tracking row in Table Storage, and places the `request_id` on an Azure Queue
- Exposes request/status endpoints used by the frontend

Key endpoints:
- `POST /api/upload`
- `GET /api/requests`
- `GET /api/requests/{request_id}`
- `GET /api/requests/{request_id}/status`
- `DELETE /api/requests/{request_id}`
- `POST /api/requests/{request_id}/retry`

#### 2. IDCA Function App

- `backend/idca_func/`
- Receives the queued `request_id`
- Claims the job in table storage to avoid duplicate processing
- Pulls the uploaded source manuscript from blob storage
- Uses Azure Document Intelligence to extract text
- Uses a Microsoft AI Foundry agent to classify invention presence and return structured JSON
- If invention is `Present`, triggers NAA
- If invention is `Implied` or `Absent`, skips NAA and triggers AA directly

Key endpoint:
- `POST /api/idca/run/{request_id}`

#### 3. NAA Function App

- `backend/naa-amie-azure-clean/`
- Runs the novelty workflow after IDCA marks the manuscript as invention-present
- Uses Microsoft AI Foundry agents to build:
  - Source Structure
  - Structural Scoring Rubric
  - Source Structure synopsis
  - UCS search query
- Searches for prior art / reference manuscripts
- Downloads and stores those references
- Assesses the stored references in parallel
- Persists the NAA output and triggers AA

Key endpoints:
- `POST /api/worker/run/{request_id}`
- `POST /api/assess`
- `GET /api/assess/{request_id}`
- `GET /api/assess/{request_id}/status`

#### 4. AA Function App

- `backend/aa/`
- Reads IDCA and NAA outputs
- Uses the Aggregation Agent in Microsoft AI Foundry
- Produces the final report for the request
- Marks the request as `completed`

Key endpoint:
- `POST /api/aa/run/{request_id}`

### Alternate Gateway

- `backend/amie-a2a/`
- Contains an A2A / JSON-RPC-style gateway and upload flow
- This is part of the repo, but the current production web workflow is primarily documented here around `frontend/` + `backend/ingestion-agent/`

## Microsoft AI Foundry Usage

AMIE uses Microsoft AI Foundry agents rather than calling one monolithic prompt for the whole workflow.

Current agent-driven responsibilities in the repo:
- IDCA agent:
  invention detection and classification
- SS agent:
  source structure generation
- SSR agent:
  structural scoring rubric generation
- SS synopsis agent:
  one-sentence structure summary
- UCS builder agent:
  search criteria/query construction
- Aggregation agent:
  final report generation

The code uses the Azure AI Agents SDK and an Azure AI project endpoint, for example through `AgentsClient(...)` plus stored agent IDs in environment variables.

## Azure Storage Layout

AMIE uses Azure Storage in three different ways.

### 1. Main source-manuscript container

Container:
- `manuscript-uploads`

Used for:
- original uploaded source manuscripts
- large generated artifacts that are offloaded from table storage when they exceed table limits

Examples stored here:
- uploaded manuscript blob named from the `request_id`
- `naa-outputs/{request_id}.json`
- `aa-outputs/{request_id}.md`

### 2. Request tracking table

Table:
- `IngestionRequests`

Each manuscript creates one row keyed by:
- `PartitionKey = "AMIE"`
- `RowKey = request_id`

This table tracks:
- filename / blob path
- status
- timestamps
- IDCA output
- NAA output or blob pointer
- AA output or blob pointer
- failures / error messages

### 3. Queue

Queue:
- `idca-queue`

Used to decouple upload from long-running analysis. The ingestion app enqueues the `request_id`, and a queue-triggered worker posts that request to the IDCA Function App.

## Reference Manuscript Storage

Reference manuscripts are stored separately from the original source manuscript.

During NAA:
- the source manuscript remains in `manuscript-uploads`
- the discovered reference manuscripts are downloaded into their own per-request Azure Blob container

Container naming convention:
- `<request-id>-rms`

Example:
- if the request ID is `1234abcd`, the RM container is `1234abcd-rms`

What goes into that RM container:
- downloaded PDFs for papers and articles
- text files for patent material when patent text is retrieved instead of a PDF

How those references are used:
1. NAA search returns a list of candidate reference manuscripts
2. each candidate is downloaded and stored in the request-specific RM container
3. each stored RM is assessed against the source structure / scoring rubric
4. the structured assessment results are added to the NAA output
5. AA uses those results to generate the final report

Current cleanup behavior:
- RM containers are treated as temporary working storage
- cleanup is scheduled after retrieval
- in the current code, cleanup is scheduled for 15 minutes after creation

## End-To-End Workflow

This is the current processing flow from start to finish.

### Step 1. User uploads a manuscript

The frontend sends the file to the ingestion Function App.

What happens:
- the file is written to the `manuscript-uploads` blob container
- a new `request_id` is generated
- a row is created in `IngestionRequests`
- status is set to `uploaded` and then `queued`
- the `request_id` is added to `idca-queue`

### Step 2. Queue worker triggers IDCA

The ingestion app's queue trigger reads the `request_id` from `idca-queue` and calls the standalone IDCA Function App.

What happens:
- IDCA claims the job using optimistic concurrency
- status becomes `classifying`
- the uploaded source manuscript is loaded from blob storage
- text is extracted using Azure Document Intelligence

### Step 3. IDCA runs in Microsoft AI Foundry

The IDCA logic:
- creates a Foundry thread
- sends the IDCA prompt
- sends the manuscript text in chunks
- starts the agent run
- polls until the run completes
- validates the returned JSON

What gets written back:
- `idca_output`
- status `classified`

### Step 4. Branch based on invention detection

If `status_determination` is:

- `Present`
  IDCA triggers the NAA Function App
- `Implied` or `Absent`
  NAA is skipped and AA is triggered directly

### Step 5. NAA builds the novelty analysis package

For invention-present manuscripts, NAA:
- rebuilds the source structure
- builds the structural scoring rubric
- creates the structure synopsis
- creates a UCS search string
- searches external sources for reference manuscripts

### Step 6. Reference manuscripts are downloaded and stored

NAA downloads discovered references into:
- `<request-id>-rms`

This gives each source manuscript its own isolated reference-manuscript working set.

### Step 7. Reference manuscripts are assessed

NAA then:
- reads the stored RM files
- compares each RM against the source structure and rubric
- runs assessments in parallel
- records which references were stored, which were assessed, and which failed

The NAA output contains:
- source structure data
- rubric data
- UCS
- list of references
- assessment summaries
- pipeline metadata such as total found, stored, and assessed

### Step 8. NAA persists results

NAA writes its results to the request record.

Depending on size:
- small NAA payloads are stored directly in table storage
- larger ones are written to `manuscript-uploads/naa-outputs/{request_id}.json` and referenced from the table row

Status becomes:
- `assessed`

### Step 9. AA generates the final report

AA reads:
- the IDCA output
- the NAA output and assessments

Then it uses the Aggregation Agent in Microsoft AI Foundry to produce the final markdown report.

Depending on size:
- smaller reports are stored directly in the table row
- larger reports are stored in `manuscript-uploads/aa-outputs/{request_id}.md`

Final status:
- `completed`

## Request Status Lifecycle

Common statuses used across the pipeline:

- `uploaded`
- `queued`
- `classifying`
- `classified`
- `analyzing`
- `assessed`
- `completed`
- `failed`

Typical paths:

- No invention path:
  `uploaded -> queued -> classifying -> classified -> completed`

- Invention present path:
  `uploaded -> queued -> classifying -> classified -> analyzing -> assessed -> completed`

## Repository Layout

```text
frontend/                      React + Vite frontend
backend/ingestion-agent/       Upload API, status API, queue trigger
backend/idca_func/             IDCA Function App and IDCA logic
backend/naa-amie-azure-clean/  Novelty Assessment workflow
backend/aa/                    Aggregation Agent Function App
backend/amie-a2a/              Alternate A2A / JSON-RPC gateway
```

## How To Run

There are two practical ways to run this repo.

### Option 1. Frontend locally, Azure backends remotely

This is the easiest way to use the current deployed pipeline.

Requirements:
- Node.js 18+
- Python 3.11+
- Azure Functions Core Tools

Install dependencies:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

cd frontend
npm install
cd ..
```

Start the local frontend plus the current configured backend mode:

```powershell
.\start_services.ps1
```

What this currently does:
- starts the frontend locally
- starts the A2A gateway locally
- leaves the main ingestion / IDCA / NAA / AA pipeline pointed at deployed Azure Function Apps unless you uncomment the local-start lines in the script

### Option 2. Run the Function Apps locally

If you want the full pipeline local-to-your-machine, start each Function App with Azure Functions Core Tools.

Typical ports already documented in the repo:
- Ingestion: `7071`
- IDCA: `7072`
- NAA: `7073`
- AA: `7074`
- A2A: `7075`
- Frontend: `5173`

Example:

```powershell
cd backend\ingestion-agent
func start --port 7071
```

Repeat that pattern for:
- `backend\idca_func`
- `backend\naa-amie-azure-clean`
- `backend\aa`
- `backend\amie-a2a`

Then start the frontend:

```powershell
cd frontend
npm run dev
```

## Environment Variables

The exact settings differ a little by Function App, but the main services you need configured are:

### Azure Storage

- `AZURE_STORAGE_CONNECTION_STRING` or `AzureWebJobsStorage`
- `STORAGE_ACCOUNT_NAME` for identity-based storage access in some paths

### Microsoft AI Foundry / Azure AI Agents

- `PROJECT_ENDPOINT`
- `IDCA_AGENT_ID`
- `AGGREGATION_AGENT_ID`
- `SS_Agent_ID`
- `SSR_Agent_ID`
- `SS_Synopsis_Agent_ID`
- `UCS_Builder_Agent_ID`

### Document Intelligence

- `DOC_INTELLIGENCE_ENDPOINT`
- `DOC_INTELLIGENCE_KEY`

### Function-to-function triggers

- `IDCA_BASE`
- `IDCA_FUNCTION_KEY`
- `NAA_BASE`
- `NAA_FUNCTION_KEY`
- `AA_BASE`
- `AA_FUNCTION_KEY`

### External data / search

- `PATENTS_VIEW_KEY`

### Frontend

The frontend expects the API base / function keys to be configured through Vite environment variables.

For the hosted Vercel frontend, set:

- `VITE_API_BASE`
- `VITE_API_CODE`
- `VITE_INGESTION_AGENT_FUNCTION_KEY`

Production example:

```env
VITE_API_BASE=https://amie-ingestion-fn-hyd0hkd0hzfmawep.westus2-01.azurewebsites.net
VITE_API_CODE=...
VITE_INGESTION_AGENT_FUNCTION_KEY=...
```

The Azure ingestion Function App must allow the deployed Vercel origin in CORS:

- `https://amie-azure-gtm4.vercel.app`

Only the ingestion Function App is called directly by the browser. IDCA, NAA, and AA are triggered server-to-server from Azure Functions and do not need browser CORS for normal operation.

## What To Tell Reviewers

If you need to explain the system quickly:

"AMIE is a multi-stage Azure pipeline. The frontend uploads a manuscript to an ingestion Function App, the manuscript is stored in Azure Blob Storage, and the request is tracked in Azure Table Storage. A queue triggers the IDCA Function App, which uses a Microsoft AI Foundry agent to determine whether the manuscript discloses an invention. If it does, the NAA Function App retrieves reference manuscripts into a separate `<request-id>-rms` container, assesses them, and then the AA Function App uses another Foundry agent to generate the final report."

## Notes

- The frontend used by stakeholders is the Vercel deployment linked at the top of this file.
- The repo currently contains both the main web workflow and an alternate A2A gateway implementation.
- Large NAA and AA payloads are intentionally offloaded from Table Storage into Blob Storage to stay within Azure Table size limits.
