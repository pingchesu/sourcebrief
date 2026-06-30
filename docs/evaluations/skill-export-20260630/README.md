# SourceBrief Skill Export approved package proof (#226)

Run date: 2026-06-30
Source stack: local isolated SourceBrief stack from the current launch proof, rebuilt from branch `fix/skill-export-leak-scan-226`.
Context Pack: `launch-proof-212` v1

## Result

| Check | Result |
| --- | --- |
| Export status | `approved` |
| Validation | `True` |
| Leak scan | `True` |
| File count | `18` |
| Package hash | `sha256:246268011845158039132422d32be9bc785f314b59c464dd11661bdf0361d9d9` |
| Download zip SHA-256 | `sha256:4ad5bdc9d94d491c1fc27785a706b9d882301b1e3d41dbd6c1def9bc33475d45` |

## Committed redacted artifacts

| Artifact | Purpose |
| --- | --- |
| `skill-export-approved.redacted.json` | Approved export metadata with IDs/paths redacted. |
| `package-tree.redacted.json` | Public redacted package file inventory/checksums after approval-status wording normalization. |
| `package__SKILL.md.redacted.txt` | Public-safe sample of the generated Hermes skill front door. |
| `package__references__data-structure.md.redacted.txt` | Regression sample for token-like pattern redaction in source-derived evidence. |
| `package__references__resource-map.md.redacted.txt` | Regression sample for local-path pattern redaction in source-derived evidence. |

Raw package zip and metadata remain ignored under `artifacts/skill-export-226-20260630/`.

## Approval-status wording

The committed redacted public projection uses the current generator wording: package generation starts as `draft`, while SourceBrief approval is authoritative in `manifest.json` (`export_status`) and the API/export metadata. External install/copy is allowed only when that approval state is `approved`. The ignored raw zip/hash remains a historical local artifact; public redacted metadata and samples are normalized to avoid reading an approved package as draft-only.

## Integrity

| File | SHA-256 |
| --- | --- |
| `package-tree.redacted.json` | `sha256:a7f6b4cc21c0adfb9d9eb1b36ecf1b4f2e52200e461fd58841eb669631c2f208` |
| `package__README.md.redacted.txt` | `sha256:d6b2649d7676b37adda3818a279e05d81c95423eb2b3cb959a226830d54421a0` |
| `package__SKILL.md.redacted.txt` | `sha256:c91c2c220cbdb5405a094c147ef5a077ae0e304a704e3817b923a66c895966d2` |
| `package__manifest.json.redacted.txt` | `sha256:b58d3cbfe9ecf124cd6cdca12fd8260798cbcb0bd988e2239cee072e7c4fdd09` |
| `package__references__data-structure.md.redacted.txt` | `sha256:9279f38ebac7f1fa33bde63bec2660bb67765f78d2341b8291393704d6171f26` |
| `package__references__resource-map.md.redacted.txt` | `sha256:36613aec327f13b1fee77f150e0cc1447abbe398ff6c7c85ec503b02e8e4875f` |
| `package__references__source-coverage.md.redacted.txt` | `sha256:745af9de79bbde29fdfd7fce024d061fbe09e2447b6c15024186cfdbdfc11ab9` |
| `skill-export-approved.redacted.json` | `sha256:fca77a48ba80291925156dbb5e6b80b37f193069174c5173df7bb55ec19713e2` |
| `summary.redacted.json` | `sha256:e8707f438455d67d197fce38d5ca9ff2e418430ec0c7429d18d6f046ab65802a` |
