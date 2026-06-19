# PR2 — ContextSmith Sources Lifecycle Spec

> 延續 PR1（enterprise shell + Command Center + design primitives）。本 PR 不動 backend，僅重建 source lifecycle 前端體驗。
> 對應 PR1 IA 中的 **Sources** 主入口（PR1 spec §4.2）。

## 1. Problem Statement / Product Goal

### 問題

PR1 已把首頁 (`/`) 重建成 Command Center，能回答「agent 是否 ready、哪些 source stale/failed、下一步去哪」。但點進 source 相關頁面後，使用者重新掉回「API demo」體驗：

1. **頁面以後端動詞命名、彼此割裂**：`/resources`、`/import`、`/git-env`、`/maintenance` 是四個獨立頁，使用者必須自己理解「先 import、再到 resources 看狀態、再去 git-env 設定、再去 maintenance reindex」的隱含流程。沒有一條可被發現的 source lifecycle。
2. **狀態語彙分散且不可見**：source 的健康度其實散落在多個欄位與多支 endpoint —— `resource.status`、`review_status`、`retrieval_enabled`、`current_snapshot_id`、`reviewItem.freshness_status` / `stale_reasons`、最近一次 `IndexRun.status`。目前沒有任何一頁把「connected → indexed → reviewed → retrieval-ready」這條 pipeline 一次呈現。`/repo-agents` 雖然有一段 `readiness()` 邏輯（`active → retrieval-off → not-indexed → needs-review → ready`），卻沒有在 source 管理頁複用。
3. **仍是 UUID-first**：`/import` 成功後直接吐 `resource_id` / `snapshot_id`；`/git-env`、`/maintenance` 用 short id 當主要識別；evidence（snapshots / index runs / graph）要靠 `selectedResource` 但選取入口不明顯。使用者被迫複製 UUID 才能往下走。
4. **evidence 與 action 脫節**：「看到某個 source stale」與「對它 reindex / 調整 git env / review」是在不同頁完成，使用者無法在看到問題的當下就處理。

### 產品目標

把 source 體驗收斂成一個**可被發現的 source lifecycle 主控台**，回答企業使用者真正的問題：

- 我連了哪些 source？分別是 git / url / document？
- 每個 source 現在走到 lifecycle 哪一階段（connected / indexed / reviewed / serving context）？
- 哪些 stale、哪些 index failed、哪些還沒 retrieval-ready、哪些需要 review？
- 選一個 source，我能看到它的 evidence（snapshots、index runs、knowledge graph、實際被生成的 context），而不是 raw JSON。
- 看到問題時能**就地**觸發既有的維運動作（refresh / reindex、調整 git env、標記 review），不需離開頁面、不需貼 UUID。
- 連新 source 是一個被引導的動作，而不是填一張暴露內部欄位的表單。

**衡量標準**：使用者全程不需閱讀或複製任何 UUID，就能完成「connect → 觀察 readiness → inspect evidence → 觸發維運」整條路徑；所有數字與狀態都來自真實 API，無 mock。

## 2. Non-Goals

PR2 **不**做以下事情（明確劃線，避免 scope 膨脹）：

- 不修改 backend：`apps/api/**`、`packages/**`、`migrations/**`、worker / retrieval / auth 一律不動。
- 不修改資料抓取模型 `apps/web/lib/platform-context.tsx` 與 `apps/web/lib/api.ts`，除非遇到 typing-only blocker（且須在 PR 說明）。本 PR 所需的 `selectResource` / `snapshots` / `indexRuns` / `graph` 皆已存在。
- 不新增後端 endpoint。所有 lifecycle 狀態都是**用現有欄位 derive**，不要求後端新增 status 欄位。
- 不重建 Command Center (`/`)、Workbench (`/repo-agents`, `/ask`)、Quality (`/review`, `/evals`)、Ship (`/agent-files`, `/agent-profile`)。這些屬於後續 PR。
- 不改 `/maintenance` 的**專案層級**動作（scheduled refresh dry-run/run、agent-files regenerate）的後端契約；PR2 只會把**單一 source 的 reindex**動作搬進 source detail，專案層級維運留在原處或輕量對齊。
- 不改 `ResourceScopePicker.tsx` 行為契約（被 `/ask`、`/evals` 使用），最多只做視覺對齊。
- 不新增大型 UI library、Tailwind、charting、animation、drag-drop 等相依。
- 不做 fake data、fake usage、fake freshness、placeholder metrics。沒有資料就誠實顯示 empty state。
- 不做 source 的批次操作（bulk reindex / bulk delete）與刪除 source 的破壞性流程（除非後端已支援且 trivially safe；預設不做）。
- 不引入 client-side 輪詢/即時刷新機制；沿用 PR1 的 `reload()` 手動刷新模型。

