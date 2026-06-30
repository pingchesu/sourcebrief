# SourceBrief proof gaps capture (#212)

Run date: 2026-06-30
Source stack: local isolated SourceBrief stack from current launch proof
Workspace: `50Q Launch Walkthrough 1782835809`
Project: `SourceBrief 50Q Product Walkthrough`
Resource: `SourceBrief repository launch import`

## Result

| Gap | Status | Committed redacted artifact | Raw local artifact | What it proves / blocks |
| --- | --- | --- | --- | --- |
| Resource Map rendered output | Closed | `resource-map.redacted.json` | `artifacts/proof-gaps-212-20260630/resource-map.raw.json` | Current indexed git resource compiled and approved a Resource Map artifact with 313 sources and 2203 citations. |
| Context Pack rendered output | Closed | `context-pack.redacted.json` | `artifacts/proof-gaps-212-20260630/context-pack.raw.json` | Approved Resource Map artifact published into Context Pack `launch-proof-212` v1. |
| Skill Export package example | Closed by #226 | `../skill-export-20260630/README.md` | `artifacts/skill-export-226-20260630/skill-export-approved.zip` | Follow-up #226 generated, approved, leak-scanned, and downloaded a public-safe package proof. |
| Runtime doctor terminal transcript | Closed | `runtime-doctor.redacted.txt` | `artifacts/proof-gaps-212-20260630/runtime-doctor.stdout.raw.txt` | CLI doctor resolved the named workspace/project and exited 0. |

## Skill Export blocker

The export reached `status=failed` because package validation passed but leak scan failed:

```json
[
  {
    "code": "forbidden_pattern",
    "message": "<token-like-pattern>",
    "path": "references/data-structure.md"
  },
  {
    "code": "forbidden_pattern",
    "message": "<local-path-pattern>",
    "path": "references/resource-map.md"
  }
]
```

This first failure is preserved as evidence. It was closed by #226 with source-evidence redaction hardening and an approved/downloadable package proof under `docs/evaluations/skill-export-20260630/`.

## Integrity

| File | SHA-256 |
| --- | --- |
| `context-pack.redacted.json` | `sha256:018e92b0ae35d1b14fb0475a25f417b66ea23e160d38f701d4737532fae67fa6` |
| `resource-map.redacted.json` | `sha256:4f90f1e62ee45371c1e73ab44e71b2b51301287a67a9182a99b0f7ab5f1b63d3` |
| `runtime-doctor.redacted.txt` | `sha256:6a9048da8f7bb3e62b5e61b86573c554b78cc5e9dec09bd91f7098642f4c44e3` |
| `skill-export.redacted.json` | `sha256:265c73bbde43b801cb1dc9a2980d3fcfd3d26f5ccf8dc9e4c4d6de551f5f2be4` |
| `summary.redacted.json` | `sha256:99192496aa80d8e5feb19e7b6daa7e623e89c9f5fb487468e9b6e83f9b8e03d6` |

Raw artifacts remain ignored under `artifacts/`; committed files are UUID/token/path redacted.
