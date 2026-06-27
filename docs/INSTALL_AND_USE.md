# Install and use SourceBrief

This is the short path for a new user. It explains what SourceBrief is good at, how to install it locally, how to add/update resources, and how to connect an agent without reading every architecture note first.

## Why SourceBrief

SourceBrief is a cited context layer for coding agents.

Agents are most useful when they can inspect project evidence before acting. SourceBrief turns repos, runbooks, docs, URLs, uploads, and folder bundles into indexed snapshots that can be queried from the UI, CLI, HTTP API, or MCP.

The product advantage is not "another chat UI". It is evidence discipline:

| Need | SourceBrief advantage |
| --- | --- |
| Onboard to an unfamiliar project | Ask one project-scoped endpoint across repos, docs, runbooks, and symbols. |
| Avoid prompt stuffing | Agents fetch only the cited context they need instead of pasting whole repos into prompts. |
| Trust answers | Answers include citations, snapshot/version metadata, paths, line ranges, hashes, and follow-up read handles. |
| Keep context current | Resource status, refresh runs, coverage warnings, and review artifacts show what was indexed and what may be stale. |
| Use multiple agents | Hermes, Claude Code, Codex, Cursor, and MCP clients can use the same project evidence contract. |
| Stay safe | SourceBrief is read-oriented evidence infrastructure; edits/tests/deploys happen in the coding agent's normal checkout and workflows. |

## 1. Install and start locally

Prerequisites:

- Docker with Compose
- Python 3.11 via `uv`
- Node.js 20+
- npm
- git

```bash
git clone https://github.com/pingchesu/sourcebrief.git
cd sourcebrief
cp .env.example .env
python3 scripts/check_quickstart_prereqs.py
```

Edit `.env` and set an admin password:

```env
SOURCEBRIEF_ADMIN_EMAIL=admin@sourcebrief.local
SOURCEBRIEF_ADMIN_PASSWORD=<choose-a-password>
```

Start the stack:

```bash
make compose-up
make quickstart-ready
```

Open the web UI:

```bash
printf '%s/login\n' "$(make -s print-web-url)"
```

Sign in with the admin email/password from `.env`.

## 2. Install the CLI in the project venv

```bash
make venv
export PATH="$PWD/.venv/bin:$PATH"
export SOURCEBRIEF_API_URL="$(make -s print-api-url)"
sourcebrief login --password-env SOURCEBRIEF_ADMIN_PASSWORD
```

Run the deterministic first-use demo:

```bash
sourcebrief quickstart-demo
sourcebrief ask --resource "Payment retry runbook" "what should an operator do when payment retries fail?"
```

A good result should include a concise answer plus citations. The point is not just that the answer sounds right; it should be inspectable.

## 3. Add resources

Use names for workspace/project. IDs still work as advanced/debug escape hatches, but normal users should not need to copy UUIDs.

```bash
sourcebrief use --workspace "SourceBrief CLI Demo" --project "First useful moment"
```

Add a document:

```bash
sourcebrief resource add-doc \
  --name "Payment retry runbook" \
  --uri doc://payment-retry \
  --content-file ./runbooks/payment-retry.md \
  --refresh \
  --wait
```

Add a Git repository with bounded import settings:

```bash
sourcebrief resource add-repo \
  --name "SourceBrief repo" \
  --repo-url https://github.com/pingchesu/sourcebrief.git \
  --branch main \
  --max-files 500 \
  --max-file-bytes 120000 \
  --max-repo-bytes 18000000 \
  --refresh \
  --wait
```

Add a URL:

```bash
sourcebrief resource add-url \
  --name "Public docs page" \
  --url https://example.com/docs \
  --max-url-bytes 500000 \
  --refresh \
  --wait
```

Add a local upload:

```bash
sourcebrief resource add-upload \
  --name "Architecture note" \
  --path ./docs/architecture.md \
  --refresh \
  --wait
```

## 4. Resource CRUD from the CLI

The CLI supports the daily resource lifecycle:

| Goal | Command |
| --- | --- |
| List resources | `sourcebrief resource list` |
| Show one resource | `sourcebrief resource get --resource-id <id>` |
| Create document/repo/URL/upload resources | `sourcebrief resource add-doc`, `add-repo`, `add-url`, `add-upload` |
| Update metadata/retrieval settings | `sourcebrief resource update --resource-id <id> ...` |
| Update common Git import settings | `sourcebrief resource update-git --resource-id <id> ...` |
| Re-index | `sourcebrief resource refresh --resource-id <id> --wait` |
| Disable without deleting artifacts | `sourcebrief resource archive --resource-id <id>` |
| Soft-delete | `sourcebrief resource delete --resource-id <id>` |
| Restore archived/deleted resource | `sourcebrief resource restore --resource-id <id>` |
| Permanently purge deleted artifacts | `sourcebrief resource purge --resource-id <id>` |
| Inspect graph index | `sourcebrief resource graph --resource-id <id>` |

