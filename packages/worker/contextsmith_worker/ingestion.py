"""Resource ingestion for ContextSmith Milestone 2.

This module turns a resource into a versioned ``source_snapshot`` plus a set of
lexical ``chunks``. Two connectors are supported:

* document/markdown resources: content is supplied inline via ``source_config``
  (never read from arbitrary host paths through the API), and
* git resources: a public ``https`` or local ``file://`` repository is cloned
  into a controlled work directory, the commit SHA is captured, and only
  text-ish, size-bounded files outside generated/dependency directories are
  indexed.

The pure helpers (``chunk_text``, ``content_hash``, ``is_text_file``,
``should_index_path``, ``validate_git_url``, ``iter_repo_files``) carry no
database or network state so they can be unit tested directly.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from contextsmith_shared.models import Chunk, IndexRun, Resource, SourceSnapshot

# --- configuration ---------------------------------------------------------

DEFAULT_MAX_FILE_BYTES = 1_000_000
HARD_MAX_FILE_BYTES = 5_000_000
DEFAULT_MAX_CHARS = 2_000
DEFAULT_OVERLAP = 200
DEFAULT_CLONE_TIMEOUT = 120

DOCUMENT_TYPES = {
    "markdown",
    "md",
    "doc",
    "document",
    "file",
    "text",
    "plaintext",
    "runbook",
}
GIT_TYPES = {"git", "git_repo", "git-repo", "repo", "repository"}

# Directories that never contain source worth indexing.
SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".cache",
    "dist",
    "build",
    "target",
    "out",
    ".next",
    ".nuxt",
    ".gradle",
    ".idea",
    ".vscode",
    "vendor",
    ".tox",
    "coverage",
    "site-packages",
}

# Binary / non-text extensions we refuse to index.
SKIP_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".tiff",
    ".pdf", ".zip", ".gz", ".tar", ".tgz", ".bz2", ".xz", ".7z", ".rar",
    ".jar", ".war", ".ear", ".class", ".so", ".dll", ".dylib", ".o", ".a",
    ".bin", ".exe", ".wasm", ".pyc", ".pyo", ".pdb",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".mp3", ".mp4", ".mov", ".avi", ".mkv", ".wav", ".flac", ".ogg", ".webm",
    ".db", ".sqlite", ".sqlite3", ".dat", ".iso", ".dmg", ".img",
}

# Large generated lockfiles add noise without value for lexical search.
SKIP_FILENAMES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "Cargo.lock",
    "composer.lock",
    "go.sum",
    "Gemfile.lock",
}

_SAFE_REF = re.compile(r"^[A-Za-z0-9._\-/]+$")


# --- pure helpers ----------------------------------------------------------

def content_hash(text: str) -> str:
    """Return a stable sha256 hex digest for ``text``."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def chunk_text(
    content: str,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap: int = DEFAULT_OVERLAP,
) -> list[str]:
    """Split ``content`` into overlapping chunks at natural boundaries.

    Deterministic and boundary-aware: it prefers to break on paragraph, then
    line, then word boundaries within the trailing half of each window so chunks
    stay readable. Whitespace-only input yields an empty list.
    """
    if not content or not content.strip():
        return []
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    overlap = max(0, min(overlap, max_chars - 1))

    chunks: list[str] = []
    n = len(content)
    start = 0
    while start < n:
        end = min(start + max_chars, n)
        if end < n:
            window = content[start:end]
            for sep in ("\n\n", "\n", " "):
                idx = window.rfind(sep)
                if idx != -1 and idx >= max_chars // 2:
                    end = start + idx + len(sep)
                    break
        piece = content[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return chunks


def is_text_file(data: bytes) -> bool:
    """Heuristically decide whether ``data`` is UTF-8 text (not binary)."""
    if not data:
        return True
    if b"\x00" in data[:8192]:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def should_index_path(relpath: str) -> bool:
    """Return True if a repo-relative path should be indexed."""
    posix = relpath.replace("\\", "/").strip("/")
    if not posix:
        return False
    parts = posix.split("/")
    if any(part in SKIP_DIRS for part in parts[:-1]):
        return False
    if any(part in SKIP_DIRS for part in parts):
        return False
    name = parts[-1]
    if name in SKIP_FILENAMES:
        return False
    ext = os.path.splitext(name)[1].lower()
    if ext in SKIP_EXTS:
        return False
    return True


def validate_git_url(url: str) -> tuple[bool, str]:
    """Validate and classify a git source URL.

    Returns ``(is_local, target)`` where ``target`` is the URL/path to hand to
    git. Only ``https`` remotes and local ``file://``/filesystem paths are
    accepted; ssh, git, and remote-helper transports (``ext::`` etc.) are
    rejected to avoid arbitrary command execution and to keep the surface small.
    """
    if not isinstance(url, str):
        raise ValueError("git url must be a string")
    candidate = url.strip()
    if not candidate:
        raise ValueError("git url is empty")
    if any(ch.isspace() for ch in candidate) or "\x00" in candidate:
        raise ValueError("git url contains whitespace or control characters")
    if candidate.startswith("-"):
        raise ValueError("git url must not start with '-'")
    lowered = candidate.lower()
    if "::" in candidate or lowered.startswith(("ext::", "fd::")):
        raise ValueError("unsupported git transport")

    parsed = urlparse(candidate)
    scheme = parsed.scheme.lower()
    if scheme == "https":
        if not parsed.netloc:
            raise ValueError("https git url missing host")
        return (False, candidate)
    if scheme == "file":
        path = candidate[len("file://") :]
        if not path:
            raise ValueError("file git url missing path")
        return (True, path)
    if scheme == "" and candidate.startswith(("/", "./", "../", "~")):
        return (True, os.path.expanduser(candidate))
    raise ValueError(f"unsupported git url scheme: {scheme or 'none'}")


def iter_repo_files(
    root: str | os.PathLike[str],
    *,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
) -> Iterator[tuple[str, str]]:
    """Yield ``(relpath, text)`` for indexable text files under ``root``.

    Skips generated/dependency directories, binary and oversized files, and
    symlinks. Every yielded file is verified to resolve inside ``root`` so a
    symlink cannot leak host files outside the clone. Output is sorted by path
    for deterministic snapshots/ordinals.
    """
    root_path = Path(root).resolve()
    collected: list[tuple[str, str]] = []
    for dirpath, dirnames, filenames in os.walk(root_path):
        # Prune skip dirs and symlinked dirs in place (os.walk does not follow
        # symlinks by default, but we drop the entries to be explicit).
        dirnames[:] = [
            d
            for d in dirnames
            if d not in SKIP_DIRS and not os.path.islink(os.path.join(dirpath, d))
        ]
        for name in filenames:
            full = Path(dirpath) / name
            if full.is_symlink():
                continue
            try:
                resolved = full.resolve()
            except OSError:
                continue
            if not resolved.is_relative_to(root_path):
                continue
            rel = full.relative_to(root_path).as_posix()
            if not should_index_path(rel):
                continue
            try:
                if full.stat().st_size > max_file_bytes:
                    continue
                data = full.read_bytes()
            except OSError:
                continue
            if not is_text_file(data):
                continue
            collected.append((rel, data.decode("utf-8")))
    collected.sort(key=lambda item: item[0])
    yield from collected


# --- git plumbing ----------------------------------------------------------

def _git_env() -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_ASKPASS": os.devnull,
            "GIT_ALLOW_PROTOCOL": "https:file",
            "GCM_INTERACTIVE": "never",
        }
    )
    return env


