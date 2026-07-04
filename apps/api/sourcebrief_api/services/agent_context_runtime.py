from __future__ import annotations

import re
from collections import Counter
from typing import Any
from uuid import UUID

from sourcebrief_api.retrieval import RetrievalCandidate
from sourcebrief_api.schemas import AgentContextAnswer, AgentContextCitation, ResourceRead


def agent_context_suggested_tool_calls(
    citations: list[AgentContextCitation], query: str, *, include_code_tools: bool = True
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = [
        {
            "name": "sourcebrief.search",
            "reason": "Find additional cited sections if the initial context is insufficient.",
            "arguments": {"query": query, "top_k": 8},
        },
        {
            "name": "sourcebrief.list_sources",
            "reason": "Discover human source names/resource IDs before narrowing follow-up calls.",
            "arguments": {"limit": 20},
        },
    ]
    if citations:
        first = citations[0]
        if first.path and first.content_hash:
            calls.insert(
                0,
                {
                    "name": "sourcebrief.read_section",
                    "reason": "Read the first cited section exactly from the cited snapshot before making source claims.",
                    "arguments": {
                        "resource_id": str(first.resource_id),
                        "source_snapshot_id": str(first.snapshot_id),
                        "path": first.path,
                        "content_hash": first.content_hash,
                    },
                },
            )
        if include_code_tools:
            calls.append(
                {
                    "name": "sourcebrief.read_file",
                    "reason": "Inspect the cited file from the indexed source snapshot when code detail is needed.",
                    "arguments": {
                        "resource_id": str(first.resource_id),
                        "path": first.path or "<path>",
                        "start_line": 1,
                        "end_line": 120,
                    },
                }
            )
    return calls


def agent_answer_snippets(context_parts: list[str], *, limit: int = 3) -> list[tuple[int, str]]:
    snippets: list[tuple[int, str]] = []
    for citation_index, part in enumerate(context_parts, start=1):
        lines = []
        for raw_line in part.splitlines()[1:]:
            line = raw_line.strip().strip("` ")
            if not line or line.startswith(("|", "---")):
                continue
            if line.startswith("#"):
                line = line.lstrip("# ").strip()
                if not line:
                    continue
            if re.match(r"^[{}();,]+$", line):
                continue
            lines.append(line)
        text = " ".join(lines)
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            continue
        sentence = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0].strip()
        if len(sentence) < 24:
            sentence = text[:240].strip()
        if len(sentence) > 280:
            sentence = sentence[:277].rstrip() + "..."
        if sentence:
            snippets.append((citation_index, sentence))
        if len(snippets) >= limit:
            break
    return snippets


def agent_answer_caveats(
    resource_coverage: list[dict[str, Any]], coverage_warnings: list[str]
) -> list[str]:
    caveats: list[str] = []
    for warning in coverage_warnings:
        if warning and warning not in caveats:
            caveats.append(warning)
    for entry in resource_coverage:
        status = entry.get("coverage_status")
        if status and status != "full":
            name = entry.get("name") or entry.get("resource_id")
            caveat = f"{name}: coverage_status={status}; evidence may be partial."
            if caveat not in caveats:
                caveats.append(caveat)
    return caveats[:5]


NEGATED_EVIDENCE_MARKERS = (
    "not documented",
    "not provide",
    "not include",
    "not guarantee",
    "does not document",
    "does not provide",
    "does not include",
    "no audit report",
    "no auditor",
    "no sla",
    "no uptime",
    "no fedramp",
    "no threat model",
    "without evidence",
    "without a cited",
    "not supported",
)

UNSUPPORTED_CLAIM_FAMILIES: tuple[
    tuple[str, tuple[str, ...], tuple[tuple[str, ...], ...]], ...
] = (
    (
        "SOC 2 audit report/auditor",
        ("soc 2", "soc2", "type ii", "auditor", "audit report"),
        (
            ("soc 2 type ii", "soc 2 audit report", "soc 2 report", "signed soc 2"),
            ("auditor is", "auditor:", "auditor named", "auditor was", "audited by"),
        ),
    ),
    (
        "HIPAA compliance/deployment checklist",
        ("hipaa", "covered entity", "covered-entity", "compliance", "deployment checklist"),
        (
            ("hipaa compliance", "hipaa compliant"),
            ("covered-entity deployment checklist", "covered entity deployment checklist"),
        ),
    ),
    (
        "hosted cloud service SLA/uptime dashboard",
        ("hosted", "cloud service", "sla", "uptime", "dashboard"),
        (("hosted cloud service",), ("sla", "service level agreement"), ("uptime dashboard",)),
    ),
    (
        "FedRAMP authorization/sponsoring agency",
        ("fedramp", "authorization", "sponsoring agency", "agency"),
        (("fedramp authorization", "fedramp authorized"), ("sponsoring agency", "agency sponsor")),
    ),
    (
        "production Kubernetes multi-tenant isolation/threat model",
        ("kubernetes", "k8s", "multi-tenant", "multitenant", "tenant isolation", "threat model"),
        (
            ("production kubernetes", "production k8s"),
            ("multi-tenant isolation", "multitenant isolation", "tenant isolation"),
            ("threat model",),
        ),
    ),
)


