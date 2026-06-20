# PR3 — SourceBrief Agent Workbench Spec

> 延續 PR1（enterprise shell + Command Center + design primitives）與 PR2（Sources lifecycle hub）。本 PR **不動 backend**，僅把目前割裂的 `/repo-agents` 與 `/ask` 收斂成單一 canonical **Agent Workbench** (`/workbench`)。
> 對應 PR1 IA 中 **Build context → Workbench** 與 **Ask & citations** 兩個入口（PR1 spec §4.2）。

## 1. Problem Statement / Product Goal

### 問題

PR1（Command Center）回答「agent 是否 ready、下一步去哪」；PR2（Sources）回答「每個 source 走到 lifecycle 哪一階段、就地維運」。但使用者真正要**用** agent 的環節仍散在兩頁，且體驗倒退回「API demo」：

1. **同一件事被切成兩頁**：「選一個 repo 當 sub-agent → 問它問題 → 看回傳的 cited context」這條工作流被拆成 `/repo-agents`（選 repo agent、看 brief）與 `/ask`（選 scope、問問題）。使用者要在兩頁間來回，且兩頁的 scope 模型互不相通。
2. **兩套不一致的 scope 模型**：`/repo-agents` 用「repo agent 卡片」選單一 git resource（透過 `generateSubAgentPrompt` 打 `agent-context`）；`/ask` 用 `ResourceScopePicker` 選「all / 多個 resource」。同一個 `agent-context` endpoint，卻有兩種選 scope 的 UX，使用者無法在一處表達「整個專案 / 單一 repo agent / 自選多個 source」。
3. **readiness 邏輯重複且可能漂移**：`/repo-agents` 內嵌了一份 `readiness()`，與 PR2 抽出的 `lib/lifecycle.ts` 是兩套來源。Workbench 必須複用 `lib/lifecycle.ts` 的單一事實來源。
4. **evidence 與提問脫節**：`/ask` 的 `AgentContextPreview`（citations / symbols / context packet）與 `/repo-agents` 的 repo 操作 brief、suggested questions、invocation contract 是分開呈現的；使用者看到「這個 repo agent ready」與「實際問它、看它引用了哪些檔案」不在同一個視野。
5. **仍偏向技術 demo 而非成熟工作台**：兩頁都缺一個統一的「scope readiness → 建議問題 → 提問 → cited 證據」的成熟運維敘事。

### 產品目標

把 agent 的**使用**收斂成單一 canonical **Agent Workbench**，回答企業使用者的核心問題：

- 我要問哪個範圍？整個專案、某一個 repo sub-agent、還是自選幾個 source？（全程以**名稱**選取，不需貼 UUID）
- 我選的範圍**ready 嗎**？（readiness 燈號、freshness、是否 indexed / retrieval-ready，沿用 PR2 lifecycle 語彙）
- 這個範圍**值得問什麼**？（依 scope 給出 suggested prompts；repo agent 用後端 `repo-agents/{id}/brief` 的 `suggested_questions` 與 operating brief）
- 我問了之後，agent 實際**讀到什麼 context、引用了哪些檔案與 symbol**？（`AgentContextPreview`：instruction / context packet / citations / code symbols）
- 我看到的 context 是**為目前控制項生成的嗎**？（沿用 `/ask` 的「generated-for / stale」守則，避免拿舊 scope 的證據做審核）

**衡量標準**：使用者在單一 `/workbench` 頁，全程不需閱讀或複製任何 UUID，即可完成「選 scope（專案 / repo agent / 自選 source）→ 確認 readiness → 採用建議問題或自行提問 → 檢視 cited context / symbols」整條路徑；所有狀態與數字都來自真實 API，無 mock。

## 2. Non-Goals

PR3 **不**做以下事情：

