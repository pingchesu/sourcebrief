# PR4 — SourceBrief Quality Gate Spec

> 延續 PR1（enterprise shell + Command Center + design primitives）、PR2（Sources lifecycle hub）、PR3（Agent Workbench）。本 PR **不動 backend**，僅把目前割裂的 `/review`（resource review / freshness）與 `/evals`（retrieval eval runs）收斂成單一 canonical **Quality** gate dashboard (`/quality`)。
> 對應 PR1 IA 中 **Assure quality** 群組（PR1 spec §4.2）的兩個入口。

## 1. Problem Statement / Product Goal

### 問題

PR1（Command Center）回答「agent 是否 ready、下一步去哪」；PR2（Sources）回答「每個 source 走到 lifecycle 哪一階段」；PR3（Workbench）回答「實際問 agent、看 cited 證據」。但「這個 agent 的 context **品質**夠不夠上線」這個企業真正在意的問題，目前散在兩頁、且都偏向 API demo：

1. **品質被切成兩個不相通的頁**：`/review`（Review Center）只看「每個 source 是否 current / approved / 有 drift reason」；`/evals`（Quality Evals）只看「retrieval golden questions 的 pass rate」。一個是 source-level 人工審核，一個是 system-level 自動量測，但兩者都是「agent context 品質」的證據，使用者卻得在兩頁拼湊全貌。
2. **沒有單一 quality gate 視角**：沒有任何一頁回答「現在可以放心讓 agent 上線嗎？有哪些 gate 還沒過？」企業評審需要的是 **gate 列表 + 各 gate 的 pass / warn / fail + 證據連結**，而非兩張各自為政的表。
3. **drift 證據缺席於 quality 敘事**：`agent-card-summaries`（drift audit findings）目前只藏在 Workbench Advanced，但它本質上是 source-level 品質訊號（過期 runbook、孤兒檔案、缺 entrypoint 等），應與 review / freshness 並列為品質 gate 的一部分。
4. **`/review` 仍是扁平 demo 表格**：一行一個 source，沒有彙總、沒有 attention 排序、沒有把 freshness / stale reason / drift / usage 串成「為何此 source 需要關注」的敘事；review 決策表單也與佐證脫節。
5. **`/evals` 把「跑 eval」當主角，把「證據」當配角**：頁面以 golden-question 編輯器為中心，但企業 reviewer 更需要「歷史 run 的趨勢、最近一次 gate 狀態、失敗原因」作為上線判準，跑新 eval 是次要動作。

### 產品目標

把 agent context 的**品質保證**收斂成單一 canonical **Quality gate dashboard**，回答企業使用者的核心問題：

- 現在整體 **quality gate 過了沒**？哪些 gate（source review / freshness / drift / retrieval eval / provider）是 pass、warn、fail？（gate-first，不需自己拼兩頁）
- **哪些 source 需要關注**、為什麼？（freshness / stale reason / drift finding / review 狀態 / 真實 usage，attention-first 排序，全程以**名稱**呈現，不貼 UUID）
- 我能否就地對一個 source **下審核決策**（approved / needs_update / stale / ignored）？（沿用 `/review` 既有 POST，但與佐證並列）
- 有沒有**自動量測證據**證明 retrieval 真的可用？（retrieval eval 歷史 run、最近 gate 狀態、pass rate、失敗原因；需要時可重跑）
- 這些品質訊號都來自**真實後端**嗎？（無 mock；沒資料就誠實 empty state）

**衡量標準**：使用者在單一 `/quality` 頁，不需閱讀或複製任何 UUID，即可（1）一眼看到整體 quality gate 狀態與未過的 gate；（2）看到 attention-first 的 source 品質佇列含 freshness / stale reason / drift / usage；（3）就地對一個 source 存審核決策；（4）檢視 retrieval eval 歷史證據並在需要時重跑；所有狀態與數字皆來自既有 API，無 fake data。

## 2. Non-Goals

PR4 **不**做以下事情：