## 3. PR2 Exact Scope & Files

### 設計取向（先講清楚路由決策）

採 **single canonical hub + master-detail** 模式，並用 in-page 選取（非 URL 帶 UUID）：

- 新增 `/sources` 作為唯一的 source lifecycle 主控台（list + detail + connect 入口）。
- 選取 source 用既有的 `selectResource(resourceId)`（更新 context state），**URL 不帶 resource UUID**，符合 no-UUID-first。
- 既有 `/resources`、`/import`、`/git-env` 在 PR2 可改為輕量轉址到 `/sources`，但如果實作成本/QA 風險過高，允許先保留頁面並在 AppShell 主導流量到 `/sources`；不可讓舊頁成為主入口。
- `/maintenance` 的**專案層級**動作保留；單 source reindex 改由 `/sources` detail 內就地提供。

> 為什麼用 `/sources` 新路由而非原地改 `/resources`：PR1 IA（§4.2）已把主入口命名為 Sources；新路由讓 nav 命名與 IA 一致，且能讓舊路由安全轉址、降低 regression 面。

### 要修改 / 新增的檔案（實作階段）

| 檔案 | 動作 | 說明 |
| --- | --- | --- |
| `apps/web/app/sources/page.tsx` | **新增** | Source lifecycle 主控台：master list（lifecycle 欄位）+ detail（evidence + 就地維運）+ Connect 入口。整合原 `/resources` evidence、`/import` connect、`/git-env` 進階設定、單 source reindex。 |
| `apps/web/app/import/page.tsx` | **重建為轉址** | 改為 `redirect('/sources')`（Next.js `redirect`）或保留為 `/sources` 的 connect deep-link。Connect 表單邏輯搬進 `/sources`。 |
| `apps/web/app/resources/page.tsx` | **重建為轉址** | `redirect('/sources')`。 |
| `apps/web/app/git-env/page.tsx` | **重建為轉址** | `redirect('/sources')`；git env 設定搬進 source detail 的 Advanced 區塊。 |
| `apps/web/components/AppShell.tsx` | **修改 nav** | 「Build context」群組：把 Resources / Connect source 收斂為單一 **Sources** (`/sources`)；把 Git environment 從 Operations 移除或標記為 deprecated 並轉址。其餘 nav 不動。 |
| `apps/web/components/ui.tsx` | **新增 primitive（additive）** | 加入 lifecycle 呈現用 primitive（見 §6），保留所有既有 export 不破壞 legacy 頁面。 |
| `apps/web/lib/lifecycle.ts` | **新增（helper-only）** | 純函式：從 `Resource` + `ReviewItem` + 最近 `IndexRun` derive `readiness` / `freshnessLabel` / lifecycle stage。單一事實來源，供 `/sources` 與未來頁複用。不含 React、不打 API。 |
| `apps/web/app/globals.css` | **新增 class（additive）** | lifecycle pipeline / detail drawer / advanced section 所需的少量 class，沿用 PR1 tokens；不改既有 class 行為。 |

### 不可碰（禁區）

- `apps/api/**`、`packages/**`、`migrations/**`
- `apps/web/lib/api.ts`、`apps/web/lib/platform-context.tsx`（資料模型不變）
- `apps/web/components/ResourceScopePicker.tsx`（行為契約）
- 其他頁面：`/`、`/ask`、`/repo-agents`、`/review`、`/evals`、`/agent-files`、`/agent-profile`、`/config`、`/admin`

