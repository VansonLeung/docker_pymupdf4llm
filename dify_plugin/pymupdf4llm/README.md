## pymupdf4llm

**Author:** vansonleung
**Version:** 0.0.1
**Type:** tool

### Description

This Dify tool converts one PDF into JSON outputs with:

- Markdown
	- `output.markdown.full`
	- `output.markdown.pages` (array)
- Plain text
	- `output.text.full`
	- `output.text.pages` (array)
- HTML
	- `output.html.full`
	- `output.html.pages` (array)

Supported inputs (use one):

- `pdf_file` (recommended)
- `pdf_path`
- `pdf_url`
- `pdf_base64`

Optional parameter:

- `dpi` (default `150`)
- `extract_images` (default `false`)
- `image_format` (default `png`)
- `max_images` (default `30`)

When `extract_images=true`, the tool emits image blobs so Dify fills `files[]` in tool output.