Examples:

```bash
sourcebrief resource list
sourcebrief resource get --resource-id "$RESOURCE_ID"

sourcebrief resource update \
  --resource-id "$RESOURCE_ID" \
  --name "Better resource name" \
  --stale-after-days 45

sourcebrief resource update-git \
  --resource-id "$RESOURCE_ID" \
  --branch main \
  --max-files 1000 \
  --max-file-bytes 200000

sourcebrief resource refresh --resource-id "$RESOURCE_ID" --wait
sourcebrief resource archive --resource-id "$RESOURCE_ID"
sourcebrief resource restore --resource-id "$RESOURCE_ID"
```

`purge` is intentionally separate from `delete`: delete is recoverable; purge removes deleted resource artifacts and should be treated as destructive cleanup.

## 5. Ask questions

Human-readable CLI answer:

```bash
sourcebrief ask --resource "SourceBrief repo" "where is resource refresh implemented?"
```

Raw runtime packet for automation/debugging:

```bash
sourcebrief --json agent-context \
  --resource "SourceBrief repo" \
  --runtime hermes \
  --query "where is resource refresh implemented?"
```

MCP-capable agents should start broad, then drill down:

1. `sourcebrief.ask` or `sourcebrief.lookup` for the first cited answer.
2. `sourcebrief.read_section`, `sourcebrief.read_file`, `sourcebrief.grep_code`, or `sourcebrief.find_symbol` for exact evidence.
3. Edit/test/commit in the real checkout, not inside SourceBrief.

## 6. Connect an agent runtime

Use the short guided path first:

```bash
sourcebrief runtime setup hermes \
  --workspace "SourceBrief CLI Demo" \
  --project "First useful moment" \
  --dry-run \
  --plan-out sourcebrief-hermes-plan.json

sourcebrief runtime validate --plan sourcebrief-hermes-plan.json --run
```

Only apply local runtime config after inspecting the plan:

```bash
sourcebrief runtime apply \
  --plan sourcebrief-hermes-plan.json \
  --target hermes \
  --receipt sourcebrief-hermes-receipt.json \
  --apply
```

For runtime-specific details, token scopes, generated skills, and failure modes, read [Agent runtime usage](AGENT_RUNTIME_USAGE.md). That guide is longer because it is the operator/runtime reference, not the first-use path.

## 7. Embeddings and rerank: what is actually tested

SourceBrief uses embeddings, vector search, graph/lexical signals, and rerank scores in the retrieval pipeline. The local default providers are intentionally deterministic development providers:

- embedding: `hashing/sourcebrief-hashing-v1`
- rerank: `term-overlap/sourcebrief-term-overlap-v1`

Those defaults are tested for correctness and safety, but they are not a production semantic-quality claim.

What is tested today:

- embedding generation is deterministic and normalized;
- embeddings are stored with provider/model/dimension/normalization namespace metadata;
- retrieval filters vectors by the active namespace so provider/model swaps do not silently mix stale vectors;
- rerank scores are normalized into `[0, 1]`;
- `/provider-health` reports provider status and marks default providers as `dev_quality=true`;
- QA smoke verifies indexing creates embeddings and that provider diagnostics appear in retrieval flows;
- real 50-question launch walkthroughs prove cited retrieval mechanics, not production-grade semantic model quality.

For production-like quality, configure a real provider (`http`, `openai-compatible`, `huggingface`, `vllm`, or `sglang`), set a deployment ID when the endpoint/model/backend changes, run `/provider-health`, reindex resources, and run an evaluation manifest before claiming semantic retrieval quality.

See [M14 provider verification](MILESTONE-14.md) for the technical details.

## 8. What SourceBrief is not

- Not an editor.
- Not a deployment system.
- Not a production mutation executor.
- Not proof that a remote indexed repo exists in the agent's local filesystem.
- Not a guarantee that dev hashing embeddings match production semantic retrieval.

Use SourceBrief to know where to look and what to trust. Use your coding agent and CI to edit, test, and ship.