- 不修改 backend：`apps/api/**`、`packages/**`、`migrations/**`、worker / retrieval / auth 一律不動。
- 不新增後端 endpoint。Workbench 只用既有 endpoint：`agent-context`、`repo-agents/{id}/brief`、`agent-card-summaries`(+ `/run`)、`remote-code/generate_patch`、`remote-code/open_pr`。
- 不修改資料抓取模型 `apps/web/lib/platform-context.tsx` 與 `apps/web/lib/api.ts`（除非遇 typing-only blocker，且須在 PR 說明）。Workbench 所需的 `resources` / `agent` / `reviewItems` / `usageItems` / `client` / `settings` 皆已存在。
- 不改 `ResourceScopePicker.tsx` 與 `AgentContextPreview.tsx` 的**行為契約**；Workbench 直接複用兩者既有 props。最多視覺對齊，不改 signature（兩者仍被 `/evals`、`/sources` 等頁使用）。
- 不重建 Command Center (`/`)、Sources (`/sources`)、Quality (`/review`, `/evals`)、Ship (`/agent-files`, `/agent-profile`)、Operations 頁。
- 不改 `lib/lifecycle.ts` 的 readiness 契約；Workbench **複用**它（取代 `/repo-agents` 內嵌的第二份 readiness）。
- 不新增大型 UI library、Tailwind、charting、animation 等相依。
- 不做 fake data / fake usage / placeholder metric；沒資料就誠實顯示 empty state。
- 不擴張 opt-in patch/PR 與 drift audit 的**後端契約或安全模型**；PR3 僅把這些既有動作平移進 Workbench 的 Advanced 區塊，預設折疊、預設 read-only，不改其 gating 文案與 endpoint。
- 不引入 client-side 輪詢/即時刷新；沿用 PR1 的 `reload()` 手動刷新模型。

## 3. PR3 Exact Scope & Files

### 設計取向（先講清楚路由決策）

採 **single canonical workbench + in-page scope 選取**：

- 新增 `/workbench` 作為唯一 canonical Agent Workbench（scope 選取 + readiness + suggested prompts + ask + cited evidence + repo-agent brief + 折疊式 Advanced governance）。
- scope 以**名稱**選取（repo-agent 卡片 / `ResourceScopePicker` 多選），**URL 不帶 resource UUID**，符合 no-UUID-first。
- `/repo-agents` 與 `/ask` 改為輕量 `redirect('/workbench')`，舊連結（含 Command Center 內既有 `/repo-agents`、`/ask` link）不 404。
- `/repo-agents` 既有的 **drift audit** 與 **opt-in patch/PR** 動作不丟失：平移進 Workbench 折疊式 Advanced 區塊（同 endpoint、同 gating 文案、預設折疊）。
- AppShell nav 的「Workbench」入口由 `/repo-agents` 改指 `/workbench`；「Ask & citations」入口移除（已被 Workbench 吸收），避免重複入口。

> 為什麼用 `/workbench` 新路由而非原地改 `/repo-agents`：PR1 IA 已把該入口命名為 **Workbench**；新路由讓 nav 命名與 IA 一致，並讓 `/repo-agents`、`/ask` 安全轉址、降低 regression 面（與 PR2 用 `/sources` 取代 `/resources`/`/import`/`/git-env` 的決策一致）。

### 要修改 / 新增的檔案（實作階段）

| 檔案 | 動作 | 說明 |
| --- | --- | --- |
| `apps/web/app/workbench/page.tsx` | **新增** | Canonical Agent Workbench：scope（project / repo agent / custom）+ readiness strip + suggested prompts + ask（runtime/topK/question + generated-for/stale 守則）+ `AgentContextPreview` + 選定 repo agent 的 operating brief / invocation contract / safety boundary + 折疊式 Advanced（drift audit + opt-in patch/PR）。 |
| `apps/web/app/repo-agents/page.tsx` | **重建為轉址** | `redirect('/workbench')`。原 selection / brief / drift / patch-PR 全部平移進 `/workbench`。 |
| `apps/web/app/ask/page.tsx` | **重建為轉址** | `redirect('/workbench')`。原 scope-picker + ask + preview 由 `/workbench` 吸收。 |
| `apps/web/components/AppShell.tsx` | **修改 nav** | 「Build context」群組：Workbench 入口指向 `/workbench`；移除重複的「Ask & citations」入口（功能已併入 Workbench）。其餘 nav 不動。 |
| `apps/web/app/globals.css` | **新增 class（additive）** | Workbench scope 選取 / segmented 模式切換 / suggested-prompt grid 所需的少量 class，沿用既有 token；不改既有 class 行為。 |