- 不修改 backend：`apps/api/**`、`packages/**`、`migrations/**`、worker / retrieval / auth / scopes 一律不動。
- 不新增後端 endpoint。Quality 只用既有 endpoint：`resource-review`、`resource-usage`、`agent-card-summaries`(+`/run?dry_run=true`)、`resources/{id}/review`、`retrieval-evals`(GET list / POST run)、`retrieval-evals/{id}`、`retrieval-profiles`、`provider-health`。
- 不修改資料抓取模型 `apps/web/lib/platform-context.tsx` 與 `apps/web/lib/api.ts`（除非遇 typing-only / compile blocker，且須在 PR 說明）。Quality 所需的 `resources` / `reviewItems` / `usageItems` / `provider` / `agent` / `client` / `settings` / `selectedResource` / `reload` 皆已存在。
- 不改 `lib/lifecycle.ts` 的 readiness / freshness 契約；Quality **複用** `readiness`、`freshnessLabel`、`isActive`、`isIndexFailed`、`isVisible`（取代 `/review` 內聯邏輯）。
- 不改 `ui.tsx` 既有 primitive 的 signature；以組合既有 export（`PageHeader`、`SectionCard`、`Metric`、`Chip`、`StatusChip`、`AttentionRow`、`EmptyState`、`Field`、`ReadinessBadge`）達成。
- 不改 `components/ResourceScopePicker.tsx`、`components/AgentContextPreview.tsx` 行為契約（本 PR 不需要 ResourceScopePicker；retrieval eval 的呈現不依賴 AgentContextPreview）。
- 不重建其他頁面：`/`（Command Center）、`/sources`、`/workbench`、`/agent-files`、`/agent-profile`、`/config`、`/admin`、`/users`、`/maintenance`。
- 不新增 client-side 輪詢 / 即時刷新；沿用既有 `reload()` + 區段 `useEffect` 手動載入模型。
- 不擴張 drift audit 的後端契約或安全模型；`agent-card-summaries/run` 一律 `dry_run=true`（read-only `review:read`），acknowledge / 寫入動作不在本 PR 範圍。
- 不新增大型 UI library、Tailwind、charting、animation 等相依。
- 不做 fake data / fake metric / placeholder pass rate；沒資料就 empty state。

## 3. PR4 Exact Scope & Files

### 設計取向（先講清楚路由決策）

採 **single canonical quality dashboard + 安全轉址**（與 PR2 `/sources`、PR3 `/workbench` 決策一致）：

- 新增 `/quality` 作為唯一 canonical Quality gate dashboard（gate 彙總 + attention 佇列 + source review 佇列與就地決策 + retrieval eval 證據與重跑 + drift findings）。
- 所有 source 以**名稱**呈現與選取，**URL 不帶 resource UUID**，符合 no-UUID-first。
- `/review` 與 `/evals` 改為輕量 `redirect('/quality')`，舊連結（含 Command Center 內既有 `/review` link）不 404。
- AppShell nav 的「Assure quality」群組由兩個入口（Review queue → `/review`、Retrieval evals → `/evals`）收斂為單一 **Quality** 入口指向 `/quality`。

> 為什麼用 `/quality` 新路由而非原地擇一改：兩頁要被一個 gate 視角吸收，新路由讓 nav 命名與 IA（Assure quality）一致，並讓 `/review`、`/evals` 安全轉址、降低 regression 面。

### 要修改 / 新增的檔案（實作階段）

| 檔案 | 動作 | 說明 |
| --- | --- | --- |
| `apps/web/app/quality/page.tsx` | **新增** | Canonical Quality dashboard：gate strip（真實計數）+ quality gates 列（pass/warn/fail + 證據）+ attention 佇列 + source review 佇列（attention-first，名稱優先）與就地審核決策表單（POST `resources/{id}/review`）+ retrieval eval 證據（history / load run / summary / 每題結果 / 重跑）+ drift findings（`agent-card-summaries` 讀 + dry-run 重掃，折疊）。 |
| `apps/web/app/review/page.tsx` | **重建為轉址** | `redirect('/quality')`。原 review 佇列 + 決策表單平移進 `/quality`。 |
| `apps/web/app/evals/page.tsx` | **重建為轉址** | `redirect('/quality')`。原 eval 編輯 / 重跑 / 歷史 / 每題結果平移進 `/quality`。 |
| `apps/web/components/AppShell.tsx` | **修改 nav** | 「Assure quality」群組收斂為單一 `Quality` 入口指向 `/quality`；其餘 nav 不動。 |
| `apps/web/app/globals.css` | **（可能）新增 additive class** | 僅在既有 class 無法表達 quality-gate 列時，新增少量沿用既有 token 的 class；不改既有 class 行為。預設目標是 **零新增**（用 `AttentionRow` + `.grid` + `.health-strip` 組合）。 |

