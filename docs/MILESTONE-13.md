# M13 — Safe Resource Connectors

## Goal

Expand resource sources beyond inline docs/git without turning SourceBrief workers into unsafe egress or local-file readers. M13 adds bounded URL and upload connectors plus a pre-index secret redaction pass.

## Delivered behavior

- URL resources (`type=url|web|webpage|website|http|https`) fetch public HTTP(S) text-like content.
- URL fetches enforce:
  - public DNS/IP targets only; localhost/private/internal IPs are rejected before each request, including redirects
  - no URL credentials
  - HTTP(S) only
  - content-type must be text-like
  - `max_url_bytes`, `fetch_timeout`, and redirect-count hard caps
  - persisted URL metadata/citations strip query strings, fragments, and credentials
- Upload resources (`type=upload|uploaded_file|file_upload`) ingest API/CLI-supplied text/base64 content.
- Upload connector refuses local path fields (`path`, `file_path`, `local_path`) so the worker never reads arbitrary host paths from API input.
- Secret redaction runs before chunking, embeddings, code symbol extraction, and graph indexing.
- Snapshot metadata records `redacted_secret_counts` without storing plaintext secrets.
- Connector failures surface through existing index-run `failed` status and `error_message`.

## Redaction patterns

Alpha redaction covers common high-risk secrets:

- AWS access key IDs
- AWS secret access key assignments
- GitHub tokens
- Slack tokens
- OpenAI-style keys
- generic `api_key`, `token`, `secret`, `password` assignments

This is not a DLP product. It is a practical pre-index safety net to avoid accidental plaintext secrets in chunks/embeddings.

## API examples

Create a URL resource (send your bearer token in the Authorization header):

```bash
curl -X POST "$SOURCEBRIEF_API/workspaces/$WS/projects/$PROJECT/resources" \
  -H "Content-Type: application/json" \
  --data @url-resource.json
```

`url-resource.json`:

```json
{
  "type": "url",
  "name": "Architecture doc",
  "uri": "https://example.com/architecture.html",
  "source_config": {"url": "https://example.com/architecture.html", "max_url_bytes": 2000000}
}
```

Create an upload resource:

```bash
curl -X POST "$SOURCEBRIEF_API/workspaces/$WS/projects/$PROJECT/resources" \
  -H "Content-Type: application/json" \
  --data @upload-resource.json
```

`upload-resource.json`:

```json
{
  "type": "upload",
  "name": "Runbook upload",
  "uri": "upload://runbook.md",
  "source_config": {"filename": "runbook.md", "content_type": "text/markdown", "content": "# Runbook"}
}
```

## CLI examples

```bash
sourcebrief resource add-url \
  --workspace-id $WS --project-id $PROJECT \
  --name "Architecture doc" \
  --url https://example.com/architecture.html \
  --refresh --wait

sourcebrief resource add-upload \
  --workspace-id $WS --project-id $PROJECT \
  --name "Runbook upload" \
  --path ./runbook.md \
  --content-type text/markdown \
  --refresh --wait
```

## Verification

Required gate for M13:

```bash
make lint
.venv/bin/pytest tests/unit tests/integration -q
make qa-smoke
```

Coverage includes:

- URL validation rejects unsafe schemes/hosts/credentials
- URL redirect-to-localhost is blocked before the redirected request is made
- URL query secrets are stripped from persisted paths/metadata
- mocked URL fetch checks size/content-type/html text extraction
- invalid URL bounds and oversized upload settings return 422
- upload connector rejects local path reads
- upload ingestion redacts secrets before search/snapshot metadata
- CLI `add-url` and `add-upload` request payloads plus local file size precheck
- real Docker QA smoke exercises upload + redaction through API → RQ worker → search/snapshot path
