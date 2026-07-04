from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from sourcebrief_api.auth import Principal
from sourcebrief_api.schemas import (
    SkillExportGenerateRequest,
    SkillExportRead,
    SkillExportReviewRequest,
)
from sourcebrief_api.skill_exports import SKILL_EXPORT_STATUS_APPROVED
from sourcebrief_shared.models import ContextPackVersion

ResolvePackVersion = Callable[[Session, UUID, UUID, str, int | str], ContextPackVersion]
GenerateSkillExport = Callable[[UUID, UUID, str, int, SkillExportGenerateRequest, Principal, Session], SkillExportRead]
ApproveSkillExport = Callable[[UUID, UUID, UUID, SkillExportReviewRequest, Principal, Session], SkillExportRead]


@dataclass(frozen=True)
class RuntimeSkillPackDeps:
    resolve_pack_version: ResolvePackVersion
    generate_skill_export: GenerateSkillExport
    approve_skill_export: ApproveSkillExport


def generate_skill_pack(
    session: Session,
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal,
    args: Mapping[str, Any],
    deps: RuntimeSkillPackDeps,
) -> dict[str, Any]:
    pack_key = str(args.get("pack_key") or "default")
    version_number = (
        int(args["version"])
        if args.get("version") is not None
        else deps.resolve_pack_version(session, workspace_id, project_id, pack_key, "current").version
    )
    payload = SkillExportGenerateRequest(
        title=str(args.get("title") or "SourceBrief runtime skill"),
        summary=str(args["summary"]) if args.get("summary") is not None else None,
    )
    export = deps.generate_skill_export(
        workspace_id, project_id, pack_key, version_number, payload, principal, session
    )
    approve_comment = args.get("approve_comment")
    if approve_comment:
        export = deps.approve_skill_export(
            workspace_id,
            project_id,
            export.id,
            SkillExportReviewRequest(comment=str(approve_comment)),
            principal,
            session,
        )
    export_dict = jsonable_encoder(export)
    download_path = f"/workspaces/{workspace_id}/projects/{project_id}/skill-exports/{export.id}/download.zip"
    return {
        "status": export.status,
        "skill_export": export_dict,
        "download_path": download_path,
        "download_available": export.status == SKILL_EXPORT_STATUS_APPROVED,
        "local_install": {
            "dry_run": "sourcebrief skill install --package <package-dir-or-zip> --target hermes --dry-run",
            "apply": "sourcebrief skill install --package <package-dir-or-zip> --target hermes --apply",
            "uninstall": "sourcebrief skill uninstall --receipt <receipt.json>",
        },
        "mutation_boundary": "MCP generation never writes local runtime files; install is a separate local CLI action.",
    }
