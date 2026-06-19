# PR1 — ContextSmith Enterprise Command Center Spec

## 1. Problem Statement

目前 ContextSmith 前端像是後端 API surface 的展示台，而不是企業級成熟產品。使用者進入系統後，看到的是一組以內部模組命名的 navigation：Dashboard、Import Resources、Repo Agents、Quality Evals、Agent Files、Git Env、Maintenance、Project Agent、Resources、Review Center、Ask / Citations、Login / Logout、Config、User Management、Admin。

這造成三個核心問題：

1. **資訊架構沒有對齊使用者任務**：使用者真正要完成的是「連接 sources → 確認 agent ready → 問問題取得 cited context → 驗證品質 → ship agent pack」，但 UI 要求使用者自己把十多個內部頁面拼起來。
2. **內部概念外露**：workspace/project/resource UUID、provider diagnostics、token/session 狀態目前直接佔據主視覺，降低企業產品的信任感與可用性。
3. **視覺與互動不像成熟產品**：目前樣式是 generic admin dashboard；缺少明確 design tokens、狀態層級、attention queue、可發現 primary action，也沒有清楚的 loading/empty/error/responsive 行為。

PR1 目標是建立新的 enterprise-grade frontend 基礎：新的 App Shell、Command Center 首頁、設計系統 primitives。它不解決所有頁面，但要把未來重構方向釘住。

## 2. Product Goal

ContextSmith 前端應該成為 **Agent Context Operating Console**：讓團隊管理 repo/document sources、觀察 context freshness 與品質、查詢 cited context，最後輸出可被 Hermes/Codex/Claude 使用的 agent pack。

首頁要回答：

- 目前 workspace/project 是什麼？
- Agent 是否 ready？
- 有多少 sources 已 connected/indexed/reviewed？
- 哪些 sources stale、failed、需要 review？
- 下一個最重要 action 是什麼？
- 如果我要開始使用 agent，應該去哪裡？

## 3. Non-Goals

PR1 不做以下事情：

- 不修改 backend API、DB schema、worker、retrieval、auth 或 migrations。
- 不修改 `apps/web/lib/platform-context.tsx` 的資料抓取模型，除非 implementation 發現 typing-only blocker。
- 不重寫所有現有頁面。
- 不新增大型 UI library、Tailwind、charting library 或 animation dependency。
- 不建立假資料、假 usage、假 testimonial 或 mock business metrics。
- 不把未完成的 Workbench/Sources/Quality/Ship flow 硬做成完整功能。
- 不更動 GitHub PR workflow / patch proposal backend contract。

## 4. Full Rebuild Information Architecture

未來完整前端應該收斂為以下主入口：

1. **Command Center** (`/`)
   - Project readiness
   - Attention queue
   - Source coverage
   - Agent quality snapshot
   - Suggested next actions

2. **Sources** (`/sources` future; can initially route to existing `/resources` and `/import`)
   - Connect git/url/file/document
   - Source lifecycle: connected → indexed → reviewed → serving context
   - Snapshot/index run evidence
   - Git environment settings as advanced source configuration

3. **Workbench** (`/workbench` future; can initially route to `/repo-agents` and `/ask`)
   - Select repo/document agent
   - Ask questions
   - Context packet preview
   - Citations/symbols/evidence
   - Optional patch/PR workflow

4. **Quality** (`/quality` future; can initially route to `/review` and `/evals`)
   - Review queue
   - Retrieval evals
   - Drift / stale / risk status
   - Quality gate history

5. **Ship** (`/ship` future; can initially route to `/agent-files` and `/agent-profile`)
   - Generated Hermes/Codex/Claude files
   - MCP config
   - Install/download agent pack
   - Runtime policy and tool boundary

6. **Operations / Admin**
   - Maintenance
   - Users & tokens
   - Audit events
   - Provider/config/session diagnostics

## 5. PR1 Exact Scope

PR1 implements only the first foundation slice:

- Rebuild global shell navigation around product tasks instead of internal modules.
- Rebuild `/` into Command Center.
- Introduce design tokens and reusable UI primitives that existing/future pages can use.
- Keep legacy pages reachable, but visually demote advanced/admin/debug pages.
- Preserve all backend contracts and existing pages unless required by shared CSS changes.

## 6. Design System Decisions

### Visual Direction

