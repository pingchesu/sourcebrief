# QueueKeeper Gate A corpus — pre-D0 commitment

Tracking: [#351](https://github.com/pingchesu/sourcebrief/issues/351)
Parent Gate A experiment: [#346](https://github.com/pingchesu/sourcebrief/issues/346)

## Status

**PRE-D0 DRAFT — not approved and not authorized for candidate tuning or held-out execution.**

The public source repository is frozen at:

- Repository: <https://github.com/pingchesu/queuekeeper>
- Commit: `620c7bb435b7c7f20aba221e12890bc28ce52856`
- Canonical tree digest: `sha256:2ed5d9d6a4f0abf0de9465c144b7c6a72b92a0a35fa98b25fb7b1994a13d6ce6`
- License: MIT

## What this slice proves

- A separate, non-sensitive, dependency-light maintenance repository exists with real library, CLI, configuration, SQLite, transport, retry, redaction, receipt, metrics, packaging, CI, tests, and operator-documentation surfaces.
- The source baseline passes tests, lint, typing, package build, clean-wheel installation, and CLI startup.
- The draft corpus has exactly 4 development tasks, 12 held-out tasks, and 6 normative controls.
- Each draft maintenance task binds to an independent test artifact; all 16 are RED at the frozen baseline while the public baseline remains GREEN.
- Public metadata contains only source provenance, counts, content/test digests, baseline receipt digests, quality counts, and contamination metrics. It contains no task prompt, control prompt, hidden test, expected answer, patch, receipt body, or approval key.

## What this slice does not prove

- The draft held-out/control material is **not a final sealed corpus**. It received LLM-assisted quality review and therefore cannot become the protected D0 commitment unchanged.
- Named human ownership, independent Eval/QA authorship, protected approval, immutable pack sealing, arm execution, and Gate A outcome are not complete.
- A GREEN schema/preflight result is not a Gate A PASS.

## D0 blockers

1. Product, Eval/QA, provider/compiler, runtime-pack, Security, and incident responsibilities need named humans and explicit acceptance evidence. Provider/compiler and Eval/QA must remain separate.
2. Independent Eval/QA must re-author or replace final held-out tasks, controls, grader tests, and expected evidence on the isolated QA host; then publish new content commitments without exposing plaintext.
3. Security and Eval/QA must generate the authenticated D0 approval through a protected approval boundary. The shared HMAC key must not be copied into the source repo, this repository, compiler input, CI, or executor.
4. No compiler input may be released and no candidate tuning may begin until the final manifest, approval, contamination receipts, hidden-test bundle, and source/runtime provenance validate together.

## Public source verification

```bash
git clone https://github.com/pingchesu/queuekeeper.git
cd queuekeeper
git checkout 620c7bb435b7c7f20aba221e12890bc28ce52856
python3.11 -m venv .venv
.venv/bin/pip install -e '.[dev]'
make verify
make package-smoke
```

The public machine-readable commitment is [`task-digest-index.json`](task-digest-index.json). Its `d0_ready` value is intentionally `false`.
