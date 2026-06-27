# Default credential policy

Status: accepted for the local alpha
Related issue: [#135](https://github.com/pingchesu/sourcebrief/issues/135)

## Decision

SourceBrief does **not** ship a universal usable username/password such as `sourcebrief@mail.com` / `changeme` for normal startup.

The supported first-run path is:

1. Copy `.env.example` to `.env`.
2. Change `SOURCEBRIEF_ADMIN_PASSWORD` before first startup.
3. Start the local stack.
4. Use the web login or `sourcebrief login --password-env SOURCEBRIEF_ADMIN_PASSWORD` to create a local session token.

There is no `SOURCEBRIEF_DEMO_AUTH` / `make demo-up` default-credential shortcut in the current product. If a future demo-credential path is added, it must be a separate, loudly labelled disposable-loopback mode and must not weaken the normal startup path.

## Why

A universal default credential optimizes the first 30 seconds but creates a bad failure mode:

- users can accidentally bind the web/API ports to a shared or remote host;
- browser CORS settings can be changed for remote self-host demos;
- screenshots, blogs, and copy-pasted runbooks tend to preserve demo credentials;
- agents and scripts may retain the credential after the demo ends.

The safer product direction is to make the normal auth path easy rather than adding a second unsafe path. `sourcebrief login` now reads `.env` directly, so users do not need to `source .env` or enable dev-header auth for the CLI demo.

## Enforced invariants

- `.env.example` keeps `SOURCEBRIEF_ADMIN_PASSWORD=change-me-before-compose-up` as a sentinel, not a usable credential.
- API startup fails closed when `SOURCEBRIEF_ADMIN_PASSWORD` is `change-me-before-compose-up` or `sourcebrief-admin`.
- `SOURCEBRIEF_DEV_AUTH=false` remains the default. Dev header auth is for disposable local experiments only.
- Quickstart/demo docs must prefer web/session login and scoped bearer tokens over dev-header auth.
- Agents/CI/runtimes should use scoped `SOURCEBRIEF_TOKEN` values, not saved human sessions or default credentials.

## Rejected options

| Option | Decision | Reason |
| --- | --- | --- |
| Ship `sourcebrief@mail.com` / `changeme` | Rejected | Too easy to expose when ports/CORS are changed for remote demos. |
| Enable `SOURCEBRIEF_DEV_AUTH=true` by default | Rejected | Header auth is useful for tests/local experiments but not a safe onboarding default. |
| Add `SOURCEBRIEF_DEMO_AUTH=true` now | Deferred | Could be built later as a loopback-only disposable mode with UI/doctor warnings, but session-login ergonomics solve the current first-run problem without another auth mode. |

## Future demo-auth requirements

If SourceBrief later adds local demo credentials, acceptance must include all of the following:

- explicit opt-in (`SOURCEBRIEF_DEMO_AUTH=true` or `make demo-up`), never normal `make compose-up`;
- only works when API/web bindings and browser API URL are loopback/local;
- startup, UI, doctor, and CLI status show a warning;
- remote/CORS self-host setup fails closed while demo auth is enabled;
- docs present it as disposable-only and still recommend changing the admin password for any shared host.