- Product identity: enterprise context operations console.
- Anchor: `tufte-dataink` for evidence-first layout + `bloomberg-terminal` for dense operational panels + restrained `raycast` command affordances.
- Avoid: generic white SaaS dashboard, purple/blue/pink gradients, emoji icons, fake metrics, large-radius card soup.

### Typography

Preferred CSS stack:

- Heading/body: `IBM Plex Sans`, `Space Grotesk`, fallback `ui-sans-serif` only as fallback.
- Mono: `IBM Plex Mono`, fallback `ui-monospace`.

No remote font dependency is required in PR1. If fonts are not installed locally, fallback is acceptable, but CSS must express the intended hierarchy through tokens.

### Colors

Use CSS variables in `apps/web/app/globals.css`:

- `--bg`: warm off-white / paper background.
- `--surface`: card surface.
- `--surface-strong`: dark evidence/console surface.
- `--ink`: primary text.
- `--muted`: secondary text.
- `--line`: borders and separators.
- `--ready`: healthy/ready state.
- `--warn`: needs attention/stale.
- `--risk`: failed/danger.
- `--accent`: primary action highlight.

Status colors must be semantic. Do not introduce one-off hex values in components unless promoted to a token.

### Spacing

- Base grid: 8px.
- Shell gutters: 20–32px depending on viewport.
- Dense data rows: 10–12px vertical rhythm.
- Major dashboard sections: 20–28px gaps.

### Radius & Shadow

- Radius should be restrained: product console, not toy app.
- Prefer borders, separators, contrast, and information hierarchy over heavy shadows.
- Cards can use subtle elevation but no glassmorphism.

### Motion

PR1 may use small CSS transitions only for:

- Navigation active/hover states.
- Card focus/hover affordance.
- Attention queue state emphasis.

No decorative animation in PR1.

### Accessibility

- Keyboard focus states for links/buttons.
- Sufficient color contrast for status chips and dark panels.
- Navigation landmarks (`nav`, `main`, `aside`, `header`) remain semantic.
- Responsive layout must keep nav and primary actions discoverable on mobile.

## 7. Files to Modify

Expected PR1 files:

- `apps/web/app/globals.css`
  - Add design tokens.
  - Replace generic styling with enterprise shell/card/status primitives.
  - Preserve class names used by existing pages where possible.

- `apps/web/components/AppShell.tsx`
  - Replace flat 15-item nav with grouped product IA.
  - Show workspace/project as human-readable names first.
  - Demote UUIDs to secondary/hidden diagnostic text, not primary UX.
  - Surface provider/session status without dominating the layout.

- `apps/web/components/ui.tsx`
  - Add/adjust primitives needed by Command Center: status chips, section cards, action links, evidence panels, attention rows.
  - Preserve existing exports (`PageHeader`, `Card`, `Metric`, `StatusChip`, `EmptyState`, `Field`) so legacy pages continue compiling.
  - Replace current string-contains status classification with explicit semantic mapping/helper; avoid implicit `includes()` drift.
  - Avoid one-off component logic that belongs in the page.

- `apps/web/app/page.tsx`
  - Rebuild Dashboard into Command Center.
  - Use existing `usePlatform()` state only.
  - Derive readiness and attention items from actual data.

Optional if strongly justified:

- `apps/web/lib/types.ts` only for UI type helper needs; avoid unless necessary.
- `apps/web/lib/api.ts` should not change in PR1.
- `apps/web/lib/platform-context.tsx` should not change in PR1.

禁區：

- `apps/api/**`
- `packages/**`
- `migrations/**`
- auth/token backend behavior
- worker/retrieval logic

## 8. Data Mapping from `usePlatform()`

Use existing fields from `apps/web/lib/platform-context.tsx`:

- `workspace`, `project`
  - Header identity: display names first.
  - Empty state when missing.

- `settings`
  - Detect signed-in mode (`bearer` or `email`) but do not expose tokens.
  - UUIDs may appear only in compact diagnostic text.

- `provider`
  - System health strip: provider status, embedding namespace/model.
  - Degraded state should become an attention item.

- `agents`, `agent`
  - Agent readiness card.
  - Runtime, resource count, snapshot count, graph node/edge count, last indexed.

- `resources`
  - Source coverage: total, active, git, retrieval enabled, stale/failed/archived/deleted counts.
  - Source map preview: top resources by attention priority.

