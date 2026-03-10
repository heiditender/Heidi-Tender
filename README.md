# suisse-tender-copilot

Minimal workflow to upload tender pack files to OpenAI Files API and run a single extraction request that returns JSON.

## Setup

```bash
cd suisse-tender-copilot
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
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
./scripts/upload_and_extract.py /path/to/tender-pack \
  --prompt prompts/initial_prompt.txt \
  --output output.json
```

The full OpenAI response is saved to `output.json`.

## Notes

- Only common file types are uploaded (`pdf, docx, xlsx, pptx, csv, txt, md, json, html, xml, rtf, odt, xls, doc`).
- Files larger than 512MB are skipped.
- This uses `input_file` for each uploaded file and requests JSON output.