> `ui.tsx`、`lib/lifecycle.ts`、`AgentContextPreview.tsx`、`ResourceScopePicker.tsx` 預設**不改**：Workbench 以組合既有 export 達成。若 lint/build 出現 typing-only blocker 才最小幅度調整，並在 PR 說明。

### 不可碰（禁區）

- `apps/api/**`、`packages/**`、`migrations/**`
- `apps/web/lib/api.ts`、`apps/web/lib/platform-context.tsx`（資料模型不變）
- `apps/web/components/ResourceScopePicker.tsx`、`apps/web/components/AgentContextPreview.tsx`（行為契約）
- `apps/web/lib/lifecycle.ts`（readiness 契約；只複用不改）
- 其他頁面：`/`、`/sources`、`/review`、`/evals`、`/agent-files`、`/agent-profile`、`/config`、`/admin`、`/users`、`/maintenance`、`/git-env`、`/resources`、`/import`

### 一個 PR 的合理性

實質新代碼集中在一支頁面（`/workbench`）＋ additive CSS；其餘是兩支轉址與一處 nav 微調。沒有 backend、沒有資料模型變更，且複用既有 `AgentContextPreview` / `ResourceScopePicker` / `lib/lifecycle.ts`，review 面可控。

## 4. Target Workbench IA & UX

### 4.1 路由與結構

```
/workbench                          ← 唯一 canonical Agent Workbench
  ├─ Header                         ← PageHeader：標題 + 動作 (Reload)
  ├─ Workbench readiness strip      ← 真實計數：repo agents / ready / needs review / retrieval-ready / drift findings
  ├─ Scope + Ask (兩欄)
  │   ├─ Scope panel (左)
  │   │   ├─ Scope mode segmented：Whole project | Repo sub-agent | Custom sources
  │   │   ├─ Repo-agent 卡片（mode=agent；以名稱+readiness 選，UUID 不出現於主視覺）
  │   │   ├─ ResourceScopePicker（mode=custom；複用既有多選元件）
  │   │   └─ Suggested prompts（依 scope；repo agent 用 brief.suggested_questions）
  │   └─ Ask panel (右)
  │       ├─ Runtime / Top K
  │       ├─ Question textarea
  │       ├─ Generate cited answer context
  │       └─ generated-for notice + 控制項變動的 stale 警示
  ├─ Selected repo-agent brief       ← mode=agent 時：operating brief / quality gates / invocation contract / safety boundary / drift summary
  ├─ AgentContextPreview             ← instruction / context packet / citations / code symbols（真實 API）
  └─ Advanced（折疊，預設關閉）        ← drift audit run（dry-run）＋ opt-in patch/PR（平移自 /repo-agents，gating 文案不變）
```

桌面為兩欄（scope | ask），窄屏堆疊，沿用既有 `.grid.two` 與 `@media` 行為。

### 4.2 Scope 模型（統一三種，對映同一個 `agent-context` body）

| Scope mode | 使用者選取方式 | `agent-context` body 的 `resource_ids` |
| --- | --- | --- |
| **Whole project** | 不需選（預設） | `null`（整個專案 retrieval-enabled current resources） |
| **Repo sub-agent** | 點選 repo-agent 卡片（名稱、readiness） | `[selectedRepoAgentId]` |
| **Custom sources** | `ResourceScopePicker` 多選（名稱） | `selectedIds`（多個） |

> 三種模式共用同一支 `agent-context` endpoint 與既有參數（`runtime` / `top_k` / `max_chars` / `include_code_symbols`），消除 `/repo-agents` 與 `/ask` 兩套 scope UX。

### 4.3 Readiness（複用 `lib/lifecycle.ts`，不重寫）

