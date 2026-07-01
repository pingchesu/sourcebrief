from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class SourceBriefCliError(RuntimeError):
    """User-facing CLI error."""


class SourceBriefClient:
    def __init__(self, api_url: str, email: str, token: str | None = None, timeout: float = 30.0) -> None:
        self.api_url = api_url.rstrip("/")
        self.email = email
        self.token = token
        self.timeout = timeout

    def request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        expected: set[int] | None = None,
    ) -> Any:
        expected = expected or {200}
        data = None
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        else:
            headers["X-User-Email"] = self.email
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(f"{self.api_url}{path}", data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:  # noqa: S310 - user-provided API base is intentional CLI behavior
                payload = response.read()
                status = response.status
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise SourceBriefCliError(
                f"{method} {path} failed with HTTP {exc.code}: {detail}"
            ) from exc
        except URLError as exc:
            raise SourceBriefCliError(f"failed to reach {self.api_url}: {exc.reason}") from exc
        if status not in expected:
            raise SourceBriefCliError(f"{method} {path} expected {sorted(expected)}, got {status}")
        if not payload:
            return None
        try:
            return json.loads(payload)
        except json.JSONDecodeError as exc:
            raise SourceBriefCliError(f"{method} {path} returned non-JSON response") from exc
