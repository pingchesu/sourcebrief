# EvoEmbedding temporal-memory 50Q eval

This directory contains a structured SourceBrief eval manifest for deciding whether EvoEmbedding-style temporal retrieval is worth adopting.

- Manifest: `eval_manifest.json`
- Ordered fixture: `temporal_fixture.md`
- Schema: `sourcebrief.eval-manifest.v1`
- Question count: 50
- True unanswerable controls: 2
- False-premise cited rejection controls: 4
- Manifest digest: `sha256:840e2e0897b864f4786e9f336a77a76183a4d457fe86b4bd8c247bd25852e32c`
- Companion plan: [`../../docs/EVOEMBEDDING_EVALUATION_PLAN.md`](../../docs/EVOEMBEDDING_EVALUATION_PLAN.md)

The manifest intentionally uses normalized placeholder IDs. Before running it against `/retrieval-evals`, import the ordered fixture plus any desired SourceBrief docs/eval artifacts, then replace workspace/project/resource/snapshot placeholders with real IDs.

The temporal fixture is deliberately ordered and includes stable evidence markers such as `turn-003`, `decision-005`, and `improve-004`. Temporal questions should cite those markers; they are not meant to be graded as generic keyword lookup.

The current intended use is evaluation design and later profile-matrix execution, not evidence that EvoEmbedding has already been adopted.