- repo-agent 卡片與 strip 的綜合燈號一律用 `lib/lifecycle.ts` 的 `readiness(resource, reviewItem)` 與 `readinessTone(...)`、`ReadinessBadge`（PR2 primitive）。
- readiness ladder（沿用）：`inactive → retrieval-off → not-indexed → needs-review → ready`。
- drift findings 計數沿用 `agent-card-summaries` 的 `status !== 'healthy'`。

### 4.4 各區塊行為

**Header**
- `PageHeader` eyebrow `Workbench`、title「Agent Workbench」。
- Action：`Reload`（呼叫 `reload()`）。

**Readiness strip**（沿用 `.health-strip` 或 `.grid.four` metric）
- 真實計數：Repo sub-agents、Ready、Needs review、Retrieval-ready、Drift findings。0 用 neutral tone，不誤導。

**Scope panel（左）**
- Segmented 模式切換（三選一）。切換 mode 時保留各自選取狀態，並更新 suggested prompts。
- `mode=agent`：repo-agent 卡片列表（`resources.filter(type==='git')`）；每張顯示 name、type、readiness chip、snapshot/freshness/uses 次要 metric；點選即設為 scope（不打 UUID）。無 git resource 時顯示 empty state 引導去 `/sources` 連 git source。
- `mode=custom`：複用 `ResourceScopePicker`（既有契約），label 為「Ask scope」。
- `mode=project`：不需選，顯示說明「整個專案的 retrieval-enabled current resources 皆在 scope」。
- Suggested prompts：
  - `agent`：優先用 `repo-agents/{id}/brief` 回傳的 `suggested_questions`；未載入時用 fallback（依 resource name 生成的問題模板，沿用 `/repo-agents` 既有文案）。
  - `project` / `custom`：少量通用 prompt（描述 scope、要求 cite 檔案）。
  - 點 prompt → 帶入 question 並觸發一次 generate（沿用 `/repo-agents` 點問題即生成的行為）。

**Ask panel（右）**
- Runtime select（hermes / claude / codex / cursor / api，預設 `agent.default_runtime ?? 'hermes'`）、Top K（1–50）。
- Question textarea。
- `Generate cited answer context` → POST `agent-context`（body 依 4.2 的 scope 映射 + runtime/topK/max_chars=22000/include_code_symbols=true）。
- 生成後記錄 `generatedFor`（scope 描述 / question / runtime / topK）；若目前控制項與 `generatedFor` 不一致，顯示 stale 警示「Displayed context was generated for previous controls. Regenerate before review/approval.」（沿用 `/ask` 守則）。

**Selected repo-agent brief**（`mode=agent` 且有選定 repo agent）
- 沿用 `/repo-agents/{id}/brief`：readiness、branch/commit/snapshot identity、operating brief（`operating_brief`）、quality gates、invocation contract、safety boundary、drift audit summary（若已 run）。
- loading / error / 無 brief 皆有誠實狀態。

**AgentContextPreview**
- 直接複用既有元件（`result` / `resources` / `title`）：runtime / citations / cited resources / symbols metric、instruction、context packet、citations 表、code symbols 表。

**Advanced（折疊，預設關閉）**
- **Drift audit**：`agent-card-summaries/run?dry_run=true`（POST，read-only）＋ 顯示 summaries。沿用 `/repo-agents` 文案（read-only、只寫 SourceBrief summary/audit 記錄）。
- **Opt-in patch / PR**（需選定 repo agent）：平移 `/repo-agents` 既有表單與 `remote-code/generate_patch`、`remote-code/open_pr`，**gating 文案、warning、預設 read-only 一字不改**（policy `patch_generation=enabled` + `patch:generate`；PR record 需 `open_pr=enabled` + `pr:write` + 明確 approval）。

### 4.5 狀態覆蓋（必須全部設計）

