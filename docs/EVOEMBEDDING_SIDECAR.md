# EvoEmbedding sidecar prototype

This prototype is the #199 bridge between SourceBrief's existing HTTP rerank provider contract and the MiG-NJU EvoEmbedding client.

## Purpose

- Provide a SourceBrief-compatible `/rerank` endpoint: `{query, documents, top_k}` -> `{scores, results}`.
- Keep SourceBrief's HTTP rerank integration batch-safe: SourceBrief sends all candidate documents in one request, because EvoEmbedding returns relative ranking rather than meaningful one-document scalar scores.
- Keep Torch / transformer dependencies outside the SourceBrief API and worker process.
- Make contract tests possible without downloading a model.
- Avoid claiming adoption evidence until the real `evoembedding` backend is used and recorded in eval artifacts.

## Backends

### deterministic

Default backend for contract tests only. It uses deterministic token overlap plus a tiny stable tie-breaker and reports `dev_quality: true` from `/healthz`.

```bash
python scripts/evoembedding_sidecar.py --host 127.0.0.1 --port 18180
curl -fsS http://127.0.0.1:18180/healthz
curl -fsS http://127.0.0.1:18180/rerank   -H 'Content-Type: application/json'   -d '{"query":"where did I travel in spring","documents":["I bought a laptop","I visited Paris in April"],"top_k":1}'
```

### evoembedding

Real model backend. Clone/install the upstream repo in a separate environment first; do not add those heavy dependencies to SourceBrief core. The sidecar passes `EVOEMBEDDING_MODEL` to upstream `EvoEmbeddingClient(model_path=...)`; incompatible upstream import/constructor paths make `/healthz` return HTTP 503 with `status=failed` instead of silently falling back.

Record the upstream repo commit and configured model/tokenizer with every #200 evidence run; this sidecar does not apply or claim model/repo revision pinning by itself.

```bash
git clone https://github.com/MiG-NJU/EvoEmbedding /opt/EvoEmbedding
cd /opt/EvoEmbedding
pip install -r requirements-evoembedding-lite.txt

EVOEMBEDDING_BACKEND=evoembedding \
EVOEMBEDDING_REPO_PATH=/opt/EvoEmbedding \
EVOEMBEDDING_MODEL=MiG-NJU/EvoEmbedding-0.8B \
EVOEMBEDDING_TOKENIZER_NAME=Qwen/Qwen3-0.6B-Instruct-2507 \
EVOEMBEDDING_DEVICE=cuda \
python /path/to/sourcebrief/scripts/evoembedding_sidecar.py --host 127.0.0.1 --port 18180
```

Point SourceBrief at the sidecar:

```bash
SOURCEBRIEF_RERANK_PROVIDER=http
SOURCEBRIEF_RERANK_ENDPOINT=http://127.0.0.1:18180/rerank
SOURCEBRIEF_RERANK_MODEL=MiG-NJU/EvoEmbedding-0.8B
```

Before using the sidecar for eval evidence, verify SourceBrief sees the real backend rather than the deterministic contract backend:

```bash
curl -fsS http://127.0.0.1:18180/healthz
curl -fsS http://127.0.0.1:18000/provider-health
```

The eval-ready path requires `backend=evoembedding`, `status=ok`, and `dev_quality=false` in the sidecar response and SourceBrief provider-health rerank section. If provider-health reports `backend=deterministic` or `dev_quality=true`, the run is contract-test evidence only and must not be used for the adoption decision.

## #200 A/B evidence boundary

This sidecar does **not** make `scripts/run_profile_matrix_eval.py` switch provider backends per profile. Until executable provider profiles exist, #200 adoption evidence must use a one-provider-per-run procedure:

1. Start SourceBrief with exactly one rerank provider configuration.
2. Capture `/provider-health` for that configuration before grading.
3. Run the same manifest/profile set and artifact bundle for that provider.
4. Repeat from a fresh provider configuration for the comparison provider.
5. Compare bundles only after confirming each bundle's provider-health metadata is eval-ready.

Do not label two profiles in the same runner invocation as different providers unless SourceBrief runtime actually switches provider config for those profiles.

Go/no-go checks for a real Evo evidence bundle:

- sidecar `/healthz` is HTTP 200 with `status=ok`, `backend=evoembedding`, `dev_quality=false`;
- SourceBrief `/provider-health` rerank section has `status=ok`, `backend=evoembedding`, `reported_model` matching `SOURCEBRIEF_RERANK_MODEL`, and `dev_quality=false`;
- upstream EvoEmbedding repo commit, configured model, tokenizer, and device are recorded in the evidence bundle notes;
- any failed provider-health, deterministic backend, missing backend metadata, or null replayability notes makes the bundle diagnostic-only, not adoption evidence.

## Non-goals

- No vector schema migration.
- No SourceBrief default-profile change.
- No bundled model weights or Torch dependencies in SourceBrief core images.
- No adoption claim from the deterministic backend.