> `ui.tsx`、`lib/lifecycle.ts`、`lib/api.ts`、`lib/platform-context.tsx`、`ResourceScopePicker.tsx`、`AgentContextPreview.tsx` 預設**不改**。若 lint/build 出現 typing-only / compile blocker 才最小幅度調整，並在 PR 說明。

### 不可碰（禁區）

- `apps/api/**`、`packages/**`、`migrations/**`
- `apps/web/lib/api.ts`、`apps/web/lib/platform-context.tsx`（資料模型不變）
- `apps/web/lib/lifecycle.ts`（readiness / freshness 契約；只複用不改）
- `apps/web/components/ui.tsx`（primitive signature）、`ResourceScopePicker.tsx`、`AgentContextPreview.tsx`
- 其他頁面：`/`、`/sources`、`/workbench`、`/agent-files`、`/agent-profile`、`/config`、`/admin`、`/users`、`/maintenance`、`/repo-agents`、`/ask`、`/resources`、`/import`、`/git-env`

### 一個 PR 的合理性

實質新代碼集中在一支頁面（`/quality`）；其餘是兩支轉址與一處 nav 微調。沒有 backend、沒有資料模型變更，複用既有 `usePlatform()`、`lib/lifecycle.ts`、`ui.tsx` primitive，review 面可控。

## 4. Target Quality IA & UX

### 4.1 路由與結構

```
/quality                            ← 唯一 canonical Quality gate dashboard
  ├─ Header                         ← PageHeader：eyebrow "Quality" + title + 動作 (Run drift scan / Reload)
  ├─ Provider degraded notice       ← provider.status !== 'ok' 時（沿用 PR1/PR2 文案）
  ├─ Quality gate strip             ← 真實計數 metric：Active sources / Approved / Stale / Drift findings / Last eval
  ├─ Quality gates                  ← gate 列（每列：tone + 名稱 + 判定理由 + 狀態 chip + 證據連結/動作）
  │     ├─ Source review gate       ← active retrieval-enabled 是否皆 approved
  │     ├─ Freshness gate           ← 是否有 stale source（freshness !== fresh）
  │     ├─ Drift gate               ← agent-card-summaries 是否有 status !== healthy
  │     ├─ Retrieval eval gate      ← 最近一次 eval run 的 status / pass_rate
  │     └─ Provider gate            ← provider.status / embedding 健康
  ├─ Attention queue                ← attention-first：failed index → stale → not-indexed → unreviewed → drift（真實訊號）
  ├─ Source review (兩欄)
  │   ├─ Review queue (左)          ← attention-first 表：名稱 + readiness + freshness + index + review 狀態 + uses + stale reasons
  │   └─ Selected review (右)       ← 就地審核決策表單（decision / note）→ POST resources/{id}/review
  ├─ Retrieval evidence
  │   ├─ Eval gate summary          ← 最近 / 載入的 run：status / profile / pass rate / latency / 失敗原因
  │   ├─ Eval history 表            ← retrieval-evals list（load run）
  │   ├─ 每題結果表                 ← 載入 run 的 per-question pass/fail / citations / symbols / latency
  │   └─ Run new eval（折疊）        ← seed golden questions + profile 選擇 + 重跑（沿用 /evals 行為）
  └─ Drift findings（折疊）          ← agent-card-summaries 讀 + dry-run 重掃，per-source severity / summary
```

桌面 source review 為兩欄（queue | decision），窄屏堆疊，沿用既有 `.grid.two` 與 `@media` 行為。

### 4.2 Quality gates（gate-first 敘事，全部由真實訊號 derive）