loading、未簽入 / 無 workspace（沿用 context 的空狀態）、無 git resource（agent mode empty）、無 resource（custom mode empty）、provider degraded（沿用 PR1 警示，可選）、ask 進行中（disabled + 「Generating…」）、ask 失敗（error notice）、未生成（`AgentContextPreview` 的 empty）、brief loading / error、drift 未 run、patch gating 未開（後端回 403 → error notice）、控制項變動的 stale 警示、窄屏堆疊。

## 5. Data Mapping（現有 usePlatform / endpoints → UI）

所有資料皆來自既有 `usePlatform()`，**無新 endpoint**。

### 5.1 Scope / readiness / strip

| UI 元素 | 來源 |
| --- | --- |
| Repo-agent 卡片 | `resources.filter(r => r.type === 'git')` |
| Custom sources 多選 | `resources`（傳入 `ResourceScopePicker`） |
| Readiness 燈號 | `lib/lifecycle.ts` `readiness(resource, reviewByResource.get(id))` + `ReadinessBadge` |
| Freshness / 最近 index | `reviewItems[]`（`freshness_status` / `freshness_age_days` / `last_index_status`） |
| Uses | `usageItems[]`（`hit_count` / `query_count`） |
| Drift findings | `agent-card-summaries`（`summaries[].status !== 'healthy'`） |
| Runtime 預設 | `agent?.default_runtime ?? 'hermes'` |

### 5.2 Ask / preview

| UI 元素 | 來源 |
| --- | --- |
| 生成 context | POST `/workspaces/{w}/projects/{p}/agent-context` → `AgentContextResponse`（`client(...)`） |
| body | `{ query, runtime, resource_ids: <由 scope 映射>, top_k, max_chars: 22000, include_code_symbols: true }` |
| Preview 呈現 | `AgentContextPreview`（`result` / `resources`） — instruction / context / citations / symbols |
| scope 描述 | `describeScope(resources, ids)`（custom）/ 自訂字串（project / agent） |

### 5.3 Repo-agent brief / advanced（皆既有 endpoint）

| 動作 | endpoint（既有） | 來源頁 |
| --- | --- | --- |
| Repo-agent brief | GET `/workspaces/{w}/projects/{p}/repo-agents/{id}/brief` → `RepoAgentBrief` | repo-agents |
| Drift audit summaries（讀） | GET `.../agent-card-summaries` → `AgentCardSummaryList` | repo-agents |
| Drift audit run（dry-run） | POST `.../agent-card-summaries/run?dry_run=true` → `AgentCardSummaryList` | repo-agents |
| Patch proposal（opt-in） | POST `.../remote-code/generate_patch` → `PatchProposal` | repo-agents |
| PR approval record（opt-in） | POST `.../remote-code/open_pr` → `PrRequest` | repo-agents |

### 5.4 Provider / scope / 狀態

| UI | 來源 |
| --- | --- |
| Workspace/Project 識別 | `workspace` / `project`（名稱優先） |
| settings（w/p id 用於 endpoint path） | `settings.workspaceId` / `settings.projectId` |
| Loading / error / reload | `loading` / `error` / `reload` |

## 6. Design Decisions（建立在 PR1/PR2 tokens 上）

### 沿用（不重造）

- **Tokens**：直接用 `globals.css` 既有變數。不得新增 one-off hex。
- **Primitive**：用既有 `PageHeader`、`Card`、`SectionCard`、`Metric`、`Chip`、`StatusChip`、`EmptyState`、`Field`、`ReadinessBadge`，及既有 `AgentContextPreview`、`ResourceScopePicker`。
- **狀態語意**：用既有 `statusTone()` / `STATUS_TONES`；新增狀態字串若未涵蓋才補進 map（顯式對應，不可 `includes()` 猜）。
- **Readiness**：用 `lib/lifecycle.ts` 單一事實來源，**取代** `/repo-agents` 內嵌的第二份。
- **版面**：沿用 `.app-shell`、`.grid.two/three/four`、`.table-wrap`、`.health-strip`、`.repo-agent-grid`/`.repo-agent-card`、`.scope-pill`、`.code-block`、`@media`。

### PR3 新增（additive，於 `globals.css`）

