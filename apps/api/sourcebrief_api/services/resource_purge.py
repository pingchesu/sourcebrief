from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from sourcebrief_shared.models import Resource


def purge_resource_artifacts(session: Session, resource: Resource) -> dict[str, int]:
    params = {"resource_id": resource.id}
    family_ref = session.execute(
        text(
            """
            SELECT 1
            FROM snapshot_sections
            WHERE section_family_resource_id = :resource_id
              AND version_resource_id <> :resource_id
            UNION ALL
            SELECT 1
            FROM context_artifact_citations
            WHERE section_family_resource_id = :resource_id
              AND resource_id <> :resource_id
            LIMIT 1
            """
        ),
        params,
    ).first()
    if family_ref is not None:
        raise HTTPException(status_code=409, detail="This source family still has compiled versions. Delete dependent versions first.")
    pack_refs = session.execute(
        text(
            """
            SELECT cpv.pack_key, cpv.version, cpv.status
            FROM context_pack_resource_coverage cprc
            JOIN context_pack_versions cpv ON cpv.id = cprc.context_pack_version_id
            WHERE cprc.resource_id = :resource_id
              AND cpv.status <> 'invalidated'
            ORDER BY cpv.pack_key, cpv.version
            """
        ),
        params,
    ).mappings().all()
    if pack_refs:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Resource is covered by Context Pack versions. Invalidate those pack versions before hard purge.",
                "context_packs": [dict(row) for row in pack_refs],
            },
        )
    skill_export_refs = session.execute(
        text(
            """
            SELECT se.pack_key, se.pack_version, se.export_version, se.status, se.package_hash
            FROM skill_exports se
            JOIN context_pack_resource_coverage cprc ON cprc.context_pack_version_id = se.context_pack_version_id
            WHERE cprc.resource_id = :resource_id
              AND se.files_json <> '[]'::jsonb
            ORDER BY se.pack_key, se.pack_version, se.export_version
            """
        ),
        params,
    ).mappings().all()
    if skill_export_refs:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Resource is referenced by generated skill exports with retained files. Invalidate/scrub those exports before hard purge.",
                "skill_exports": [dict(row) for row in skill_export_refs],
            },
        )
    repo_agent_refs = session.execute(
        text(
            """
            SELECT ra.agent_key, COALESCE(rav.version, 0) AS version, COALESCE(rav.status, ra.status) AS status
            FROM repo_agents ra
            LEFT JOIN repo_agent_versions rav ON rav.repo_agent_id = ra.id AND rav.resource_id = :resource_id
            WHERE ra.resource_id = :resource_id OR rav.resource_id = :resource_id
            ORDER BY ra.agent_key, rav.version
            """
        ),
        params,
    ).mappings().all()
    if repo_agent_refs:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Resource is referenced by Repo Agent versions. Archive, invalidate, and scrub those versions before hard purge.",
                "repo_agents": [dict(row) for row in repo_agent_refs],
            },
        )
    graph_merge_refs = session.execute(
        text(
            """
            SELECT gm.merge_key, gmv.version, gmv.status
            FROM graph_merge_inputs gmi
            JOIN graph_merge_versions gmv ON gmv.id = gmi.graph_merge_version_id
            JOIN graph_merges gm ON gm.id = gmv.graph_merge_id
            WHERE gmi.input_resource_id = :resource_id
            ORDER BY gm.merge_key, gmv.version
            """
        ),
        params,
    ).mappings().all()
    if graph_merge_refs:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Resource is referenced by retained graph merge versions. E1 retains merge provenance, so hard purge remains blocked until a later scrub/delete lifecycle removes those versions.",
                "graph_merges": [dict(row) for row in graph_merge_refs],
            },
        )
    graph_refs = session.execute(
        text(
            """
            SELECT g.graph_key, COALESCE(gv.version, 0) AS version, COALESCE(gv.status, g.status) AS status
            FROM graphs g
            LEFT JOIN graph_versions gv ON gv.graph_id = g.id AND gv.resource_id = :resource_id
            WHERE g.resource_id = :resource_id OR gv.resource_id = :resource_id
            ORDER BY g.graph_key, gv.version
            """
        ),
        params,
    ).mappings().all()
    if graph_refs:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Resource is referenced by retained graph streams or graph versions. Archive zero-version graphs, or invalidate/retain graph versions before hard purge.",
                "graphs": [dict(row) for row in graph_refs],
            },
        )
    statements = [
        ("resources_current_snapshot", "UPDATE resources SET current_snapshot_id = NULL WHERE id = :resource_id"),
        (
            "context_pack_resource_coverage",
            "DELETE FROM context_pack_resource_coverage WHERE resource_id = :resource_id",
        ),
        (
            "context_pack_artifacts",
            "DELETE FROM context_pack_artifacts WHERE resource_id = :resource_id OR context_artifact_id IN (SELECT id FROM context_artifacts WHERE resource_id = :resource_id)",
        ),
        (
            "context_artifact_citations",
            """
            DELETE FROM context_artifact_citations
            WHERE resource_id = :resource_id
               OR context_artifact_id IN (SELECT id FROM context_artifacts WHERE resource_id = :resource_id)
            """,
        ),
        (
            "context_artifact_sources",
            """
            DELETE FROM context_artifact_sources
            WHERE resource_id = :resource_id
               OR context_artifact_id IN (SELECT id FROM context_artifacts WHERE resource_id = :resource_id)
            """,
        ),
        ("context_artifacts", "DELETE FROM context_artifacts WHERE resource_id = :resource_id"),
        ("snapshot_sections", "DELETE FROM snapshot_sections WHERE version_resource_id = :resource_id"),
        (
            "orphan_sections",
            """
            DELETE FROM sections s
            WHERE s.section_family_resource_id = :resource_id
              AND NOT EXISTS (SELECT 1 FROM snapshot_sections ss WHERE ss.section_id = s.id)
              AND NOT EXISTS (SELECT 1 FROM context_artifact_citations cac WHERE cac.section_id = s.id)
            """,
        ),
        ("pr_requests", "DELETE FROM pr_requests WHERE resource_id = :resource_id"),
        ("patch_proposals", "DELETE FROM patch_proposals WHERE resource_id = :resource_id"),
        ("agent_card_summaries", "DELETE FROM agent_card_summaries WHERE resource_id = :resource_id"),
        ("context_packet_items", "DELETE FROM context_packet_items WHERE resource_id = :resource_id"),
        ("retrieval_hits", "DELETE FROM retrieval_hits WHERE resource_id = :resource_id"),
        ("chunk_embeddings", "DELETE FROM chunk_embeddings WHERE resource_id = :resource_id"),
        ("graph_edges", "DELETE FROM graph_edges WHERE resource_id = :resource_id"),
        ("graph_nodes", "DELETE FROM graph_nodes WHERE resource_id = :resource_id"),
        ("code_symbols", "DELETE FROM code_symbols WHERE resource_id = :resource_id"),
        ("resource_manifest_files", "DELETE FROM resource_manifest_files WHERE resource_id = :resource_id"),
        ("resource_manifests", "DELETE FROM resource_manifests WHERE resource_id = :resource_id"),
        ("snapshot_files", "DELETE FROM snapshot_files WHERE resource_id = :resource_id"),
        ("chunks", "DELETE FROM chunks WHERE resource_id = :resource_id"),
        ("index_runs", "DELETE FROM index_runs WHERE resource_id = :resource_id"),
        ("source_snapshots", "DELETE FROM source_snapshots WHERE resource_id = :resource_id"),
    ]
    counts: dict[str, int] = {}
    for name, sql in statements:
        result = session.execute(text(sql), params)
        counts[name] = int(result.rowcount or 0)  # type: ignore[attr-defined]
    result = session.execute(text("DELETE FROM resources WHERE id = :resource_id"), params)
    counts["resources"] = int(result.rowcount or 0)  # type: ignore[attr-defined]
    return counts