| Gate | pass 條件 | warn / fail 條件 | 證據 / 動作 |
| --- | --- | --- | --- |
| **Source review** | 所有 active 且 retrieval-enabled 的 source `review_status === 'approved'` | 有未 approved → warn（顯示數量） | 捲動到 Review queue |
| **Freshness** | 無 stale（所有 review item `freshness_status === 'fresh'` 或無 freshness 資料） | 有 stale → warn（顯示數量 + 範例 stale reason） | Review queue |
| **Drift** | `agent-card-summaries` 全 `status === 'healthy'` 或無 summary | 有 `status !== 'healthy'` → warn / `severity` 高 → risk | 展開 Drift findings |
| **Retrieval eval** | 最近一次 run `status === 'passed'`（或 pass_rate = 1） | 無 run → neutral「not run」；run failed / pass_rate < 1 → warn/risk | Retrieval evidence |
| **Provider** | `provider.status === 'ok'` | 非 ok → warn（顯示 provider/model/namespace） | `/config` |
| **Index health** | 無 index failed（`isIndexFailed(last_index_status)` 皆 false） | 有 failed → risk（顯示數量） | `/sources` 或 `/maintenance` |

> gate tone 一律用既有 `Tone`（ready / warn / risk / neutral）與 `AttentionRow` 呈現；neutral 用於「尚無資料」不可誤導成 pass。

### 4.3 各區塊行為

**Header**
- `PageHeader` eyebrow `Quality`、title「Quality gate」、description 說明這是 agent context 上線前的品質判準。
- Actions：`Run drift scan`（POST `agent-card-summaries/run?dry_run=true`，read-only）、`Reload`（`reload()`）。

**Quality gate strip**（沿用 `.health-strip`）
- 真實計數：Active sources、Approved、Stale、Drift findings、Last eval（status）。0 用 neutral，不誤導。

**Quality gates**（沿用 `AttentionRow` 列）
- 依 §4.2 derive；每列顯示 tone、gate 名稱、判定理由（真實數字）、狀態 chip、跳轉/展開動作。

**Attention queue**（沿用 Command Center 的 `AttentionRow` 模式）
- attention-first：index failed → stale → not indexed → unreviewed → drift finding。每筆顯示 source 名稱、原因、usage meta、就地動作（選取該 source 進審核 / 展開 drift）。無項目時誠實顯示「Nothing needs attention」。

**Source review（兩欄）**
- 左：Review queue 表，attention-first 排序（沿用 `/sources` 的 `attentionRank`）。欄位：Source（名稱 + type）、Readiness（`ReadinessBadge` 用 `lib/lifecycle.ts`）、Freshness（`freshnessLabel`）、Index（`last_index_status`）、Review（`review_status`）、Uses（`usageItems`）、Reasons（`stale_reasons`）。點列以**名稱**選取（`selectResource`），不需 UUID。
- 右：Selected review 決策表單（沿用 `/review` POST `resources/{id}/review`，body `{ review_status, review_note, stale_after_days: 30 }`），decision 下拉（approved / needs_update / stale / ignored / unreviewed）、note，存檔後 `reload()`。同時顯示該 source 的 freshness / stale reasons / usage 佐證並列。

**Retrieval evidence**
- Eval gate summary：最近一次（或使用者載入的）run → status / profile / pass rate / avg latency / 失敗原因（沿用 `/evals` summary 呈現）。
- Eval history 表：`retrieval-evals?limit=20` list，每列 status / profile / created / questions / pass rate / provider / scope + Load。
- 每題結果表：載入 run（`retrieval-evals/{id}`）後顯示 per-question pass/fail / citations / symbols / latency / 失敗原因。
- Run new eval（折疊，預設關閉）：seed golden questions（依選定 indexed resource）、profile 選擇（`retrieval-profiles`）、POST `retrieval-evals` 重跑（沿用 `/evals` 行為與 body）。重跑後刷新 history。

**Drift findings（折疊，預設關閉）**
- 讀 `agent-card-summaries`（latest_only）顯示 per-source severity / status / summary / findings 數。
- `Run drift scan` 用 `agent-card-summaries/run?dry_run=true`（read-only），沿用 Workbench Advanced 的 read-only 文案，不寫入。