### 一個 PR 的合理性

實質新代碼集中在一支頁面（`/sources`）＋一支 helper（`lifecycle.ts`）＋ additive primitive。其餘是轉址與 nav 微調。沒有 backend、沒有資料模型變更，review 面可控。

## 4. Target Sources IA & UX

### 4.1 路由與結構

```
/sources                     ← 唯一 hub
  ├─ Header                  ← PageHeader：標題 + 主要動作 (Connect source / Reload)
  ├─ Lifecycle summary strip ← 各 lifecycle 階段的 source 計數（真實 derive）
  ├─ Sources list (master)   ← 每列一個 source，顯示 lifecycle 狀態欄位，可點選
  ├─ Source detail (detail)  ← 選取後右側顯示 evidence + 就地維運 + Advanced
  └─ Connect panel           ← 從 header 動作開啟的 connect 表單（git/url/markdown/upload）
```

桌面為兩欄（list | detail），窄屏堆疊（list 在上、detail 在下），沿用 PR1 `.grid.two` 與 `@media` 行為。

### 4.2 Lifecycle 模型（產品語彙）

把分散欄位收斂成一條使用者看得懂的 pipeline，五個階段：

1. **Connected** — source 已建立且 `status === 'active'`（非 archived/deleted）。
2. **Indexed** — 有 `current_snapshot_id` 且最近一次 index run 成功。
3. **Reviewed** — `review_status` 為 `approved`（非 `unreviewed` / `needs_update` / `stale` / `ignored`）。
4. **Retrieval-ready** — `retrieval_enabled === true` 且已 indexed。
5. **Serving / Fresh** — 上述皆滿足且 `freshness_status === 'fresh'`（在 `stale_after_days` 內）。

**Readiness（單一綜合燈號）** 複用並抽出 `/repo-agents` 的既有邏輯到 `lib/lifecycle.ts`：

```
inactive       ← status !== 'active'
retrieval-off  ← !retrieval_enabled
not-indexed    ← !current_snapshot_id
needs-review   ← reviewItem.freshness_status && !== 'fresh'  (含 stale / stale_reasons)
ready          ← 以上皆通過
```

對應 PR1 tone：`ready→ready`、`needs-review/retrieval-off→warn`、`not-indexed→warn`、`inactive→neutral`、index failed→`risk`。

### 4.3 各區塊行為

**Header**
- `PageHeader` eyebrow `Sources`、title「Connected sources and lifecycle」。
- Actions：`Connect source`（primary，開 Connect panel）、`Reload`（呼叫 `reload()`）。

**Lifecycle summary strip**（沿用 `.health-strip` 風格）
- 顯示真實計數：Total active、Retrieval-ready、Needs review、Not indexed、Index failed、Stale。
- 計數為 0 時顯示 0（不隱藏），但 0 risk 用 neutral tone 表達，不誤導。

**Sources list（master）**
- 每列欄位：
  - **Name**（人類可讀；type 以 chip 呈現 git/url/markdown/upload；UUID 不出現在主視覺）。
  - **Readiness**（綜合燈號 chip，來自 §4.2）。
  - **Freshness**（`fresh` / `stale` + `freshness_age_days` 天數；缺資料顯示「—」）。
  - **Index**（最近一次 index run 的 status + chunks，或「not indexed」）。
  - **Review**（`review_status`）。
  - **Uses**（來自 `usageItems` 的 `hit_count` 或 `query_count`；無則「—」）。
- 排序：預設「需要注意者優先」——index failed / stale / not-indexed / needs-review 排前，其餘依 name。
- 點列觸發 `selectResource(id)`，右側載入 detail。選取列高亮。
- Empty state：完全沒有 source 時，顯示引導文案 + `Connect source` CTA（不顯示假列）。