- `.segmented` / `.segmented button`（+ `.active`）：scope mode 三選一切換（沿用 token，無裝飾動畫）。
- `.workbench-prompts`（suggested prompt grid，可直接複用 `.scope-pill`，必要時最小新增）。
- 不改既有 class 行為，避免 legacy 頁面 regression。

> 原則：能用既有 primitive / class 組合就不新增；不新增跨頁元件除非確有複用價值（本 PR 傾向直接在頁面內以既有 primitive 組合）。

### 視覺方向（延續 PR1/PR2）

- tufte-dataink（evidence-first：citations / symbols 表）＋ bloomberg-terminal（密集運維工作台）＋ restrained raycast（明確 primary action：Generate）。
- 避免：generic white SaaS、漸層、emoji icon、fake metric、裝飾動畫。
- Motion：僅 nav/hover、卡片選取高亮、Advanced 折疊的小 transition。
- A11y：semantic landmarks、focus 狀態、segmented 與卡片可鍵盤觸發、status chip 對比；窄屏 scope/ask/preview 皆可達。

## 7. Acceptance Criteria

PR3 僅在以下全部成立時可接受：

- [ ] `/workbench` 為單一 canonical Agent Workbench，同頁完成 選 scope → 確認 readiness → 採用建議問題或自行提問 → 檢視 cited context / symbols，無需跳頁。
- [ ] 三種 scope（Whole project / Repo sub-agent / Custom sources）共用同一 `agent-context` endpoint，對映正確的 `resource_ids`（`null` / 單一 / 多選）。
- [ ] 全程**不需閱讀或複製任何 UUID**：repo agent 以名稱卡片選、custom 以名稱多選；URL 不含 resource UUID。
- [ ] Readiness 一律來自 `lib/lifecycle.ts`（不再有 `/repo-agents` 內嵌第二份）。
- [ ] Suggested prompts：repo-agent scope 用 `repo-agents/{id}/brief` 的 `suggested_questions`（未載入時 fallback）；點 prompt 會帶入問題並生成。
- [ ] `AgentContextPreview` 顯示真實 instruction / context / citations / symbols；無生成結果時顯示誠實 empty state。
- [ ] 控制項（scope / question / runtime / topK）變動後，顯示「為舊控制項生成」的 stale 警示（沿用 `/ask` 守則）。
- [ ] `mode=agent` 時呈現選定 repo agent 的 operating brief / quality gates / invocation contract / safety boundary（來自真實 brief endpoint）。
- [ ] Advanced 區塊保留 drift audit（dry-run, read-only）與 opt-in patch/PR，**gating 文案與 endpoint 與 `/repo-agents` 等價**，預設折疊、預設 read-only。
- [ ] `/repo-agents`、`/ask` 轉址到 `/workbench`，舊連結（含 Command Center 內 link）不 404。
- [ ] AppShell nav 的 Workbench 指向 `/workbench`；移除重複的 Ask 入口；其他 nav 與頁面未被破壞。
- [ ] loading / 無 git resource / 無 resource / ask 失敗 / brief 載入失敗 / drift 未 run / patch gating 未開 / stale / 窄屏 等狀態皆已設計。
- [ ] 無 fake data / fake usage / placeholder metric；無新增大型相依。
- [ ] 無 backend 變更；`lib/api.ts`、`lib/platform-context.tsx`、`ResourceScopePicker.tsx`、`AgentContextPreview.tsx`、`lib/lifecycle.ts` 行為未變。
- [ ] `lint`（`tsc --noEmit`）與 `build`（`next build`）通過。

## 8. Verification Commands

由 repo root 執行（除非另註）。

```bash
# 1. 確認改動範圍乾淨，未碰禁區
git status --short
git diff --name-only origin/main...HEAD
# 預期僅出現：
#   apps/web/app/workbench/page.tsx
#   apps/web/app/repo-agents/page.tsx
#   apps/web/app/ask/page.tsx
#   apps/web/components/AppShell.tsx
#   apps/web/app/globals.css
#   docs/frontend-rebuild/PR3-workbench-spec.md

# 2. 靜態檢查
npm --prefix apps/web run lint
npm --prefix apps/web run build

# 3. 確認禁區未被改動（應無輸出）
git diff --name-only origin/main...HEAD -- apps/api packages migrations \
  apps/web/lib/api.ts apps/web/lib/platform-context.tsx apps/web/lib/lifecycle.ts \
  apps/web/components/ResourceScopePicker.tsx apps/web/components/AgentContextPreview.tsx
```

