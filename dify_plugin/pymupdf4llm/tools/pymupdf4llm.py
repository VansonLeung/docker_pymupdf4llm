from collections.abc import Generator, Mapping
import base64
import binascii
import tempfile
from pathlib import Path
from typing import Any
from urllib.request import urlopen

import markdown as mdlib
import pymupdf
import pymupdf4llm
from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage


class Pymupdf4llmTool(Tool):
    @staticmethod
    def _to_bool(value: Any, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "y", "on"}
        return default

    @staticmethod
    def _md_to_html(text: str) -> str:
        return mdlib.markdown(
            text,
            extensions=["extra", "tables", "fenced_code", "sane_lists", "toc"],
        )

    @staticmethod
    def _as_dict(value: Any) -> dict[str, Any] | None:
        if isinstance(value, dict):
            return value
        if isinstance(value, Mapping):
            return dict(value)

        for method_name in ("model_dump", "dict", "to_dict"):
            method = getattr(value, method_name, None)
            if callable(method):
                try:
                    dumped = method()
                    if isinstance(dumped, dict):
                        return dumped
                except Exception:
                    pass

        # Fallback for object-like values.
        if hasattr(value, "__dict__"):
            try:
                data = dict(vars(value))
                if data:
                    return data
            except Exception:
                pass
        return None

    @staticmethod
    def _parse_file_parameter(pdf_file: Any) -> bytes | None:
        if pdf_file is None:
            return None
        if isinstance(pdf_file, bytes):
            return pdf_file
        if isinstance(pdf_file, str):
            p = Path(pdf_file)
            if p.exists() and p.is_file():
                return p.read_bytes()
            return None
        as_dict = Pymupdf4llmTool._as_dict(pdf_file)
        if as_dict is not None:
            # Try common fields that Dify / integrations may pass.
            for path_key in ("path", "local_path", "tmp_path", "file_path"):
                candidate = as_dict.get(path_key)
                if isinstance(candidate, str):
                    p = Path(candidate)
                    if p.exists() and p.is_file():
                        return p.read_bytes()

            for b64_key in ("base64", "content", "data"):
                candidate = as_dict.get(b64_key)
                if isinstance(candidate, str):
                    raw = candidate.split(",", 1)[-1] if "," in candidate else candidate
                    try:
                        return base64.b64decode(raw, validate=False)
                    except binascii.Error:
                        continue

            for url_key in ("url", "download_url", "remote_url", "preview_url"):
                candidate = as_dict.get(url_key)
                if isinstance(candidate, str) and candidate.startswith(("http://", "https://")):
                    with urlopen(candidate, timeout=60) as resp:  # nosec B310
                        return resp.read()

        return None

    def _load_pdf_bytes(self, tool_parameters: dict[str, Any]) -> bytes:
        # Preferred: structured file input.
        pdf_file = tool_parameters.get("pdf_file")
        parsed = self._parse_file_parameter(pdf_file)
        if parsed:
            return parsed

        # Alternative: local path.
        pdf_path = tool_parameters.get("pdf_path")
        if isinstance(pdf_path, str) and pdf_path.strip():
            path = Path(pdf_path.strip())
            if not path.exists() or not path.is_file():
                raise ValueError(f"pdf_path not found: {pdf_path}")
            return path.read_bytes()

        # Alternative: remote URL.
        pdf_url = tool_parameters.get("pdf_url")
        if isinstance(pdf_url, str) and pdf_url.startswith(("http://", "https://")):
            with urlopen(pdf_url, timeout=60) as resp:  # nosec B310
                return resp.read()

        # Alternative: base64 payload.
        pdf_base64 = tool_parameters.get("pdf_base64")
        if isinstance(pdf_base64, str) and pdf_base64.strip():
            raw = pdf_base64.split(",", 1)[-1] if "," in pdf_base64 else pdf_base64
            try:
                return base64.b64decode(raw, validate=False)
            except binascii.Error as exc:
                raise ValueError(f"Invalid pdf_base64 content: {exc}") from exc

        raise ValueError(
            "No PDF input provided. Use one of: pdf_file, pdf_path, pdf_url, or pdf_base64."
        )

    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage]:
        try:
            pdf_bytes = self._load_pdf_bytes(tool_parameters)
            dpi = int(tool_parameters.get("dpi", 150) or 150)
            extract_images = self._to_bool(tool_parameters.get("extract_images", False), False)
            image_format = str(tool_parameters.get("image_format", "png") or "png").lower()
            max_images = int(tool_parameters.get("max_images", 30) or 30)
            if max_images < 1:
                max_images = 1

            with tempfile.TemporaryDirectory(prefix="dify-pymupdf4llm-") as tmp:
                pdf_path = Path(tmp) / "input.pdf"
                images_dir = Path(tmp) / "images"
                pdf_path.write_bytes(pdf_bytes)
                images_dir.mkdir(parents=True, exist_ok=True)

                full_markdown = pymupdf4llm.to_markdown(
                    str(pdf_path),
                    dpi=dpi,
                    write_images=extract_images,
                    image_path=str(images_dir),
                    image_format=image_format,
                )
                chunks = pymupdf4llm.to_markdown(str(pdf_path), page_chunks=True, dpi=dpi)

                pages_markdown = [str(c.get("text", "")) for c in chunks if isinstance(c, dict)]
                pages_html = [self._md_to_html(md) for md in pages_markdown]
                full_html = self._md_to_html(full_markdown)

                # Plain text via PyMuPDF page extraction.
                with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
                    pages_text = [page.get_text("text") for page in doc]
                full_text = "\n".join(pages_text)

                image_files = sorted([p for p in images_dir.glob("*") if p.is_file()])
                emitted_images: list[str] = []
                if extract_images:
                    for image_path in image_files[:max_images]:
                        emitted_images.append(image_path.name)
                        suffix = image_path.suffix.lower().lstrip(".")
                        mime_type = f"image/{suffix if suffix else image_format}"
                        yield self.create_blob_message(
                            blob=image_path.read_bytes(),
                            meta={
                                "filename": image_path.name,
                                "mime_type": mime_type,
                            },
                        )

            result = {
                "input": {
                    "dpi": dpi,
                    "bytes": len(pdf_bytes),
                    "extract_images": extract_images,
                    "image_format": image_format,
                    "max_images": max_images,
                },
                "output": {
                    "markdown": {
                        "full": full_markdown,
                        "pages": pages_markdown,
                    },
                    "text": {
                        "full": full_text,
                        "pages": pages_text,
                    },
                    "html": {
                        "full": full_html,
                        "pages": pages_html,
                    },
                    "images": {
                        "count": len(emitted_images),
                        "names": emitted_images,
                    },
                },
            }

            yield self.create_json_message(result)
        except Exception as exc:
            yield self.create_json_message({"error": str(exc)})