**Source detail（detail，選取後）**
- **Lifecycle stages**：以 §4.2 五階段的 pipeline 視覺呈現目前走到哪（達成/未達成/失敗）。
- **Identity & evidence**：name、type、URI（mono）、current snapshot、last refresh 時間；UUID 僅以次要 mono 小字呈現於需要處（如 snapshot id），非操作前提。
- **Snapshots**（來自 `snapshots`）：table —— status、version（`version_kind`=hash 顯示）、indexed 時間、is_current 標記。
- **Index runs**（來自 `indexRuns`，取最近 8–10 筆）：table —— status、trigger、chunks、symbols、finished 時間；failed 顯示 `error_message`。
- **Knowledge graph**（來自 `graph`）：node_count / edge_count metric；無則 empty state。
- **Generated context preview**：沿用 `/resources` 既有的 `agent-context` POST 預覽（顯示真實生成的 context / citations / symbols），讓使用者看到「這個 source 實際貢獻什麼 context」。
- **就地維運動作**（皆為現有 endpoint）：
  - `Refresh / Reindex`（git → 「Update repo and reindex」、其餘 → 「Reindex」），POST `.../resources/{id}/refresh`。
  - 動作完成後呼叫 `selectResource(id)` + `reload()` 重新載入 evidence 與列狀態。
- **Advanced（git source 才顯示，collapsible）**：搬入原 `/git-env` 表單 —— branch、auth token env var（僅存環境變數名稱、不存 secret）、clone timeout、max file/repo bytes、max repo files、update frequency；PATCH `.../resources/{id}/git-env`。

**Connect panel**
- 重建原 `/import` 表單，但以「引導連接」呈現：
  - 先選 source 類型（git / url / markdown / upload），UI 依類型只顯示相關欄位。
  - 友善預設與說明文案；不把 `resource_id` 當成成功的主結果，改以「Source connected — now indexing」這類 lifecycle 語彙呈現，並把新 source 帶入 list（成功後 `reload()` 並可自動 `selectResource` 新 id）。
  - 「Create index immediately」選項保留（對應建立後 POST refresh）。
  - 成功/失敗都有明確狀態；token 僅以 env var 名稱引用的提示保留。

### 4.4 狀態覆蓋（必須全部設計）

loading、empty（無 source）、未選取 source（detail 提示「Select a source」）、provider degraded（沿用 PR1 警示）、index failed（risk）、stale（warn）、API error（`error` 顯示 + Reload）、窄屏堆疊。

## 5. Data Mapping（現有 usePlatform / endpoints → UI）

所有資料皆來自既有 `usePlatform()`，**無新 endpoint**。

### 5.1 List / summary

| UI 元素 | 來源欄位 / endpoint |
| --- | --- |
| Source 列表 | `resources: Resource[]`（已由 `reload()` 載入） |
| 過濾掉已刪除 | `!resource.deleted_at`；archived 用 `archived_at` 區分 |
| Connection 狀態 | `resource.status`（`active` / 其他） |
| Type chip | `resource.type`（`git`/`url`/`markdown`/`upload`） |
| Retrieval-ready | `resource.retrieval_enabled` && `resource.current_snapshot_id` |
| Review 狀態 | `resource.review_status`（`approved`/`needs_update`/`stale`/`ignored`/`unreviewed`） |
| Freshness | `reviewItems[].freshness_status`、`freshness_age_days`、`stale_reasons`（依 `resource.id` 比對） |
| 最近 index 狀態 | `reviewItems[].last_index_status` / `last_index_finished_at`（list 層級即可，免逐一打 detail endpoint） |
| Uses | `usageItems[].hit_count` / `query_count` / `context_packet_count`（依 `resource_id` 比對） |
| Next refresh | `resource.next_refresh_at`、`last_refresh_finished_at` |

> List 的 freshness / index 狀態優先用已批次載入的 `reviewItems`（`/resource-review`），避免為每列各打一次 detail endpoint。

### 5.2 Detail evidence（選取後）