### 4.4 狀態覆蓋（必須全部設計）

loading、未簽入 / 無 workspace（沿用 context 空狀態）、無 source（review queue empty）、無 review item、無 drift summary、無 eval run（gate neutral「not run」）、provider degraded（沿用警示）、審核存檔中（disabled +「Saving…」）、審核失敗（error notice）、eval 重跑中 / 失敗、drift scan 中 / 失敗（403 gating → error notice，不 crash）、窄屏堆疊。

## 5. Data Mapping（現有 usePlatform / endpoints → UI）

所有資料皆來自既有 `usePlatform()` 或既有 endpoint，**無新 endpoint**。

### 5.1 Gate strip / gates / attention

| UI 元素 | 來源 |
| --- | --- |
| Active sources / approved / stale 計數 | `resources` + `reviewItems`（`lib/lifecycle.ts` `isActive` / `isIndexFailed`，`freshness_status`、`review_status`） |
| Readiness 燈號 | `lib/lifecycle.ts` `readiness(resource, reviewByResource.get(id))` + `ReadinessBadge` |
| Freshness / stale reason / last index | `reviewItems[]`（`freshness_status` / `freshness_age_days` / `last_index_status` / `stale_reasons`） |
| Uses | `usageItems[]`（`hit_count` / `query_count`） |
| Drift findings 計數 | GET `agent-card-summaries` → `AgentCardSummaryList`（`summaries[].status !== 'healthy'`） |
| Last eval gate | GET `retrieval-evals?limit=20` → `runs[0]`（`status` / `pass_rate`） |
| Provider gate | `provider`（`status` / `embedding.provider` / `model` / `namespace`） |

### 5.2 Source review 決策（沿用 `/review`）

| 動作 | endpoint（既有） |
| --- | --- |
| Review 佇列 | `reviewItems`（context 已載 `resource-review`） |
| 存審核決策 | POST `/workspaces/{w}/projects/{p}/resources/{id}/review`，body `{ review_status, review_note, stale_after_days: 30 }` → `reload()` |
| 選取 source（名稱） | `selectResource(resource.id)` / `selectedResource` |

### 5.3 Retrieval evidence（沿用 `/evals`）

| 動作 | endpoint（既有） |
| --- | --- |
| Eval 歷史 | GET `/workspaces/{w}/projects/{p}/retrieval-evals?limit=20` → `RetrievalEvalRunList` |
| 載入單一 run | GET `.../retrieval-evals/{run_id}` → `RetrievalEvalResponse` |
| Profiles | GET `.../retrieval-profiles` → `RetrievalProfilesResponse` |
| 重跑 eval | POST `.../retrieval-evals`，body `{ runtime: 'hermes', profile, max_chars: 10000, questions }` → `RetrievalEvalResponse` |
| seed questions | `indexedResources`（`resources.filter(current_snapshot_id && retrieval_enabled && status==='active')`） |

### 5.4 Drift findings

| 動作 | endpoint（既有） |
| --- | --- |
| 讀 findings | GET `.../agent-card-summaries?latest_only=true` → `AgentCardSummaryList` |
| dry-run 重掃 | POST `.../agent-card-summaries/run?dry_run=true` → `AgentCardSummaryList`（read-only） |

### 5.5 狀態 / 識別

| UI | 來源 |
| --- | --- |
| Workspace / Project 識別 | `workspace` / `project`（名稱優先） |
| endpoint path 的 w/p id | `settings.workspaceId` / `settings.projectId` |
| Loading / error / reload | `loading` / `error` / `reload` |

## 6. Design Decisions（建立在 PR1–PR3 tokens 上）

### 沿用（不重造）

