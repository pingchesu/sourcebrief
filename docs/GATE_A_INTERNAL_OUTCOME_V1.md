# Gate A Founder-Controlled Internal Outcome v1

This contract is the bounded execution path tracked by Issue #354. It does **not** reuse or impersonate the independent-human D0 authority model.

Every validated result must display:

> **FOUNDER-CONTROLLED INTERNAL SIGNAL — NOT INDEPENDENT GATE A, NOT D0, AND NOT PROMOTION AUTHORITY**

The validator always returns:

- `authorization=internal_signal_only`
- `d0_ready=false`
- `promotion_authorized=false`

## Frozen experiment

Before any compile or held-out execution, freeze and MAC-bind:

- internal-governance digest;
- source commit/tree and candidate SourceBrief commit;
- scorer and task-bundle digests;
- provider, model, prompt and sandbox-policy digests;
- network egress disabled;
- cost, latency, retry and stop budgets;
- uplift, AI-success and regression thresholds;
- exactly 4 development IDs, 12 held-out IDs and 6 control IDs;
- five lanes: `direct_tools_no_sourcebrief`, `current_deterministic`, `real_static`, `human_authored`, `ai_compiled`;
- four pack digests, with the direct-tools lane receiving `null`/no pack;
- three clean compiler receipts completed before the protected run.

## Exact coverage and scoring

The envelope requires exactly:

- 60 task receipts: five lanes × the same 12 held-out tasks;
- 30 control receipts: five lanes × the same six controls;
- a valid self-digest for every receipt;
- success equal to hidden-test exit code zero.

The validator recomputes all scores. The envelope contains no caller-supplied verdict or uplift.

`ai_compiled` passes the internal outcome only if all frozen requirements hold, including:

- AI held-out success floor;
- minimum task uplift over the strongest of direct-tools/current-deterministic/real-static;
- co-best baseline regression limit;
- all controls pass;
- total cost and elapsed latency stay within frozen budgets.

A FAIL sets `stop_investment=true`. It does not authorize broad rebuild work.

## CLI

```bash
python scripts/eval_manifest.py validate-gate-a-internal-outcome \
  /path/to/internal-outcome.private.json \
  --key-file /path/to/internal-outcome.key
```

The outcome, HMAC key, protected tasks, prompts, responses, diffs and hidden tests remain private evidence and must not be committed.

## Operational ownership

Joe is the sole accountable human. Compiler, runtime and verifier agents are isolated workloads, not independent human approvers. Local HMAC proves only integrity under one control domain; it does not prove independent custody or non-repudiation.