| UI 元素 | 來源 |
| --- | --- |
| 觸發載入 | `selectResource(resourceId)` → 內部打 `/resources/{id}/snapshots`、`/index-runs`、`/graph` |
| Snapshots | `snapshots: Snapshot[]`（`version`/`version_kind`/`status`/`indexed_at`/`is_current`） |
| Index runs | `indexRuns: IndexRun[]`（`status`/`trigger`/`chunks_created`/`symbols_created`/`finished_at`/`error_message`） |
| Knowledge graph | `graph: GraphRead`（`node_count`/`edge_count`） |
| Context preview | POST `/workspaces/{w}/projects/{p}/agent-context`（`client(...)`），body 沿用 `/resources` 既有參數（runtime=agent.default_runtime、`resource_ids=[selectedId]`、top_k/max_chars/include_code_symbols） |
| 選取的 resource 物件 | `selectedResource`、`selectedResourceId` |

### 5.3 維運 / 連接動作

| 動作 | endpoint（既有） | 來源頁 |
| --- | --- | --- |
| Reindex / refresh 單一 source | POST `/workspaces/{w}/projects/{p}/resources/{id}/refresh` → `IndexRun` | resources / maintenance / import |
| Connect 新 source | POST `/workspaces/{w}/projects/{p}/resources` → `Resource` | import |
| 建立後立即 index | POST `.../resources/{id}/refresh` | import |
| Git env 讀取 | GET `/workspaces/{w}/projects/{p}/git-env` → `GitResourceEnv[]` | git-env |
| Git env 更新 | PATCH `/workspaces/{w}/projects/{p}/resources/{id}/git-env` → `GitResourceEnv` | git-env |

> Review 動作（POST `.../resources/{id}/review`）屬於 Quality PR 範疇；PR2 detail 只**顯示** review 狀態並可深連到 `/review`，不在此實作 review 寫入（避免與 Quality PR 重疊）。

### 5.4 Provider / scope

| UI | 來源 |
| --- | --- |
| Provider degraded 警示 | `provider: ProviderHealth`（`status`、`embedding.*`） |
| Workspace/Project 識別 | `workspace` / `project`（名稱優先，UUID demote） |
| Loading / error / reload | `loading` / `error` / `reload` |

### 5.5 Derived state（放 `lib/lifecycle.ts`，純函式）

```
readiness(resource, reviewItem)            → 'inactive'|'retrieval-off'|'not-indexed'|'needs-review'|'ready'
lifecycleStages(resource, reviewItem, lastIndexStatus) → 各階段 reached/failed boolean
freshnessLabel(reviewItem)                 → { label, ageDays, tone }
readinessTone(readiness, lastIndexStatus)  → PR1 Tone
isVisible(resource)                        → !deleted_at
isActive(resource)                         → status === 'active' && !deleted_at && !archived_at
```

readiness 須與 `/repo-agents` 現有邏輯一致（抽共用，避免漂移）。

## 6. Design Decisions（建立在 PR1 tokens 上）

### 沿用 PR1（不重造）

- **Tokens**：直接用 `globals.css` 既有變數（`--bg`/`--surface`/`--surface-strong`/`--ink`/`--muted`/`--line`/`--ready`/`--warn`/`--risk`/`--accent` 及其 `-soft`、`--radius*`、`--shadow*`、`--font-sans`/`--font-mono`）。不得新增 one-off hex；需要新顏色須先升級為 token。
- **Primitive**：用既有 `PageHeader`、`SectionCard`、`Card`、`Metric`、`Chip`、`StatusChip`、`ActionLink`、`AttentionRow`、`EmptyState`、`Field`。
- **狀態語意**：用既有 `statusTone()` / `STATUS_TONES`；新增狀態字串若未涵蓋，補進 `STATUS_TONES` map（顯式對應，**不可**用 `includes()` 字串猜測）。
- **版面**：沿用 `.app-shell`、`.grid.two/three/four`、`.table-wrap`、`@media` breakpoints。

### PR2 新增 primitive（additive，於 `ui.tsx`）

