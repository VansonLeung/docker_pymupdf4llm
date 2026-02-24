# PyMuPDF4LLM FastAPI Docker API

This project exposes a PDF processing API using `FastAPI` + `pymupdf4llm`.

## Features

- Python 3.13
- Optional `pymupdf-layout` mode (recommended with Python 3.12 + `onnxruntime`)
- Upload PDF and process with `pymupdf4llm`
- Output artifacts:
  - `full.md` (full markdown)
  - `full.html` (HTML rendered from markdown)
  - `pages/page-XXXX.md` (page-by-page markdown)
  - `pages_html/page-XXXX.html` (page-by-page HTML)
  - `images/*` (image attachments when `write_images=true`)
  - `manifest.json`
- Docker files for:
  - linux/amd64
  - linux/arm64 (for Apple Silicon Docker host)

## API

- Health: `GET /health`
- Processing: `POST /api/v1/pdf/process`

### Form fields

- `file` (required): PDF file
- `response_format`: `zip` (default) or `json`
- `dpi`: image rendering DPI (default `150`)
- `write_images`: `true/false` (default `true`)
- `force_text`: `true/false` (default `true`)
- `embed_images`: `true/false` (default `false`)
- `use_layout`: `true/false` (default `false`, requires layout-enabled image)

> `write_images=true` and `embed_images=true` are mutually exclusive.

## Build images

From project root:

### 1) linux/amd64 image

```bash
docker build -f docker/Dockerfile.amd64 -t pymupdf4llm-api:amd64 .
```

### 2) linux/arm64 image

```bash
docker build -f docker/Dockerfile.arm64 -t pymupdf4llm-api:arm64 .
```

### 3) Optional layout-enabled linux/amd64 image (Python 3.12)

```bash
docker build \
  -f docker/Dockerfile.amd64 \
  --build-arg PYTHON_VERSION=3.12 \
  --build-arg ENABLE_LAYOUT=true \
  -t pymupdf4llm-api:layout-amd64 .
```

### 4) Optional layout-enabled linux/arm64 image (Python 3.12)

```bash
docker build \
  -f docker/Dockerfile.arm64 \
  --build-arg PYTHON_VERSION=3.12 \
  --build-arg ENABLE_LAYOUT=true \
  -t pymupdf4llm-api:layout-arm64 .
```

## Run

```bash
docker run --rm -p 8000:8000 pymupdf4llm-api:amd64
```

or

```bash
docker run --rm -p 8000:8000 pymupdf4llm-api:arm64
```

Layout-enabled image:

```bash
docker run --rm -p 8000:8000 pymupdf4llm-api:layout-arm64
```

Open API docs:

- http://localhost:8000/swagger

## Run with Docker Compose

Start amd64 service:

```bash
docker compose up pymupdf4llm-api-amd64
```

Start arm64 service:

```bash
docker compose up pymupdf4llm-api-arm64
```

Start layout-enabled amd64 service:

```bash
docker compose up pymupdf4llm-api-layout-amd64
```

Start layout-enabled arm64 service:

```bash
docker compose up pymupdf4llm-api-layout-arm64
```

## Run Locally (without Docker)

From project root:

### 1) Create and activate virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2) Install dependencies

Base mode:

```bash
pip install -U pip
pip install -r requirements.txt
```

Optional layout mode:

```bash
pip install -r requirements-layout.txt
```

### 3) Start the API server

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Or run as a module:

```bash
python3 -m app.main
```

Open API docs:

- http://localhost:8000/swagger

## Swagger / OpenAPI

- Swagger UI: http://localhost:8000/swagger
- ReDoc: http://localhost:8000/redoc
- OpenAPI JSON: http://localhost:8000/openapi.json

The `/api/v1/pdf/process` endpoint now includes:

- parameter descriptions for all form fields
- example JSON success response
- documented `application/json` and `application/zip` response types

### 4) Quick health check

```bash
curl http://localhost:8000/health
```

Expected response:

```json
{"status":"ok"}
```

### Notes

- `uvicorn app.main:app --reload` is best for development.
- `python3 -m app.main` starts the same app without auto-reload.

## Save and Load Docker Images

Use this when you need to move images between machines (offline / air-gapped).

### 1) Save one image to a tar file

```bash
docker save -o pymupdf4llm-api-amd64.tar pymupdf4llm-api:amd64
```

For arm64:

```bash
docker save -o pymupdf4llm-api-arm64.tar pymupdf4llm-api:arm64
```

For layout image:

```bash
docker save -o pymupdf4llm-api-layout-arm64.tar pymupdf4llm-api:layout-arm64
```

### 2) (Optional) Compress the tar file

```bash
gzip pymupdf4llm-api-amd64.tar
```

This produces `pymupdf4llm-api-amd64.tar.gz`.

### 3) Load image on another machine

If tar is uncompressed:

```bash
docker load -i pymupdf4llm-api-amd64.tar
```

If tar is gzipped:

```bash
gunzip -c pymupdf4llm-api-amd64.tar.gz | docker load
```

### 4) Verify image exists

```bash
docker image ls | grep pymupdf4llm-api
```

### 5) Run loaded image

```bash
docker run --rm -p 8000:8000 pymupdf4llm-api:amd64
```

### Save/load multiple images in one file

```bash
docker save -o pymupdf4llm-bundle.tar \
  pymupdf4llm-api:amd64 \
  pymupdf4llm-api:arm64 \
  pymupdf4llm-api:layout-amd64 \
  pymupdf4llm-api:layout-arm64
```

Load bundle:

```bash
docker load -i pymupdf4llm-bundle.tar
```

## Example cURL

Return ZIP artifacts:

```bash
curl -X POST "http://localhost:8000/api/v1/pdf/process" \
  -F "response_format=zip" \
  -F "dpi=150" \
  -F "write_images=true" \
  -F "force_text=true" \
  -F "embed_images=false" \
  -F "use_layout=false" \
  -F "file=@/absolute/path/to/input.pdf" \
  --output result.zip
```

Return JSON payload:

```bash
curl -X POST "http://localhost:8000/api/v1/pdf/process" \
  -F "response_format=json" \
  -F "use_layout=true" \
  -F "file=@/absolute/path/to/input.pdf"
```

## Notes on PyMuPDF-Layout

- `use_layout=true` requires image build arg `ENABLE_LAYOUT=true`.
- `onnxruntime` wheels can be more reliable on Python 3.12, so layout images are preconfigured to use 3.12.
- If `use_layout=true` is sent to a non-layout image, API returns HTTP 400 with guidance.