- **Tokens**：直接用 `globals.css` 既有變數，不新增 one-off hex。
- **Primitive**：`PageHeader`、`Card`、`SectionCard`、`Metric`、`Chip`、`StatusChip`、`AttentionRow`、`EmptyState`、`Field`、`ReadinessBadge`（皆既有 export）。
- **狀態語意**：用既有 `statusTone()` / `STATUS_TONES`；retrieval eval 的 `passed/failed`、drift 的 `healthy/degraded/...` 已被 `STATUS_TONES` 覆蓋。若出現未涵蓋字串才顯式補進 map（不可 `includes()` 猜）。
- **Lifecycle**：`readiness` / `freshnessLabel` / `isActive` / `isIndexFailed` / `isVisible` 一律取自 `lib/lifecycle.ts`（取代 `/review` 內聯邏輯），與 `/sources` 共用單一事實來源。
- **版面**：`.app-shell`、`.grid.two/three/four`、`.health-strip`、`.attention-list` / `AttentionRow`、`.table-wrap`、`.advanced-section` / `.advanced-toggle`、`.notice`、`.code-block`、`@media`。

### PR4 新增（盡量為零）

- 目標 **零新增 class**：quality-gate 列用既有 `AttentionRow`；strip 用 `.health-strip`；折疊區用既有 `.advanced-section` / `.advanced-toggle`。
- 僅當既有 class 無法表達時，才於 `globals.css` 新增少量沿用 token 的 additive class，且不改既有 class 行為（避免 legacy route regression）。

### 視覺方向（延續 PR1–PR3）

- tufte-dataink（evidence-first：review 佇列 / eval 每題結果 / drift findings 表）＋ bloomberg-terminal（密集 gate 運維面）＋ restrained raycast（明確 primary：存審核 / 重跑 eval / drift scan）。
- 避免：generic white SaaS、漸層、emoji icon、fake metric、裝飾動畫。
- Motion：僅 nav/hover、列選取高亮、折疊區小 transition。
- A11y：semantic landmarks、focus 狀態、列可鍵盤觸發、status chip 對比；窄屏 gate / queue / decision / evidence 皆可達。

## 7. Acceptance Criteria

PR4 僅在以下全部成立時可接受：

- [ ] `/quality` 為單一 canonical Quality gate dashboard，同頁完成：看整體 gate 狀態 → 看 attention-first source 品質佇列 → 就地存審核決策 → 檢視 retrieval eval 證據（必要時重跑）→ 檢視 drift findings，無需跳頁。
- [ ] Quality gates 列（source review / freshness / drift / retrieval eval / provider / index health）皆由**真實訊號** derive，tone 正確（neutral 不誤判為 pass）。
- [ ] 全程**不需閱讀或複製任何 UUID**：source 以名稱呈現與選取；URL 不含 resource UUID。
- [ ] Readiness / freshness 一律來自 `lib/lifecycle.ts`（不再有 `/review` 內聯版本）。
- [ ] Source review 佇列 attention-first，含 freshness / stale reasons / index / review 狀態 / 真實 usage；可就地存審核決策（POST `resources/{id}/review`）並 `reload()`。
- [ ] Retrieval evidence 顯示 eval 歷史、可載入單一 run 看 per-question 結果、可重跑（沿用 `/evals` 既有 body 與 profiles），無 run 時 gate 顯示 neutral「not run」。
- [ ] Drift findings 來自 `agent-card-summaries`（讀 + dry-run 重掃，read-only `review:read`）；gating 文案保留，403 以 error notice 呈現不 crash。
- [ ] `/review`、`/evals` 轉址到 `/quality`，舊連結（含 Command Center 內 `/review` link）不 404。
- [ ] AppShell nav 「Assure quality」收斂為單一 `Quality` 入口指向 `/quality`；其他 nav 與頁面未被破壞。
- [ ] loading / 未簽入 / 無 source / 無 review item / 無 drift / 無 eval run / provider degraded / 存檔中 / 重跑中 / scan 失敗 / 窄屏 等狀態皆已設計。
- [ ] 無 fake data / fake metric / placeholder pass rate；無新增大型相依。
- [ ] 無 backend 變更；`lib/api.ts`、`lib/platform-context.tsx`、`lib/lifecycle.ts`、`ui.tsx`、`ResourceScopePicker.tsx`、`AgentContextPreview.tsx` 行為未變。
- [ ] `lint`（`tsc --noEmit`）與 `build`（`next build`）通過。

## 8. Verification Commands

由 repo root 執行（除非另註）。