- `LifecyclePipeline`（或 `LifecycleStages`）：把 §4.2 五階段以小型 stepper/pipeline 呈現，每階段 tone 來自 helper；純呈現、狀態由 props 傳入。
- `ReadinessBadge`：包 `Chip`，輸入 readiness 字串輸出對應 tone 與文字。
- `SourceLifecycleRow`（可選）：list 列的封裝；若邏輯簡單可直接在頁面內組合 `Chip`/`StatusChip`，避免過度抽象。

> 原則：能用既有 primitive 組合就不新增元件；新增者必須是「跨頁可複用的呈現」而非頁面專屬邏輯。

### globals.css 新增（additive class，沿用 token）

- `.lifecycle-pipeline` / `.lifecycle-stage.is-{reached|pending|failed}`：階段視覺。
- `.source-detail` / `.advanced-section`（collapsible）：detail 區塊排版。
- `.connect-panel`：connect 表單容器（沿用 `.card` 風格，不做 modal 動畫）。
- 不改既有 class 行為，避免 legacy 頁面 regression。

### 視覺方向（延續 PR1）

- 維持 tufte-dataink（evidence-first table）＋ bloomberg-terminal（密集運維面板）＋ restrained raycast（明確 primary action）。
- 避免：generic white SaaS、漸層、emoji icon、fake metric、大圓角卡片堆。
- Motion：僅限 nav/hover、列選取高亮、collapsible 展開的小 transition；無裝飾動畫。
- A11y：semantic landmarks、focus 狀態、status chip 對比、可鍵盤觸發的選取與動作；窄屏 list/detail/connect 皆可達。

## 7. Acceptance Criteria

PR2 僅在以下全部成立時可接受：

- [ ] `/sources` 為單一 source lifecycle 主控台，同頁完成 list → 選取 → evidence → 就地維運，無需跳頁。
- [ ] 全程**不需閱讀或複製任何 UUID** 即可完成 connect → 觀察 readiness → inspect evidence → reindex；URL 不含 resource UUID。
- [ ] List 每個 source 顯示真實 lifecycle 狀態：connection、readiness、freshness、最近 index 結果、review、uses，皆 derive 自既有欄位。
- [ ] Lifecycle 五階段（connected/indexed/reviewed/retrieval-ready/serving）在 detail 清楚呈現目前進度與失敗。
- [ ] Readiness 邏輯與 `/repo-agents` 現有 `readiness()` 一致（抽到 `lib/lifecycle.ts` 共用，無第二套漂移）。
- [ ] Detail evidence（snapshots / index runs / graph / generated context preview）均來自真實 API；無資料時顯示誠實 empty state，非假列。
- [ ] 就地維運（refresh/reindex）成功後 list 與 detail 狀態同步更新（`selectResource` + `reload`）。
- [ ] Git source 的 Advanced 設定（branch / auth env var / timeouts / size limits / frequency）可在 detail 內編輯並 PATCH 成功；secret 僅以 env var 名稱引用、不落地。
- [ ] Connect 流程依 source 類型只顯示相關欄位，成功以 lifecycle 語彙呈現並把新 source 帶入 list。
- [ ] `/resources`、`/import`、`/git-env` 轉址到 `/sources`，舊連結不 404。
- [ ] AppShell nav 的 Sources 入口指向 `/sources`；移除/降級重複入口；其他 nav 與頁面未被破壞。
- [ ] loading / empty / 未選取 / provider degraded / index failed / stale / error / 窄屏 等狀態皆已設計。
- [ ] 無 fake data、fake usage、placeholder metric；無新增大型相依。
- [ ] 無 backend 變更；`lib/api.ts`、`lib/platform-context.tsx`、`ResourceScopePicker.tsx` 行為未變。
- [ ] `lint` 與 `build` 通過。

## 8. Verification Commands

由 repo root 執行（除非另註）。

