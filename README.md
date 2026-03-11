# suisse-bid-match

Minimal workflow to upload tender pack files to OpenAI Files API and run a DSPy-driven extraction + SQL match.

## Setup

```bash
cd suisse-bid-match
python -m venv .venv
source .venv/bin/activate
pip install -r src/requirements.txt
```

Set your API key:

```bash
export OPENAI_API_KEY="..."
```

Optional envs:

- `OPENAI_MODEL` (default: `gpt-5-mini`)
- `OPENAI_BASE_URL` (default: `https://api.openai.com/v1`)
- `OPENAI_FILE_PURPOSE` (default: `user_data`)

## Run

```bash
python src/core/upload_and_extract.py /path/to/tender-pack \
  --output output.json
```

The full OpenAI response is saved to `src/output.json` (or the path you pass via `--output`).

## Notes

- Only common file types are uploaded (`pdf, docx, xlsx, pptx, csv, txt, md, json, html, xml, rtf, odt, xls, doc`).
- Files larger than 512MB are skipped.
- This uses `input_file` for each uploaded file and requests JSON output.