Browser smoke：

```bash
npm --prefix apps/web run dev -- --hostname 0.0.0.0 --port 13000
```

於瀏覽器確認：

- `/workbench` 桌面渲染：readiness strip + scope/ask 兩欄；無 console error。
- 切換 scope mode（project / agent / custom）→ 對應選取 UI 出現；repo-agent 卡片以名稱+readiness 呈現。
- 選一個 repo agent → brief 載入（operating brief / quality gates / invocation / safety boundary）。
- 採用一個 suggested prompt → 問題帶入並生成 → `AgentContextPreview` 顯示 citations / symbols。
- 自行改 question / runtime / topK → 出現 stale 警示；重新 generate 後消失。
- custom mode 多選 source → generate → context 反映多 source scope。
- 展開 Advanced → drift audit dry-run 可執行、顯示 summaries；patch/PR 表單 gating 文案保留（未開 policy 時動作回 403 error notice，不 crash）。
- 直接訪問 `/repo-agents`、`/ask` → 轉址到 `/workbench`，不 404。
- 其他既有路由 `/`、`/sources`、`/review`、`/evals`、`/agent-files`、`/config` 仍正常渲染；Command Center 內指向 `/repo-agents`、`/ask` 的 link 轉到 `/workbench`。
- 窄屏（mobile viewport）scope/ask/preview 堆疊可用。

## 9. Risks & Rollback

| Risk | Impact | Mitigation |
| --- | --- | --- |
| 單頁 `/workbench` 過大、難 review | review 負擔高 | 複用既有 `AgentContextPreview` / `ResourceScopePicker` / `lib/lifecycle.ts`；Advanced（drift + patch/PR）折疊隔離；scope/ask/brief 清楚分區 |
| 轉址後遺失 `/repo-agents` 的 patch/PR 與 drift | 功能倒退 | 兩者平移進 Workbench Advanced，endpoint 與 gating 文案等價；smoke 驗證 |
| readiness 兩套漂移 | 同 resource 兩頁不同狀態 | Workbench 一律用 `lib/lifecycle.ts`；移除 `/repo-agents`（轉址後不再有第二份） |
| 改到 `AgentContextPreview` / `ResourceScopePicker` 契約 | 破壞 `/evals`、`/sources` | 只複用既有 props，不改 signature；§8 diff guard 檢查 |
| 轉址破壞既有 deep link / Command Center link | 使用者 404 | 用 framework `redirect` 保留 `/repo-agents`、`/ask` 可達；smoke 驗證 |
| scope→`resource_ids` 映射錯誤 | 問錯範圍、citations 失真 | 三模式集中一處映射（project=null / agent=[id] / custom=ids）；generated-for/stale 守則避免拿舊 scope 證據審核 |
| patch/PR gating 未開時報錯 | 使用者誤以為壞掉 | 平移既有 gating 文案；403 以 error notice 呈現，不 crash；Advanced 預設折疊 |
| globals.css 新增 class 影響 legacy | 樣式跑版 | 僅 additive class、不改既有 class；smoke 多條 legacy route |

### Rollback

PR3 為 frontend-only，回滾簡單：

- Revert PR branch 或 merge commit 即可，無 DB migration、無 backend 相容性問題。
- `/workbench`、`/repo-agents` redirect、`/ask` redirect、`AppShell.tsx`、`globals.css` 共同構成一套 workbench 體驗，發現問題時應**整組一起 revert**，避免 nav 指向已移除頁面或 redirect 與 hub 不一致。
- 後端契約全程未變，回滾後既有 API 與 PR1/PR2 不受影響。