```bash
# 1. 確認改動範圍乾淨，未碰禁區
git status --short
git diff --name-only origin/main...HEAD
# 預期僅出現：
#   apps/web/app/sources/page.tsx
#   apps/web/app/import/page.tsx
#   apps/web/app/resources/page.tsx
#   apps/web/app/git-env/page.tsx
#   apps/web/components/AppShell.tsx
#   apps/web/components/ui.tsx
#   apps/web/lib/lifecycle.ts
#   apps/web/app/globals.css
#   docs/frontend-rebuild/PR2-sources-lifecycle-spec.md

# 2. 靜態檢查
npm --prefix apps/web run lint
npm --prefix apps/web run build

# 3. 確認禁區未被改動（應無輸出）
git diff --name-only origin/main...HEAD -- apps/api packages migrations \
  apps/web/lib/api.ts apps/web/lib/platform-context.tsx \
  apps/web/components/ResourceScopePicker.tsx
```

Browser smoke：

```bash
npm --prefix apps/web run dev -- --hostname 0.0.0.0 --port 13000
```

於瀏覽器確認：

- `/sources` 桌面渲染：list + detail 兩欄、lifecycle summary strip 顯示真實計數。
- 點選一個 source → detail 載入 snapshots / index runs / graph，無 console error。
- 對選取 source 觸發 Reindex → 動作回報結果且 list/detail 狀態更新。
- git source → Advanced 區塊可開啟並儲存（PATCH 200）。
- `Connect source` → 依類型切換欄位、成功後新 source 出現在 list。
- `/sources` 窄屏（mobile viewport）堆疊可用、動作可達。
- 直接訪問 `/resources`、`/import`、`/git-env` → 轉址到 `/sources`，不 404。
- 無 source 帳號（或空 project）→ 顯示 empty state 與 Connect CTA，無假資料。
- 其他既有路由 `/`、`/repo-agents`、`/review`、`/agent-files`、`/config` 仍正常渲染。
- Console 無 runtime error；`reload` 在 session/provider 異常時回報清楚狀態。

## 9. Risks & Rollback

| Risk | Impact | Mitigation |
| --- | --- | --- |
| 單頁 `/sources` 過大、難 review | review 負擔高 | evidence 與 connect 抽成頁內子區塊；derive 邏輯抽 `lib/lifecycle.ts`；維持 list/detail 清楚分界 |
| Readiness 邏輯與 `/repo-agents` 漂移 | 同一 source 在兩頁顯示不同狀態 | 抽共用 helper，`/repo-agents` 後續可改用同 helper（本 PR 不強制改它，但 helper 必須等價） |
| List 為每列逐一打 detail endpoint | 請求風暴 / 慢 | list 只用已批次載入的 `reviewItems`/`usageItems`；detail endpoint 僅在選取時觸發 |
| 轉址破壞既有 deep link / 書籤 | 使用者 404 | 用 framework redirect 保留 `/resources`、`/import`、`/git-env` 可達；smoke 驗證 |
| 把 git-env / maintenance 動作搬移後遺漏專案層級維運 | 找不到 scheduled refresh / regenerate | `/maintenance` 專案層級動作維持原處；nav 保留入口；只搬「單 source reindex」 |
| globals.css 新增 class 影響 legacy | 既有頁面樣式跑版 | 僅 additive class、不改既有 class；smoke 多條 legacy route |
| Connect 表單欄位/`source_config` 結構與後端不符 | create 失敗 | 完全沿用既有 `/import` 的 body 結構，不改欄位語意 |
| 誤觸禁區（api/context/api.ts） | 破壞資料層或越界 | §8 diff guard 明確列出禁區檢查 |

### Rollback

PR2 為 frontend-only，回滾簡單：

- Revert PR branch 或 merge commit 即可，無 DB migration、無 backend 部署相容性問題。
- 因 `/sources`、redirect 頁、`AppShell.tsx`、`ui.tsx`、`lifecycle.ts`、`globals.css` 共同構成一套 source 體驗，發現問題時應**整組一起 revert**，而非部分回滾，避免 nav 指向已移除頁面或 redirect 與 hub 不一致。
- 後端契約全程未變，回滾後既有 API 與 PR1 Command Center 不受影響。
