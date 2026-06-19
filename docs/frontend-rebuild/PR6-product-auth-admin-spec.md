# PR6 — Product auth and admin user management

## Problem

The current web console exposes alpha engineering auth mechanics (`X-User-Email`, bearer tokens, API base URL, workspace/project IDs) as the user login flow. A mature product should boot with an operator-provided default admin account, let that admin sign in with email/password, and manage users/roles from the web UI. Integration/API tokens may still exist, but they must not be the normal login path.

## Goals

1. Create a default admin user during API startup from environment variables.
2. Support email/password login from the web UI.
3. Let admins create additional users and assign workspace roles, including multiple admins.
4. Remove normal-user exposure of dev auth, bearer token login, editable API base URL, raw route IDs, and token/scopes language from nav-visible login/user/session UI.
5. Keep API tokens only as backend/integration credentials, not as human login instructions.

## Non-goals

- Full SSO/magic-link/OAuth.
- Complete fine-grained RBAC beyond existing workspace `owner/admin/member/viewer` semantics.
- Removing backend API-token support for agents/MCP/CLI.
- Perfect cookie/session hardening; this PR can use a backend-issued session token internally, but the UI must not ask users to paste one.

## Backend design

### Data model

Add to `users`:

- `password_hash text null`
- `is_active boolean not null default true`
- `is_platform_admin boolean not null default false`

Password hashes use stdlib PBKDF2-SHA256 with per-password salt to avoid adding new dependencies.

### Bootstrap env

- `CONTEXTSMITH_ADMIN_EMAIL`
- `CONTEXTSMITH_ADMIN_PASSWORD`
- `CONTEXTSMITH_ADMIN_DISPLAY_NAME`
- `CONTEXTSMITH_BOOTSTRAP_WORKSPACE_NAME`
- `CONTEXTSMITH_BOOTSTRAP_WORKSPACE_SLUG`
- `CONTEXTSMITH_BOOTSTRAP_PROJECT_NAME`

On startup, after optional migrations, idempotently:

1. Create/update the admin user.
2. Mark it active and platform-admin.
3. Create a default workspace/project if missing.
4. Ensure the admin is workspace `owner` and project `owner`.

### Auth endpoints

- `POST /auth/login` `{email,password}` → session token + current user + workspace/project defaults.
- `GET /auth/me` → current user + accessible workspaces/projects/defaults.
- `POST /auth/logout` → revoke current session token when token-backed.

The session token is implemented with the existing hashed `api_tokens` table and a reserved name/scope set. This keeps scope enforcement unchanged while removing token handling from human UX.

### Admin user endpoints

- `POST /workspaces/{workspace_id}/members` create a user if needed, set password if provided, and assign workspace role.
- `PATCH /workspaces/{workspace_id}/members/{membership_id}` update role/active/display name/password.

Guardrails:

- Only workspace `owner/admin` can manage members.
- Multiple admins are allowed.
- Last `owner/admin` cannot be downgraded/deactivated.

## Frontend design

### Login

Replace the session page with a normal product login:

- Email
- Password
- Submit
- No bearer token field
- No API base URL field
- No dev-auth text
- No workspace/project ID override

After login, store only the backend-issued internal session token and selected workspace/project IDs. Never show the token.

### App shell/session state

- Show signed-in user display name/email.
- Remove short workspace/project IDs from footer.
- Rename `Session` to `Sign in`/`Account`.
- If unauthenticated, show signed-out state without trying to load platform data.

### Users page

Convert from `Users & tokens` to `Team access`:

- Members count and admins count.
- Create user form: name, email, temporary password, role.
- Members table: name/email/role/status/joined.
- Role update control for admins.
- No API token/scopes/bounds table.

### Config page

Remove session/API base/bearer/project route setup from normal UI. Keep source addition and move integration tokens to product copy if present, but no login framing.

## Verification

- Unit tests for password hashing and bootstrap idempotency.
- API tests for login/me/logout and admin user creation/role update.
- Frontend lint/build.
- Docker compose starts with env default admin and API ready.
- Browser smoke: login with default admin, load Command Center, open Team Access, create a second admin/member.
- Source grep confirms no nav-visible page asks for bearer token/dev auth/API base URL/workspace route key.