```bash
# 1. 確認改動範圍乾淨，未碰禁區
git status --short
git diff --name-only origin/main...HEAD
# 預期僅出現：
#   apps/web/app/quality/page.tsx
#   apps/web/app/review/page.tsx
#   apps/web/app/evals/page.tsx
#   apps/web/components/AppShell.tsx
#   docs/frontend-rebuild/PR4-quality-spec.md
#   (若有 additive CSS) apps/web/app/globals.css

# 2. 靜態檢查
npm --prefix apps/web run lint
npm --prefix apps/web run build

# 3. 確認禁區未被改動（應無輸出）
git diff --name-only origin/main...HEAD -- apps/api packages migrations \
  apps/web/lib/api.ts apps/web/lib/platform-context.tsx apps/web/lib/lifecycle.ts \
  apps/web/components/ui.tsx apps/web/components/ResourceScopePicker.tsx \
  apps/web/components/AgentContextPreview.tsx
```

Browser smoke：

```bash
npm --prefix apps/web run dev -- --hostname 0.0.0.0 --port 13000
```

於瀏覽器確認：

- `/quality` 桌面渲染：gate strip + quality gates 列 + attention 佇列 + source review 兩欄 + retrieval evidence + drift findings；無 console error。
- Quality gates 反映真實狀態（無 eval run 時 retrieval gate 為 neutral「not run」，非 pass）。
- 點 review 佇列一列（名稱）→ 右側決策表單帶入該 source → 改 decision/note → 存檔成功並刷新。
- Retrieval evidence：history 載入、Load 一筆 run → per-question 結果出現；展開 Run new eval → seed → 重跑 → history 更新。
- 展開 Drift findings → 顯示 summaries；`Run drift scan` dry-run 可執行（未開 policy 時 403 以 error notice 呈現不 crash）。
- 直接訪問 `/review`、`/evals` → 轉址到 `/quality`，不 404。
- 其他既有路由 `/`、`/sources`、`/workbench`、`/agent-files`、`/config` 仍正常渲染；Command Center 內指向 `/review` 的 link 轉到 `/quality`。
- 窄屏（mobile viewport）gate / queue / decision / evidence 堆疊可用。

## 9. Risks & Rollback

| Risk | Impact | Mitigation |
| --- | --- | --- |
| 單頁 `/quality` 過大、難 review | review 負擔高 | 複用既有 primitive / `lib/lifecycle.ts`；retrieval eval 重跑與 drift scan 折疊隔離；gate / queue / evidence 清楚分區 |
| 轉址後遺失 `/review` 決策或 `/evals` 重跑 | 功能倒退 | 兩者完整平移進 `/quality`（同 endpoint / 同 body）；smoke 驗證 |
| readiness / freshness 兩套漂移 | 同 source 兩頁不同狀態 | Quality 一律用 `lib/lifecycle.ts`；移除 `/review` 內聯版本（轉址後不再有第二份） |
| gate 把 neutral 誤判為 pass | 假性「可上線」 | gate 明確區分 neutral（無資料 / not run）與 pass；§4.2 條件表為準 |
| drift scan / patch gating 未開時報錯 | 使用者誤以為壞掉 | `dry_run=true` read-only；403 以 error notice 呈現不 crash；Drift findings 預設折疊 |
| 改到 `ui.tsx` / lifecycle / context 契約 | 破壞其他頁 | 只複用既有 export，不改 signature；§8 diff guard 檢查 |
| 轉址破壞既有 deep link / Command Center link | 使用者 404 | 用 framework `redirect` 保留 `/review`、`/evals` 可達；smoke 驗證 |
| globals.css 新增 class 影響 legacy | 樣式跑版 | 目標零新增；必要時僅 additive、不改既有 class；smoke 多條 legacy route |

### Rollback

PR4 為 frontend-only，回滾簡單：

- Revert PR branch 或 merge commit 即可，無 DB migration、無 backend 相容性問題。
- `/quality`、`/review` redirect、`/evals` redirect、`AppShell.tsx`（、`globals.css`）共同構成一套 quality 體驗，發現問題時應**整組一起 revert**，避免 nav 指向已移除入口或 redirect 與 hub 不一致。
- 後端契約全程未變，回滾後既有 API 與 PR1–PR3 不受影響。