def clone_repo(
    target: str,
    is_local: bool,
    dest: str | os.PathLike[str],
    *,
    branch: str | None = None,
    timeout: int = DEFAULT_CLONE_TIMEOUT,
) -> None:
    """Clone ``target`` into ``dest`` with hooks disabled and no code execution."""
    args = ["git", "-c", f"core.hooksPath={os.devnull}", "-c", "protocol.ext.allow=never"]
    args += ["-c", f"protocol.file.allow={'always' if is_local else 'never'}"]
    args += [
        "clone",
        "--depth",
        "1",
        "--single-branch",
        "--no-tags",
        "--no-recurse-submodules",
        "--quiet",
    ]
    if branch:
        if not _SAFE_REF.match(branch) or ".." in branch:
            raise ValueError("invalid branch name")
        args += ["--branch", branch]
    args += ["--", target, str(dest)]
    try:
        proc = subprocess.run(
            args, env=_git_env(), timeout=timeout, capture_output=True, text=True, check=False
        )
    except FileNotFoundError as exc:  # git not installed
        raise RuntimeError("git executable not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"git clone timed out after {timeout}s") from exc
    if proc.returncode != 0:
        raise RuntimeError(f"git clone failed: {proc.stderr.strip()[:500]}")


def get_commit_sha(repo_dir: str | os.PathLike[str], *, timeout: int = 30) -> str:
    args = ["git", "-C", str(repo_dir), "rev-parse", "HEAD"]
    try:
        proc = subprocess.run(
            args, env=_git_env(), timeout=timeout, capture_output=True, text=True, check=False
        )
    except FileNotFoundError as exc:
        raise RuntimeError("git executable not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"git rev-parse timed out after {timeout}s") from exc
    if proc.returncode != 0:
        raise RuntimeError(f"git rev-parse failed: {proc.stderr.strip()[:300]}")
    return proc.stdout.strip()


def _work_base() -> str:
    base = os.getenv("CONTEXTSMITH_WORK_DIR") or os.path.join(
        tempfile.gettempdir(), "contextsmith-ingest"
    )
    os.makedirs(base, exist_ok=True)
    return base


# --- document model --------------------------------------------------------

def _coerce_documents(source_config: dict) -> list[dict]:
    """Extract inline documents from a document resource's source_config."""
    docs: list[dict] = []
    raw_docs = source_config.get("documents")
    if isinstance(raw_docs, list):
        for entry in raw_docs:
            if not isinstance(entry, dict):
                continue
            content = entry.get("content") or entry.get("text") or ""
            if not isinstance(content, str) or not content.strip():
                continue
            docs.append(
                {
                    "path": entry.get("path") or entry.get("title"),
                    "title": entry.get("title") or entry.get("path"),
                    "content": content,
                    "meta": {"source": "document"},
                }
            )
        return docs

    content = (
        source_config.get("content")
        or source_config.get("text")
        or source_config.get("body")
        or ""
    )
    if isinstance(content, str) and content.strip():
        docs.append(
            {
                "path": source_config.get("path"),
                "title": source_config.get("title"),
                "content": content,
                "meta": {"source": "document"},
            }
        )
    return docs


def _collect_documents(resource: Resource) -> tuple[list[dict], str, str, dict]:
    config = resource.source_config or {}
    docs = _coerce_documents(config)
    for doc in docs:
        if not doc.get("title"):
            doc["title"] = resource.name
        if not doc.get("path"):
            doc["path"] = resource.uri
    combined = "\n\n".join(doc["content"] for doc in docs)
    version = content_hash(combined)
    meta = {
        "source": "document",
        "uri": resource.uri,
        "document_count": len(docs),
    }
    return docs, version, "content_hash", meta


def _collect_git(resource: Resource) -> tuple[list[dict], str, str, dict]:
    config = resource.source_config or {}
    url = config.get("url") or resource.uri
    branch = config.get("branch") or config.get("ref")
    max_file_bytes = min(
        int(config.get("max_file_bytes", DEFAULT_MAX_FILE_BYTES)), HARD_MAX_FILE_BYTES
    )
    timeout = min(int(config.get("clone_timeout", DEFAULT_CLONE_TIMEOUT)), 600)

    is_local, target = validate_git_url(url)
    clone_dir = tempfile.mkdtemp(prefix="repo-", dir=_work_base())
    try:
        clone_repo(target, is_local, clone_dir, branch=branch, timeout=timeout)
        commit = get_commit_sha(clone_dir)
        docs = [
            {
                "path": rel,
                "title": rel,
                "content": text,
                "meta": {"source": "git", "path": rel, "commit": commit},
            }
            for rel, text in iter_repo_files(clone_dir, max_file_bytes=max_file_bytes)
        ]
    finally:
        shutil.rmtree(clone_dir, ignore_errors=True)

    meta = {
        "source": "git",
        "remote_url": url,
        "commit": commit,
        "branch": branch,
        "file_count": len(docs),
    }
    return docs, commit, "commit_sha", meta


# --- orchestration ---------------------------------------------------------

def ingest_resource(session: Session, resource: Resource, run: IndexRun) -> SourceSnapshot:
    """Produce a snapshot and chunks for ``resource`` within ``run``.

    Runs inside the caller's transaction so that a failure rolls back the
    snapshot and chunk inserts together (no orphaned partial snapshot).
    """
    rtype = (resource.type or "").lower()
    now = datetime.now(UTC)
    snapshot = SourceSnapshot(
        workspace_id=resource.workspace_id,
        project_id=resource.project_id,
        resource_id=resource.id,
        version="",
        version_kind="content_hash",
        status="running",
        fetched_at=now,
    )
    session.add(snapshot)
    session.flush()
    run.snapshot_id = snapshot.id

    if rtype in GIT_TYPES:
        docs, version, version_kind, meta = _collect_git(resource)
    elif rtype in DOCUMENT_TYPES:
        docs, version, version_kind, meta = _collect_documents(resource)
    else:
        # Unknown types fall back to inline-document handling when content is
        # present; otherwise we refuse rather than guess.
        docs, version, version_kind, meta = _collect_documents(resource)
        if not docs:
            raise RuntimeError(f"unsupported resource type for ingestion: {resource.type!r}")

    snapshot.version = version
    snapshot.version_kind = version_kind
    snapshot.meta = meta

    chunks_created = 0
    for doc in docs:
        pieces = chunk_text(doc["content"])
        for ordinal, piece in enumerate(pieces):
            session.add(
                Chunk(
                    workspace_id=resource.workspace_id,
                    project_id=resource.project_id,
                    resource_id=resource.id,
                    source_snapshot_id=snapshot.id,
                    path=doc.get("path"),
                    title=doc.get("title"),
                    content=piece,
                    ordinal=ordinal,
                    content_hash=content_hash(piece),
                    meta=doc.get("meta", {}),
                )
            )
            chunks_created += 1

    snapshot.status = "succeeded"
    snapshot.indexed_at = datetime.now(UTC)
    run.documents_seen = len(docs)
    run.chunks_created = chunks_created
    resource.current_snapshot_id = snapshot.id
    resource.status = "active"
    return snapshot
