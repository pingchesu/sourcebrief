from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IntegerImportLimit:
    default: int
    maximum: int


GIT_CLONE_TIMEOUT = IntegerImportLimit(default=120, maximum=600)
GIT_MAX_FILE_BYTES = IntegerImportLimit(default=1_000_000, maximum=10_000_000)
GIT_MAX_REPO_FILES = IntegerImportLimit(default=1_000, maximum=5_000)
GIT_MAX_REPO_BYTES = IntegerImportLimit(default=20_000_000, maximum=200_000_000)
GIT_MAX_CHUNKS = IntegerImportLimit(default=5_000, maximum=20_000)
GIT_MAX_SYMBOLS = IntegerImportLimit(default=5_000, maximum=20_000)

GIT_INTEGER_IMPORT_LIMITS: dict[str, IntegerImportLimit] = {
    "clone_timeout": GIT_CLONE_TIMEOUT,
    "max_file_bytes": GIT_MAX_FILE_BYTES,
    "max_repo_files": GIT_MAX_REPO_FILES,
    "max_repo_bytes": GIT_MAX_REPO_BYTES,
    "max_chunks": GIT_MAX_CHUNKS,
    "max_symbols": GIT_MAX_SYMBOLS,
}