def agent_unsupported_claim_terms(query: str, context_parts: list[str]) -> list[str]:
    query_text = query.lower()
    context_text = "\n".join(context_parts).lower()
    unsupported: list[str] = []
    for label, query_terms, required_groups in UNSUPPORTED_CLAIM_FAMILIES:
        if not any(term in query_text for term in query_terms):
            continue
        negated = any(marker in context_text for marker in NEGATED_EVIDENCE_MARKERS)
        supported = not negated and all(
            any(term in context_text for term in group) for group in required_groups
        )
        if not supported:
            unsupported.append(label)
    return unsupported


def agent_answer_citations_used(
    citations: list[AgentContextCitation],
    *,
    count: int | None = None,
    citation_indices: list[int] | None = None,
) -> list[dict[str, Any]]:
    if citation_indices:
        indices = [idx for idx in dict.fromkeys(citation_indices) if 1 <= idx <= len(citations)]
    else:
        indices = list(range(1, min(len(citations), max(1, count or 0)) + 1))
    return [
        {
            "label": f"[{idx}]",
            "resource_id": str(citation.resource_id),
            "snapshot_id": str(citation.snapshot_id),
            "path": citation.path or citation.title or str(citation.resource_id),
            "content_hash": citation.content_hash,
            "score": citation.score,
        }
        for idx in indices
        for citation in [citations[idx - 1]]
    ]


def synthesize_agent_answer(
    *,
    query: str,
    context_parts: list[str],
    citations: list[AgentContextCitation],
    resource_coverage: list[dict[str, Any]],
    coverage_warnings: list[str],
) -> AgentContextAnswer:
    caveats = agent_answer_caveats(resource_coverage, coverage_warnings)
    unsupported_terms = agent_unsupported_claim_terms(query, context_parts)
    if unsupported_terms:
        reason = "Retrieved SourceBrief evidence does not directly support the requested high-assurance claim."
        text = (
            "Insufficient evidence: the cited SourceBrief context does not support the requested claim "
            f"about {', '.join(unsupported_terms)}. Do not answer this as true unless a cited source explicitly provides that evidence."
        )
        if caveats:
            text += " Caveat: " + " ".join(caveats[:2])
        return AgentContextAnswer(
            outcome="unsupported_by_sources",
            text=text,
            citations_used=agent_answer_citations_used(citations, count=min(len(citations), 3)),
            caveats=caveats,
            confidence="none",
            abstention_reason=reason,
            unsupported_claim_terms=unsupported_terms,
        )
    if not citations:
        text = f"No grounded answer is available from the selected SourceBrief evidence for: {query}"
        if caveats:
            text += " Caveat: " + " ".join(caveats[:2])
        return AgentContextAnswer(
            outcome="insufficient_evidence",
            text=text,
            citations_used=[],
            caveats=caveats,
            confidence="none",
            abstention_reason="No cited SourceBrief evidence was retrieved for this question.",
        )
    snippets = agent_answer_snippets(context_parts)
    if snippets:
        claims = [f"{snippet} [{idx}]" for idx, snippet in snippets]
        text = f"Based on the cited SourceBrief context for `{query}`: " + " ".join(claims)
    else:
        text = "SourceBrief found cited context for this question; inspect the cited sections before making claims."
    if caveats:
        text += " Caveat: " + " ".join(caveats[:2])
    citations_used = agent_answer_citations_used(
        citations,
        count=3,
        citation_indices=[idx for idx, _snippet in snippets] if snippets else None,
    )
    return AgentContextAnswer(
        text=text,
        citations_used=citations_used,
        caveats=caveats,
        confidence="low" if caveats else "medium",
    )


