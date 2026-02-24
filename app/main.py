from __future__ import annotations

import json
import importlib
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any, Literal

import markdown as mdlib
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from starlette.background import BackgroundTask

app = FastAPI(
    title="PyMuPDF4LLM API",
    version="1.0.0",
    description=(
        "Upload a PDF and receive markdown / HTML / page chunks / image artifacts. "
        "Supports ZIP artifact download and JSON response modes."
    ),
    docs_url="/swagger",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    openapi_tags=[
        {"name": "system", "description": "Service health and metadata endpoints."},
        {"name": "pdf", "description": "PDF conversion and extraction endpoints."},
    ],
)


def _cleanup_path(path: Path) -> None:
    if path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path, ignore_errors=True)


def _markdown_to_html(markdown_text: str) -> str:
    return mdlib.markdown(
        markdown_text,
        extensions=["extra", "tables", "fenced_code", "sane_lists", "toc"],
    )


def _normalize_page_chunks(page_chunks: Any) -> list[dict[str, Any]]:
    if not isinstance(page_chunks, list):
        return []
    normalized: list[dict[str, Any]] = []
    for chunk in page_chunks:
        if isinstance(chunk, dict):
            normalized.append(chunk)
    return normalized


def _activate_layout_if_requested(use_layout: bool) -> bool:
    if not use_layout:
        return False
    try:
        import pymupdf.layout  # noqa: F401

        return True
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                "use_layout=true requested, but pymupdf-layout is unavailable in this image. "
                "Build with ENABLE_LAYOUT=true (recommended PYTHON_VERSION=3.12). "
                f"Details: {exc}"
            ),
        ) from exc


def _get_pymupdf4llm(use_layout: bool):
    _activate_layout_if_requested(use_layout)
    module = importlib.import_module("pymupdf4llm")
    if use_layout:
        module = importlib.reload(module)
    return module


def _safe_to_markdown(lib: Any, doc_path: str, **kwargs: Any):
    try:
        return lib.to_markdown(doc_path, **kwargs)
    except Exception as exc:
        if "min() iterable argument is empty" not in str(exc):
            raise
        retry_kwargs = dict(kwargs)
        retry_kwargs["hdr_info"] = False
        return lib.to_markdown(doc_path, **retry_kwargs)


