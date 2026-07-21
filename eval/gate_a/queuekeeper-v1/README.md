# QueueKeeper Gate A corpus — pre-D0 commitment

Tracking: [#351](https://github.com/pingchesu/sourcebrief/issues/351)
Parent Gate A experiment: [#346](https://github.com/pingchesu/sourcebrief/issues/346)

## Status

**PRE-D0 DRAFT — not approved and not authorized for candidate tuning or held-out execution.**

The public source repository is frozen at:

- Repository: <https://github.com/pingchesu/queuekeeper>
- Commit: `b366986fded2db350899ee56c7f4e0a416644317`
- Canonical tree digest: `sha256:af19cf1263cddc037c754c5e39cbc8374009baf89094ba8a307e715a2687b549`
- License: MIT

## What this slice proves

- A separate, non-sensitive, dependency-light maintenance repository exists with real library, CLI, configuration, SQLite, transport, retry, redaction, receipt, metrics, packaging, CI, tests, and operator-documentation surfaces.
- The source baseline passes tests, lint, typing, package build, clean-wheel installation, and CLI startup; the private GREEN receipt now retains and re-hashes the exact installed wheel bytes instead of trusting a digest for an overwritten `dist/` artifact.
- The draft corpus has exactly 4 development tasks, 12 held-out tasks, and 6 normative controls.
- Each draft maintenance task binds to an independent test artifact; all 16 are RED at the frozen baseline while the public baseline remains GREEN.
- Public metadata contains only source provenance, counts, content/test digests, baseline receipt self-digests, quality counts, and contamination metrics. A baseline receipt self-digest is SHA-256 over UTF-8 canonical JSON with its `receipt_sha256` field omitted; it is not the raw digest of the complete pretty-printed private receipt file. The public metadata contains no task prompt, control prompt, hidden test, expected answer, patch, receipt body, or approval key.

## What this slice does not prove

- Joe is the sole accountable human. The six role agents provide procedural challenge and context isolation only; they are not independent people, signers, owners, or custody authorities.
- A founder-controlled run may produce an explicitly labeled internal signal, but it cannot claim independent D0, Gate A PASS, or promotion authority.
- The draft held-out/control material is **not a final sealed corpus**. It received LLM-assisted quality review and therefore cannot become an independent protected D0 commitment unchanged.
- An independently operated verifier, protected signing/revocation boundary, real pack sealing/execution, and formal Gate A outcome are not complete. The local validator can recompute verifier-owned CAS bytes but cannot make the verifier independent.
- A GREEN schema/preflight result is not a Gate A PASS.

## D0 blockers

1. The current one-founder agent council must remain labeled `single_founder_internal` with `human_independence=false`; role aliases or workload agents must not satisfy independent-human ownership.
2. Independent Gate A requires newly authored protected material under separately accountable Eval/QA custody after candidate inputs freeze. The current LLM-reviewed draft remains internal-only.
3. Approval and verifier keys need a service-local, non-exportable boundary plus revocation/replay state. One founder-held HMAC is an integrity MAC, not multisigner consent or non-repudiation.
4. All four packs must freeze before protected material is released. A QA-side broker must release one task at a time into fresh sandboxes, and a separate verifier must retain/replay raw artifacts rather than trust report booleans or unattached hashes.
5. No independent compiler input or candidate tuning may begin until the final manifest, external authority, contamination/challenge receipts, hidden-test bundle, raw-receipt verifier contract, and source/runtime provenance validate together. A separate founder-controlled internal experiment may use only the development-only contract from #354 and remains non-promotional.

## Public source verification

```bash
git clone https://github.com/pingchesu/queuekeeper.git
cd queuekeeper
git checkout b366986fded2db350899ee56c7f4e0a416644317
python3.11 -m venv .venv
.venv/bin/pip install -e '.[dev]'
make verify
make package-smoke
```

The public machine-readable commitment is [`task-digest-index.json`](task-digest-index.json). Its `d0_ready` value is intentionally `false`.
