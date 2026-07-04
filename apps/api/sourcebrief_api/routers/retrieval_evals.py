from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from typing import Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from sourcebrief_api.auth import Principal, require_principal, require_scope
from sourcebrief_api.retrieval import (
    DEFAULT_RETRIEVAL_PROFILE,
    RETRIEVAL_PROFILES,
    embedding_namespace_diagnostics,
    normalize_retrieval_profile,
    retrieval_profile_manifest,
)
from sourcebrief_api.schemas import (
    AgentContextRequest,
    AgentContextResponse,
    RetrievalEvalRequest,
    RetrievalEvalResponse,
    RetrievalEvalResult,
    RetrievalEvalRunListResponse,
    RetrievalEvalRunRead,
    RetrievalEvalRunSummaryRead,
    RetrievalEvalSummary,
    RetrievalProfileRead,
    RetrievalProfilesResponse,
)
from sourcebrief_shared.db import get_session
from sourcebrief_shared.embeddings import current_embedding_config
from sourcebrief_shared.models import Resource, RetrievalEvalItem, RetrievalEvalRun

ProjectAccessAuthorizer = Callable[[Session, UUID, UUID, Principal], object]
ResourceResolver = Callable[..., Resource]
EffectiveResourceIdsResolver = Callable[[Principal, list[UUID] | None], list[UUID] | None]
AgentContextBuilder = Callable[..., AgentContextResponse]


@dataclass(frozen=True)
class RetrievalEvalRouterDeps:
    require_project_access: ProjectAccessAuthorizer
    resolve_resource: ResourceResolver
    effective_resource_ids: EffectiveResourceIdsResolver
    build_agent_context_response: AgentContextBuilder


def _eval_run_visible_to_principal(principal: Principal, run: RetrievalEvalRun) -> bool:
    token = principal.api_token
    if token is None or token.allowed_resource_ids is None:
        return True
    if run.project_wide:
        return False
    return set(run.resource_ids or []).issubset(set(token.allowed_resource_ids))


def _retrieval_eval_run_summary_read(run: RetrievalEvalRun) -> RetrievalEvalRunSummaryRead:
    summary = run.summary or {}
    return RetrievalEvalRunSummaryRead(
        id=run.id,
        profile=run.profile,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        created_at=run.created_at,
        runtime=run.runtime,
        provider=run.provider,
        model=run.model,
        status=run.status,
        question_count=run.question_count,
        passed_count=run.passed_count,
        failed_count=run.failed_count,
        pass_rate=run.pass_rate,
        max_latency_ms=run.max_latency_ms,
        avg_latency_ms=run.avg_latency_ms,
        project_wide=run.project_wide,
        resource_ids=run.resource_ids or [],
        failure_reasons=list(summary.get("failure_reasons") or []),
    )


def _retrieval_eval_run_read(session: Session, run: RetrievalEvalRun) -> RetrievalEvalRunRead:
    items = list(
        session.scalars(
            select(RetrievalEvalItem)
            .where(
                RetrievalEvalItem.workspace_id == run.workspace_id,
                RetrievalEvalItem.project_id == run.project_id,
                RetrievalEvalItem.eval_run_id == run.id,
            )
            .order_by(RetrievalEvalItem.ordinal.asc())
        )
    )
    return RetrievalEvalRunRead(
        run_id=run.id,
        profile=run.profile,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        created_at=run.created_at,
        runtime=run.runtime,
        provider=run.provider,
        model=run.model,
        diagnostics=run.diagnostics or {},
        summary=RetrievalEvalSummary(**(run.summary or {})),
        results=[
            RetrievalEvalResult(
                id=item.question_id,
                query=item.query,
                passed=item.passed,
                failure_reasons=item.failure_reasons or [],
                latency_ms=item.latency_ms,
                citation_count=item.citation_count,
                context_chars=item.context_chars,
                symbol_count=item.symbol_count,
                expected_resource_ids=item.expected_resource_ids or [],
                cited_resource_ids=item.cited_resource_ids or [],
                forbidden_resource_ids=item.forbidden_resource_ids or [],
                hit_quality=item.hit_quality or [],
            )
            for item in items
        ],
    )