- `reviewItems`
  - Attention queue: stale/not fresh items, stale reasons, usage count.
  - Quality snapshot: review risks count.

- `usageItems`
  - Retrieval usage snapshot: query/hit/context packet counts.
  - Use only real numbers; if no usage, show honest empty state.

- `tokens`, `members`, `auditEvents`
  - Admin/security summary only; no deep management UI on Command Center.

- `selectedResource`, `snapshots`, `indexRuns`, `graph`
  - Optional Command Center detail teaser for selected source if already loaded.
  - Do not make selected resource mandatory for homepage usefulness.

- `loading`, `error`, `reload`
  - Page-level loading and error states.
  - Reload action remains visible.

## 9. Derived State Formulas

Implementation should derive state locally in `page.tsx` or small helpers:

- `activeResources = resources.filter(r => r.status === 'active' && !r.deleted_at)`
- `gitResources = activeResources.filter(r => r.type === 'git')`
- `retrievalEnabled = activeResources.filter(r => r.retrieval_enabled)`
- `reviewRisks = reviewItems.filter(item => item.freshness_status !== 'fresh' || item.stale_reasons.length > 0)`
- `failedResources = activeResources.filter(r => ['failed', 'error'].includes(r.status.toLowerCase()))`
- `staleResources = reviewItems.filter(item => item.freshness_status !== 'fresh')`
- `usageHits = usageItems.reduce((sum, item) => sum + item.hit_count, 0)`
- `contextPackets = usageItems.reduce((sum, item) => sum + item.context_packet_count, 0)`

Readiness should not be a fake score. Use a transparent classification:

- `ready`: signed in, agent exists, provider ok, at least one active source, no failed provider.
- `attention`: signed in and agent exists, but stale/review/provider issues exist.
- `setup`: missing session, workspace/project, agent, or sources.

## 10. Enterprise-Grade Acceptance Criteria

PR1 is acceptable only if:

- Primary navigation reflects product workflow, not backend implementation modules.
- Command Center gives a clear next action for setup, healthy, and degraded states.
- User-facing UI does not require copying UUIDs to proceed.
- No fake business data, fake testimonials, fake logos, or placeholder metrics presented as real.
- Loading, empty, signed-out, degraded provider, no resources, and error states are explicitly designed.
- Desktop and mobile layouts are usable.
- Existing pages remain reachable and are not broken by CSS changes.
- Status language is precise: signed out, provider degraded, source stale, review needed, indexed, graph ready.
- Accessibility basics are present: semantic landmarks, focus states, contrast, keyboard-reachable actions.
- No backend changes are included.

## 11. Verification Commands

Run from repo root unless noted:

```bash
git status --short
npm --prefix apps/web run lint
npm --prefix apps/web run build
```

Browser smoke:

```bash
npm --prefix apps/web run dev -- --hostname 0.0.0.0 --port 13000
```

Then verify in browser:

- `/` desktop render.
- `/` mobile/narrow viewport render.
- Navigation links visible and grouped.
- Console has no runtime errors.
- Reload action works or reports a clear API/session state.
- Existing routes such as `/resources`, `/repo-agents`, `/agent-files`, `/config` still render.

Diff guard:

```bash
git diff --name-only origin/main...HEAD
```

Expected changed files should stay within PR1 scope.

## 12. Risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| CSS rewrite breaks legacy pages | Existing functionality appears broken | Preserve existing generic classes where possible; smoke several legacy routes |
| New IA hides advanced operations | Power users cannot find maintenance/config | Keep advanced/admin group visible but secondary |
| Design overreaches beyond real data | UI feels fake | Use only `usePlatform()` data and honest empty states |
| PR1 too large | Hard to review | Only shell, homepage, primitives; no backend or full page rewrites |
| Font availability differs | Visual drift | Use CSS stack fallbacks and verify layout, not exact font rendering |

## 13. Rollback

Rollback is simple because PR1 is frontend-only:

- Revert PR branch or merge commit.
- No DB migration rollback needed.
- No backend deployment compatibility concern.
- Existing backend API remains untouched.

If CSS regressions are found after merge, revert `globals.css`, `AppShell.tsx`, `ui.tsx`, and `page.tsx` together rather than partial rollback, because these files define one visual system.
