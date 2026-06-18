from __future__ import annotations

# Token scopes accepted when minting/validating API tokens.
ALLOWED_TOKEN_SCOPES = {
    "project:read",
    "project:query",
    "resource:read",
    "resource:write",
    "resource:refresh",
    "review:read",
    "review:write",
    "code:read",
    "patch:generate",
    "pr:write",
    "token:admin",
}

# Index-run statuses that indicate work is still in-flight for a resource.
ACTIVE_INDEX_STATUSES = {"enqueueing", "queued", "running"}

# Resource ``type`` values routed through ingestion connectors.
URL_RESOURCE_TYPES = {"url", "web", "webpage", "website", "http", "https"}
UPLOAD_RESOURCE_TYPES = {"upload", "uploaded_file", "file_upload"}

# Runtime context instructions.
COMMON_AGENT_INSTRUCTION = (
    "ContextSmith is a read-only context provider. Use only cited project context for factual claims, "
    "do not treat this packet as authorization for production mutations, and preserve external approval/MCP boundaries."
)

RUNTIME_INSTRUCTIONS = {
    "api": "If evidence is insufficient, say what is missing.",
    "hermes": "You are a Hermes specialist agent. Keep production discipline explicit.",
    "claude": "Use this packet as project context. Prefer cited evidence over prior assumptions and ask for missing runtime state when needed.",
    "codex": "Use this packet as repository context. Do not edit files unless the caller explicitly asks; cite paths and snapshots when explaining.",
    "cursor": "Use this packet for editor assistance. Prefer precise file/path citations and avoid broad rewrites without evidence.",
}