def _persist_retrieval_eval_run(
    session: Session,
    *,
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal,
    payload: RetrievalEvalRequest,
    response: RetrievalEvalResponse,
    project_wide: bool,
    resource_ids: set[UUID],
) -> RetrievalEvalResponse:
    run = RetrievalEvalRun(
        workspace_id=workspace_id,
        project_id=project_id,
        actor_user_id=principal.user.id,
        actor_token_id=principal.token_id,
        runtime=payload.runtime,
        profile=response.profile,
        provider=response.provider,
        model=response.model,
        status=response.summary.status,
        question_count=response.summary.question_count,
        passed_count=response.summary.passed_count,
        failed_count=response.summary.failed_count,
        pass_rate=response.summary.pass_rate,
        max_latency_ms=response.summary.max_latency_ms,
        avg_latency_ms=response.summary.avg_latency_ms,
        max_chars=payload.max_chars,
        project_wide=project_wide,
        resource_ids=sorted(resource_ids),
        summary=response.summary.model_dump(mode="json"),
        diagnostics=response.diagnostics,
    )
    session.add(run)
    session.flush()
    for ordinal, result in enumerate(response.results):
        session.add(
            RetrievalEvalItem(
                workspace_id=workspace_id,
                project_id=project_id,
                eval_run_id=run.id,
                ordinal=ordinal,
                question_id=result.id,
                query=result.query,
                passed=result.passed,
                latency_ms=result.latency_ms,
                citation_count=result.citation_count,
                context_chars=result.context_chars,
                symbol_count=result.symbol_count,
                expected_resource_ids=result.expected_resource_ids,
                cited_resource_ids=result.cited_resource_ids,
                forbidden_resource_ids=result.forbidden_resource_ids,
                failure_reasons=result.failure_reasons,
                hit_quality=result.hit_quality,
            )
        )
    session.commit()
    return response.model_copy(update={"run_id": run.id})