@app.get(
    "/health",
    tags=["system"],
    summary="Health check",
    description="Returns API health status.",
)
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/api/v1/pdf/process",
    response_model=None,
    tags=["pdf"],
    summary="Process uploaded PDF",
    description=(
        "Upload a PDF file and process it with PyMuPDF4LLM. "
        "Set response_format=json for inline JSON data, or response_format=zip "
        "to download artifact files (markdown/html/pages/images/manifest)."
    ),
    responses={
        200: {
            "description": "Successful processing. Returns application/zip or application/json.",
            "content": {
                "application/json": {
                    "example": {
                        "manifest": {
                            "job_id": "8a14b3c42f124ec2bf5f6c1d0c8e2a8d",
                            "filename": "sample.pdf",
                            "dpi": 150,
                            "write_images": True,
                            "embed_images": False,
                            "layout_active": False,
                            "page_count": 3,
                            "images": ["input.pdf-0-0.png"],
                            "files": {
                                "full_markdown": "full.md",
                                "full_html": "full.html",
                                "pages_dir": "pages/",
                                "pages_html_dir": "pages_html/",
                                "images_dir": "images/",
                            },
                        },
                        "full_markdown": "# Title\\n...",
                        "full_html": "<h1 id=\"title\">Title</h1>",
                        "layout_active": False,
                        "pages": [
                            {
                                "page_number": 1,
                                "markdown": "# Page 1\\n...",
                                "html": "<h1 id=\"page-1\">Page 1</h1>",
                                "metadata": {},
                            }
                        ],
                        "embedded_images": False,
                    }
                },
                "application/zip": {},
            },
        },
        400: {"description": "Invalid request (bad file type or invalid options)."},
        500: {"description": "Internal processing failure."},
    },
)
async def process_pdf(
    file: UploadFile = File(..., description="PDF file to process."),
    response_format: Literal["zip", "json"] = Form(
        "zip",
        description="Output mode: zip artifact package or JSON payload.",
    ),
    dpi: int = Form(150, description="Image rendering DPI for extracted images."),
    write_images: bool = Form(
        True,
        description="Write extracted images to artifact folder (for zip output).",
    ),
    force_text: bool = Form(
        True,
        description="Keep text even when overlapping images/graphics are detected.",
    ),
    embed_images: bool = Form(
        False,
        description="Embed images as base64 in markdown output (mutually exclusive with write_images).",
    ),
    use_layout: bool = Form(
        False,
        description="Enable optional pymupdf-layout mode (requires layout-enabled image).",
    ),
) -> JSONResponse | FileResponse:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF uploads are supported.")

    if write_images and embed_images:
        raise HTTPException(
            status_code=400,
            detail="Choose either write_images=true or embed_images=true, not both.",
        )

    job_id = uuid.uuid4().hex
    workspace = Path(tempfile.mkdtemp(prefix=f"pymupdf4llm-{job_id}-"))
    input_pdf = workspace / "input.pdf"
    artifacts_dir = workspace / "artifacts"
    pages_dir = artifacts_dir / "pages"
    pages_html_dir = artifacts_dir / "pages_html"
    images_dir = artifacts_dir / "images"

    artifacts_dir.mkdir(parents=True, exist_ok=True)
    pages_dir.mkdir(parents=True, exist_ok=True)
    pages_html_dir.mkdir(parents=True, exist_ok=True)
    images_dir.mkdir(parents=True, exist_ok=True)

    try:
        input_pdf.write_bytes(await file.read())
        pymupdf4llm = _get_pymupdf4llm(use_layout)
        layout_active = use_layout

        markdown_kwargs = {
            "dpi": dpi,
            "force_text": force_text,
            "write_images": write_images,
            "embed_images": embed_images,
            "image_path": str(images_dir),
        }

        full_markdown = _safe_to_markdown(pymupdf4llm, str(input_pdf), **markdown_kwargs)
        chunks_raw = _safe_to_markdown(
            pymupdf4llm,
            str(input_pdf),
            page_chunks=True,
            dpi=dpi,
            force_text=force_text,
            write_images=False,
            embed_images=False,
        )

        page_chunks = _normalize_page_chunks(chunks_raw)

        full_html = _markdown_to_html(full_markdown)

        (artifacts_dir / "full.md").write_text(full_markdown, encoding="utf-8")
        (artifacts_dir / "full.html").write_text(full_html, encoding="utf-8")

        for idx, chunk in enumerate(page_chunks, start=1):
            page_text = str(chunk.get("text", ""))
            (pages_dir / f"page-{idx:04d}.md").write_text(page_text, encoding="utf-8")
            (pages_html_dir / f"page-{idx:04d}.html").write_text(
                _markdown_to_html(page_text),
                encoding="utf-8",
            )

        manifest = {
            "job_id": job_id,
            "filename": file.filename,
            "dpi": dpi,
            "write_images": write_images,
            "embed_images": embed_images,
            "layout_active": layout_active,
            "page_count": len(page_chunks),
            "images": sorted([p.name for p in images_dir.glob("*") if p.is_file()]),
            "files": {
                "full_markdown": "full.md",
                "full_html": "full.html",
                "pages_dir": "pages/",
                "pages_html_dir": "pages_html/",
                "images_dir": "images/",
            },
        }
        (artifacts_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        if response_format == "zip":
            zip_path = workspace / "result"
            archive_path = shutil.make_archive(str(zip_path), "zip", root_dir=artifacts_dir)
            archive = Path(archive_path)
            return FileResponse(
                path=archive,
                media_type="application/zip",
                filename=f"{Path(file.filename).stem}-artifacts.zip",
                background=BackgroundTask(_cleanup_path, workspace),
            )

        response = {
            "manifest": manifest,
            "full_markdown": full_markdown,
            "full_html": full_html,
            "layout_active": layout_active,
            "pages": [
                {
                    "page_number": i,
                    "markdown": str(chunk.get("text", "")),
                    "html": _markdown_to_html(str(chunk.get("text", ""))),
                    "metadata": chunk.get("metadata", {}),
                }
                for i, chunk in enumerate(page_chunks, start=1)
            ],
            "embedded_images": embed_images,
        }

        _cleanup_path(workspace)
        return JSONResponse(response)

    except HTTPException:
        _cleanup_path(workspace)
        raise
    except Exception as exc:
        _cleanup_path(workspace)
        raise HTTPException(status_code=500, detail=f"Processing failed: {exc}") from exc


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)
