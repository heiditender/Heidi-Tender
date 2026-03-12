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
python src/core/main.py /path/to/tender-pack \
  --output output.json
```

The full OpenAI response is saved to `src/output.json` (or the path you pass via `--output`).

## Notes

- Only common file types are uploaded (`pdf, docx, xlsx, pptx, csv, txt, md, json, html, xml, rtf, odt, xls, doc`).
- Files larger than 512MB are skipped.
- This uses `input_file` for each uploaded file and requests JSON output.
- LLM outputs are validated with Pydantic before writing/using them.
- Generated SQL is safety-checked (single `SELECT`, no comments, no multi-statements, allowlisted tables only) before execution.

## Knowledge Base Pipeline

The main entrypoint can bootstrap KB automatically before tender processing:

```bash
python src/core/main.py /path/to/tender-pack \
  --kb-src "/path/to/raw-lighting-kb" \
  --kb-base-dir "/path/to/light_kb_minimal_preprocessed" \
  --kb-vector-store-name "lighting_kb" \
  --kb-key "lighting_kb"
```

Standalone KB modules are still available under `src/core/kb/`:

```bash
PYTHONPATH=src/core python -m kb.kb_builder \
  --src "/path/to/raw-lighting-kb" \
  --base-dir "/path/to/light_kb_minimal_preprocessed" \
  --force
```

Vector store sync:

```bash
PYTHONPATH=src/core python -m kb.vector_store_sync \
  --base-dir "/path/to/light_kb_minimal_preprocessed" \
  --vector-store-name "lighting_kb"
```

The uploader first checks whether a matching KB (same `kb_key` + manifest fingerprint) already exists under the current API key.  
If found, it returns that store; otherwise it creates and uploads.