def create_router(deps: RetrievalEvalRouterDeps) -> APIRouter:
    router = APIRouter()

    @router.get(
            "/workspaces/{workspace_id}/projects/{project_id}/retrieval-evals",
            response_model=RetrievalEvalRunListResponse,
        )
    def list_retrieval_eval_runs(
        workspace_id: UUID,
        project_id: UUID,
        limit: int = Query(default=20, ge=1, le=100),
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> RetrievalEvalRunListResponse:
        require_scope(principal, "project:query")
        deps.require_project_access(session, workspace_id, project_id, principal)
        stmt = select(RetrievalEvalRun).where(
            RetrievalEvalRun.workspace_id == workspace_id,
            RetrievalEvalRun.project_id == project_id,
        )
        token = principal.api_token
        if token is not None and token.allowed_resource_ids is not None:
            resource_ids_column = cast(Any, RetrievalEvalRun.resource_ids)
            stmt = stmt.where(
                RetrievalEvalRun.project_wide.is_(False),
                resource_ids_column.contained_by(token.allowed_resource_ids),
            )
        rows = list(session.scalars(stmt.order_by(RetrievalEvalRun.created_at.desc()).limit(limit)))
        return RetrievalEvalRunListResponse(count=len(rows), runs=[_retrieval_eval_run_summary_read(run) for run in rows])


    @router.get(
            "/workspaces/{workspace_id}/projects/{project_id}/retrieval-evals/{run_id}",
            response_model=RetrievalEvalRunRead,
        )
    def get_retrieval_eval_run(
        workspace_id: UUID,
        project_id: UUID,
        run_id: UUID,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> RetrievalEvalRunRead:
        require_scope(principal, "project:query")
        deps.require_project_access(session, workspace_id, project_id, principal)
        run = session.scalar(
            select(RetrievalEvalRun).where(
                RetrievalEvalRun.id == run_id,
                RetrievalEvalRun.workspace_id == workspace_id,
                RetrievalEvalRun.project_id == project_id,
            )
        )
        if run is None or not _eval_run_visible_to_principal(principal, run):
            raise HTTPException(status_code=404, detail="eval run not found")
        return _retrieval_eval_run_read(session, run)


    @router.get(
            "/workspaces/{workspace_id}/projects/{project_id}/retrieval-profiles",
            response_model=RetrievalProfilesResponse,
        )
    def list_retrieval_profiles(
        workspace_id: UUID,
        project_id: UUID,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> RetrievalProfilesResponse:
        require_scope(principal, "project:read")
        deps.require_project_access(session, workspace_id, project_id, principal)
        profiles = [
            RetrievalProfileRead(
                name=name,
                description=profile.description,
                weights={
                    "lexical": profile.lexical_weight,
                    "vector": profile.vector_weight,
                    "graph": profile.graph_weight,
                    "rerank": profile.rerank_weight,
                },
                candidate_pool={
                    "multiplier": profile.candidate_multiplier,
                    "min": profile.candidate_pool_min,
                    "max": profile.candidate_pool_max,
                },
                second_stage_rerank=profile.second_stage_rerank,
                promote_sequence_siblings=profile.promote_sequence_siblings,
            )
            for name, profile in RETRIEVAL_PROFILES.items()
        ]
        return RetrievalProfilesResponse(default=DEFAULT_RETRIEVAL_PROFILE, profiles=profiles)


    @router.post(
            "/workspaces/{workspace_id}/projects/{project_id}/retrieval-evals",
            response_model=RetrievalEvalResponse,
        )
    def run_retrieval_eval(
        workspace_id: UUID,
        project_id: UUID,
        payload: RetrievalEvalRequest,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> RetrievalEvalResponse:
        require_scope(principal, "project:query")
        deps.require_project_access(session, workspace_id, project_id, principal)
        effective_resource_ids_by_question: list[list[UUID] | None] = []
        referenced_ids: set[UUID] = set()
        for question in payload.questions:
            effective_resource_ids = deps.effective_resource_ids(principal, question.resource_ids)
            effective_resource_ids_by_question.append(effective_resource_ids)
            referenced_ids.update(question.expected_resource_ids)
            referenced_ids.update(question.forbidden_resource_ids)
            referenced_ids.update(effective_resource_ids or [])
        for rid in referenced_ids:
            deps.resolve_resource(session, workspace_id, project_id, rid, principal)
        embedding_config = current_embedding_config()
        diagnostics_resource_ids: list[UUID] | None
        if any(resource_ids is None for resource_ids in effective_resource_ids_by_question):
            diagnostics_resource_ids = None
        else:
            diagnostics_resource_ids = sorted({rid for resource_ids in effective_resource_ids_by_question for rid in (resource_ids or [])})
        diagnostics = embedding_namespace_diagnostics(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            resource_ids=diagnostics_resource_ids,
        )
        results: list[RetrievalEvalResult] = []
        all_failure_reasons: list[str] = []
        question_resource_coverage: list[dict[str, Any]] = []
        for question, effective_resource_ids in zip(payload.questions, effective_resource_ids_by_question, strict=True):
            started = perf_counter()
            response = deps.build_agent_context_response(
                session,
                workspace_id=workspace_id,
                project_id=project_id,
                payload=AgentContextRequest(
                    query=question.query,
                    profile=payload.profile,
                    top_k=question.top_k,
                    resource_ids=effective_resource_ids,
                    runtime=payload.runtime,
                    include_code_symbols=question.include_code_symbols,
                    max_chars=payload.max_chars,
                ),
                principal=principal,
            )
            latency_ms = round((perf_counter() - started) * 1000, 2)
            cited_resource_ids = {citation.resource_id for citation in response.citations}
            cited_paths = {citation.path for citation in response.citations if citation.path}
            cited_symbol_names = {symbol.name for symbol in response.symbols}
            requested_for_question = effective_resource_ids or []
            resource_count_by_id = Counter(str(citation.resource_id) for citation in response.citations)
            missing_requested_for_question = [str(rid) for rid in requested_for_question if resource_count_by_id.get(str(rid), 0) == 0]
            question_resource_coverage.append(
                {
                    "question_id": question.id,
                    "requested_resource_ids": [str(rid) for rid in requested_for_question],
                    "cited_resource_counts": dict(sorted(resource_count_by_id.items())),
                    "missing_requested_resource_ids": missing_requested_for_question,
                    "coverage_warnings": response.coverage_warnings,
                }
            )
            failures: list[str] = []
            if len(response.citations) < question.min_citations:
                failures.append("missing_citations")
            missing_expected = sorted(rid for rid in question.expected_resource_ids if rid not in cited_resource_ids)
            if missing_expected:
                failures.append("missing_expected_resources:" + ",".join(str(rid) for rid in missing_expected))
            forbidden_hits = sorted(rid for rid in question.forbidden_resource_ids if rid in cited_resource_ids)
            if forbidden_hits:
                failures.append("forbidden_resources_cited:" + ",".join(str(rid) for rid in forbidden_hits))
            missing_paths = [path for path in question.expected_paths if path not in cited_paths]
            if missing_paths:
                failures.append("missing_expected_paths:" + ",".join(path[:128] for path in missing_paths))
            missing_symbols = [symbol for symbol in question.expected_symbols if symbol not in cited_symbol_names]
            if missing_symbols:
                failures.append("missing_expected_symbols:" + ",".join(symbol[:128] for symbol in missing_symbols))
            lower_context = response.context.lower()
            for required in question.required_texts:
                if required.lower() not in lower_context:
                    failures.append(f"missing_required_text:{required[:128]}")
            all_failure_reasons.extend(failures)
            results.append(
                RetrievalEvalResult(
                    id=question.id,
                    query=question.query,
                    passed=not failures,
                    failure_reasons=failures,
                    latency_ms=latency_ms,
                    citation_count=len(response.citations),
                    context_chars=len(response.context),
                    symbol_count=len(response.symbols),
                    expected_resource_ids=question.expected_resource_ids,
                    cited_resource_ids=sorted(cited_resource_ids),
                    forbidden_resource_ids=question.forbidden_resource_ids,
                    hit_quality=[
                        {
                            "resource_id": str(citation.resource_id),
                            "snapshot_id": str(citation.snapshot_id),
                            "path": citation.path,
                            "title": citation.title,
                            "ordinal": citation.ordinal,
                            "version": citation.version,
                            "score": citation.score,
                            "graph_score": citation.graph_score,
                            "score_components": citation.score_components,
                        }
                        for citation in response.citations
                    ],
                )
            )
        passed_count = sum(1 for result in results if result.passed)
        latencies = [result.latency_ms for result in results]
        eval_profile = normalize_retrieval_profile(payload.profile)
        eval_response = RetrievalEvalResponse(
            profile=eval_profile.name,
            workspace_id=workspace_id,
            project_id=project_id,
            generated_at=datetime.now(UTC),
            provider=embedding_config.provider,
            model=embedding_config.model,
            diagnostics={
                **diagnostics,
                "retrieval_profile": eval_profile.name,
                "retrieval_profile_weights": retrieval_profile_manifest()[eval_profile.name]["weights"],
                "rerank_score_range": [0.0, 1.0],
                "question_resource_coverage": question_resource_coverage,
            },
            summary=RetrievalEvalSummary(
                status="passed" if passed_count == len(results) else "failed",
                question_count=len(results),
                passed_count=passed_count,
                failed_count=len(results) - passed_count,
                pass_rate=round(passed_count / len(results), 4) if results else 0.0,
                max_latency_ms=max(latencies) if latencies else 0.0,
                avg_latency_ms=round(sum(latencies) / len(latencies), 2) if latencies else 0.0,
                failure_reasons=sorted(set(all_failure_reasons)),
            ),
            results=results,
        )
        persisted_resource_ids = set(referenced_ids)
        project_wide = False
        for effective_resource_ids in effective_resource_ids_by_question:
            if effective_resource_ids is None:
                project_wide = True
            else:
                persisted_resource_ids.update(effective_resource_ids)
        for result in results:
            persisted_resource_ids.update(result.cited_resource_ids)
        return _persist_retrieval_eval_run(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            principal=principal,
            payload=payload,
            response=eval_response,
            project_wide=project_wide,
            resource_ids=persisted_resource_ids,
        )



    return router