def runtime_safe_index_failure(error_message: str | None) -> str:
    if not error_message:
        return "latest index failed; inspect Index activity with read scope for details"
    lowered = error_message.lower()
    if "chunk budget exceeded" in lowered:
        parts = ["latest index failed: chunk budget exceeded"]
        for key in ("max_chunks", "documents_collected", "chunks_created"):
            match = re.search(rf"{key}=([0-9]+)", error_message)
            if match:
                parts.append(f"{key}={match.group(1)}")
        parts.append(
            "suggested retry: narrow include/exclude filters, use a source subpath, or intentionally raise max_chunks"
        )
        return "; ".join(parts)
    if "symbol budget exceeded" in lowered:
        parts = ["latest index failed: symbol budget exceeded"]
        for key in ("max_symbols", "documents_collected", "symbols_created"):
            match = re.search(rf"{key}=([0-9]+)", error_message)
            if match:
                parts.append(f"{key}={match.group(1)}")
        parts.append(
            "suggested retry: use docs-only/source-subpath import, include/exclude filters, or intentionally raise max_symbols"
        )
        return "; ".join(parts)
    return "latest index failed; inspect Index activity with read scope for details"


def coverage_budget_reason(read: ResourceRead) -> str | None:
    diagnostics = read.index_diagnostics or {}
    configured_budgets = diagnostics.get("configured_budgets") or {}
    limited_keys = diagnostics.get("limited_budget_keys") or [
        key for key in configured_budgets if configured_budgets.get(key) is not None
    ]
    if read.coverage_status != "partial":
        return None
    if limited_keys:
        details = ", ".join(
            f"{key}={configured_budgets.get(key)}"
            for key in limited_keys
            if configured_budgets.get(key) is not None
        )
        return f"limited import budget ({details})" if details else "limited import budget"
    if diagnostics.get("file_budget_stats"):
        return "current snapshot was truncated by file/byte import budgets"
    return "partial corpus; evidence may be incomplete"


def agent_context_retrieval_metadata(
    candidates: list[RetrievalCandidate], requested_resource_ids: list[UUID] | None = None
) -> dict[str, Any]:
    paths = [candidate.path for candidate in candidates if candidate.path]
    unique_paths = {path for path in paths}
    diversity = (
        candidates[0].ranking_diagnostics.get("retrieval_diversity")
        if candidates and candidates[0].ranking_diagnostics
        else None
    )
    path_prior_hits: dict[str, int] = {}
    cited_resource_counts = Counter(str(candidate.resource_id) for candidate in candidates)
    for candidate in candidates:
        diagnostics = candidate.ranking_diagnostics or {}
        for reason in diagnostics.get("path_prior_reasons", []) or []:
            path_prior_hits[reason] = path_prior_hits.get(reason, 0) + 1
    requested_ids = [str(rid) for rid in requested_resource_ids or []]
    missing_requested_ids = [rid for rid in requested_ids if cited_resource_counts.get(rid, 0) == 0]
    metadata = {
        "selected_count": len(candidates),
        "unique_citation_paths": len(unique_paths),
        "duplicate_citation_count": max(0, len(paths) - len(unique_paths)),
        "path_prior_hits": path_prior_hits,
        "requested_resource_ids": requested_ids,
        "cited_resource_counts": dict(sorted(cited_resource_counts.items())),
        "missing_requested_resource_ids": missing_requested_ids,
    }
    if isinstance(diversity, dict):
        metadata["candidate_pool_count"] = diversity.get("candidate_pool_count", len(candidates))
        metadata["deduped_from_count"] = diversity.get("deduped_from_count", 0)
        metadata["retriever_selected_count"] = diversity.get("selected_count")
        metadata["retriever_unique_citation_paths"] = diversity.get("unique_citation_paths")
        metadata["retriever_duplicate_citation_count"] = diversity.get("duplicate_citation_count")
        metadata["candidate_resource_counts"] = diversity.get("candidate_resource_counts", {})
        metadata["retriever_selected_resource_counts"] = diversity.get(
            "selected_resource_counts", {}
        )
    else:
        metadata["candidate_pool_count"] = len(candidates)
        metadata["deduped_from_count"] = 0
        metadata["candidate_resource_counts"] = dict(sorted(cited_resource_counts.items()))
        metadata["retriever_selected_resource_counts"] = dict(sorted(cited_resource_counts.items()))
    return metadata
