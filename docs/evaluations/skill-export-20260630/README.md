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
| Package hash | `sha256:3a56e72516b72056275733d9d7800e036e6a22d3b672f94fc6d47aa09b444aaa` |
| Download zip SHA-256 | `sha256:4ad5bdc9d94d491c1fc27785a706b9d882301b1e3d41dbd6c1def9bc33475d45` |

## Committed redacted artifacts

| Artifact | Purpose |
| --- | --- |
| `skill-export-approved.redacted.json` | Approved export metadata with IDs/paths redacted. |
| `package-tree.redacted.json` | Downloaded package file inventory and checksums. |
| `package__SKILL.md.redacted.txt` | Public-safe sample of the generated Hermes skill front door. |
| `package__references__data-structure.md.redacted.txt` | Regression sample for token-like pattern redaction in source-derived evidence. |
| `package__references__resource-map.md.redacted.txt` | Regression sample for local-path pattern redaction in source-derived evidence. |

Raw package zip and metadata remain ignored under `artifacts/skill-export-226-20260630/`.

## Integrity

| File | SHA-256 |
| --- | --- |
| `package-tree.redacted.json` | `sha256:8a2a8888543d66f38b6867adb01c0be024bc8c954e11c439678fd74029e386ee` |
| `package__README.md.redacted.txt` | `sha256:85921c8200de8e73042160f677c1f803acbeea45fb62b9f86420136fdb6f8026` |
| `package__SKILL.md.redacted.txt` | `sha256:c91c2c220cbdb5405a094c147ef5a077ae0e304a704e3817b923a66c895966d2` |
| `package__manifest.json.redacted.txt` | `sha256:cc3cf180477f29c8eaca5c76a63c30cfb8bd28cae39c1051e1677a685b65018d` |
| `package__references__data-structure.md.redacted.txt` | `sha256:9279f38ebac7f1fa33bde63bec2660bb67765f78d2341b8291393704d6171f26` |
| `package__references__resource-map.md.redacted.txt` | `sha256:36613aec327f13b1fee77f150e0cc1447abbe398ff6c7c85ec503b02e8e4875f` |
| `package__references__source-coverage.md.redacted.txt` | `sha256:745af9de79bbde29fdfd7fce024d061fbe09e2447b6c15024186cfdbdfc11ab9` |
| `skill-export-approved.redacted.json` | `sha256:33b5d3ff313fa2a1f9514d95059abc395560828f0c0972ec71179a39c52fb263` |
| `summary.redacted.json` | `sha256:d06f6b518800792d5f48f0ad6649d674e8cbda25bb6d3f5d8060a6f6404eacfa` |
