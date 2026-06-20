# PR5 — SourceBrief Ship / Admin Cleanup & Final IA Polish Spec

> 延續 PR1（enterprise shell + Command Center + design primitives）、PR2（Sources lifecycle hub `/sources`）、PR3（Agent Workbench `/workbench`）、PR4（Quality gate `/quality`）。本 PR **不動 backend**，是 frontend rebuild 的**收尾**：把產品最後的 rough edges 收乾淨，讓整套 console 從第一頁到最後一頁都像「完成品」而非「API demo 拼盤」。
> PR5 不新增大功能，重點是：**(a) Command Center 深連結全部指向 canonical 路由**（不再二次轉址）、**(b) Ship（agent pack handoff）surface 文案/順序收斂**、**(c) Operations / Admin / Session 群組去除開發備註式文案、命名一致**、**(d) 確認 AppShell nav 與全站不暴露 endpoint 名稱 / UUID-first workflow**。

## 1. Problem Statement / Product Goal

### 問題

PR1–PR4 已把核心 IA 收斂成五個 canonical hub（`/`、`/sources`、`/workbench`、`/quality`、`/agent-files`+`/agent-profile`），舊路由（`/review`、`/ask`、`/evals`、`/resources`、`/repo-agents`、`/import`、`/git-env`）都已改為安全 `redirect`。但 rebuild 尾端仍留下幾處「看得出是半成品」的痕跡：

1. **Command Center 深連結仍指向 legacy redirect 路由**：`app/page.tsx` 內多處連到 `/import`、`/review`、`/resources`、`/ask`、`/repo-agents`（attention queue、nextAction、SectionCard action、ActionLink 皆有）。這些路由雖然會 `redirect` 到 canonical hub，但造成 **二次轉址（double-hop）**、瀏覽器網址列短暫出現已淘汰路徑、且這些連結的**標籤**（「Review center」「Ask & citations」「Open Workbench」指向 `/repo-agents`）仍用舊命名，與 nav 的 canonical 命名（Quality / Workbench / Sources）不一致。這是 PR5 唯一的功能性修正，其餘為文案/呈現收斂。

2. **Ship surface（`/agent-files`）以 legacy 為敘事主角**：`/agent-files` 是產品最終的「交付 / handoff」面（下載 Skill Pack、各 runtime adapter、MCP config），但頁面標題與第一段文案是「Generate **legacy** agent files and the new remote-only Skill Pack…」，把 legacy 放在句首；版面上「Legacy generated files」與 canonical Skill Pack 視覺權重相當。對企業使用者而言，這頁應**先講「如何把 agent 交付出去」**（Skill Pack 為主），legacy 檔案降為相容性備註。

3. **Operations / Admin 群組殘留開發備註式文案**：`/admin` 描述寫「…This is no longer a blank placeholder.」、`/users` 與 `/config` 文案多次以「UUID / debug metadata / API operators」自我說明，`/config` header 動作叫「Reset **demo** defaults」。這些都是 rebuild 過程的 dev note，讀起來像「給開發者看的施工說明」而非完成品 console 文案。內容（真實資料、名稱優先）已正確，缺的是**語氣收尾**。

4. **缺少「全站不暴露 endpoint 名稱 / UUID-first」的最終把關**：rebuild 橫跨四個 PR，需要一次最終 sweep 確認 nav、頁面標題、主要 CTA 不以 endpoint 路徑或 UUID 為主要識別。（既有頁面大致已符合；PR5 負責確認並修掉殘留。）

### 產品目標

把 frontend rebuild **收尾成一個一致、完成的 console**，使用者在任何頁面都不會看到：指向已淘汰路由的連結、把 legacy 當主角的交付面、開發備註式文案、或被迫以 endpoint / UUID 思考的 workflow。

具體而言，PR5 完成後：

- Command Center 的每一個連結都直接指向 **canonical 路由**（`/sources`、`/workbench`、`/quality`、`/agent-profile`、`/agent-files`、`/config`、`/login`、`/maintenance`），無任何指向 redirect 路由的 deep-link；連結**標籤**與 nav 命名一致。
- `/agent-files` 作為 **Ship / handoff** 面，敘事**先 Skill Pack（canonical 交付）**、legacy 檔案明確標示為相容性保留。
- `/admin`、`/users`、`/config`、`/login` 文案為**完成品語氣**：說明「這頁能做什麼、給誰用」，不含「no longer a placeholder」「demo」「給 API operator 看 UUID」這類施工備註。
- AppShell nav 與全站主要識別**以產品名詞（名稱）為主**，UUID 僅作為折疊 / 次要 debug metadata 存在（維持既有設計，PR5 確認不退步）。

**衡量標準**：(1) `grep` Command Center 找不到任何指向 `/import|/review|/resources|/ask|/repo-agents|/evals|/git-env` 的 link；(2) `/agent-files` 第一屏先呈現 Skill Pack 交付，legacy 區塊標示為相容性保留；(3) `/admin`、`/users`、`/config` 無「placeholder / demo / 給 operator 看 UUID」式 dev note；(4) 全站 nav 與頁面標題不以 endpoint 路徑命名；(5) `lint` + `build` 綠燈；(6) 全程無 backend / 資料模型 / fake data 變更。

## 2. Non-Goals

PR5 **不**做以下事情：

- 不修改 backend：`apps/api/**`、`packages/**`、`migrations/**`、worker / retrieval / auth / scopes 一律不動。
- 不新增任何後端 endpoint，也不改既有 endpoint 的呼叫契約（body / method / path）。
- 不修改資料抓取模型 `apps/web/lib/platform-context.tsx` 與 `apps/web/lib/api.ts`（除非遇 typing-only / compile blocker，且須在 PR 說明）。
- 不改 `lib/lifecycle.ts` 的 readiness / freshness 契約。
- 不改 `ui.tsx` 既有 primitive 的 signature 與行為；如需新呈現，以**組合既有 export**達成。
- 不**重建**任何頁面。`/agent-files` 為**就地重排序 + 文案調整**（保留所有既有 state / fetch / 互動），非重寫。`/admin`、`/users`、`/config`、`/login` 僅**文案層級**調整（PageHeader description、區塊標題、按鈕 label）。
- 不新增 / 移除路由。所有既有 redirect（`/review`、`/ask`、`/evals`、`/resources`、`/repo-agents`、`/import`、`/git-env`）**維持原樣可達**，不刪除（保護既有外部書籤 / 深連結）。
- 不改 AppShell nav 的**結構**（群組與項目已於 PR1–PR4 定稿）；PR5 僅在發現暴露 endpoint / UUID 時才微調文案，預期 **零結構變更**。
- 不改 retrieval / drift / patch / PR 等行為與安全模型。
- 不新增大型 UI library、Tailwind、charting、animation 等相依（no new deps）。
- 不做 fake data / fake metric / placeholder；沒資料就誠實 empty state。
- 不 over-build：已成熟的頁面（`/sources`、`/workbench`、`/quality`、`/maintenance`、`/agent-profile`）**不動**，僅在它們指向 legacy 路由時才修連結（經查皆已 canonical，預期不需改）。

## 3. PR5 Exact Scope & Files

### 設計取向

PR5 是**收尾型 PR**：以最小、可逐項驗證的改動把 rebuild 收乾淨，不引入新概念。所有改動都落在「連結指向」「文案語氣」「區塊順序」三類，皆為低風險、易 review、易 rollback。

### 要修改的檔案（實作階段）

| 檔案 | 動作 | 說明 |
| --- | --- | --- |
| `apps/web/app/page.tsx` | **修改連結與標籤** | Command Center 所有深連結改指 canonical：`/import`→`/sources`、`/review`→`/quality`、`/resources`→`/sources`、`/ask`→`/workbench`、`/repo-agents`→`/workbench`。同步把標籤改為 canonical 命名（如「Review center」→「Quality gate」、「Ask & citations」/「Ask a question」→「Open Workbench」/「Try a query」、「Open Workbench」指向 `/workbench`）。**不改**頁面結構、derived state、readiness/attention 邏輯。 |
| `apps/web/app/agent-files/page.tsx` | **重排序 + 文案** | PageHeader 改為「Ship the agent pack」敘事（先 Skill Pack）；Skill Pack 區塊維持在 legacy 之前；「Legacy generated files」明確標示為相容性保留（muted 說明）。**保留**所有既有 state、fetch（`agent-files`、`agent-pack/*`、`agent-pack.zip`、`remote-code/*`）、下載 / copy / grep / read 互動。 |
| `apps/web/app/admin/page.tsx` | **文案** | 移除「This is no longer a blank placeholder.」等 dev note，改為完成品 description。資料 / 表格不動。 |
| `apps/web/app/users/page.tsx` | **文案** | PageHeader description 收斂為完成品語氣（保留「名稱優先」精神，去除施工口吻）。資料 / 表格不動。 |
| `apps/web/app/config/page.tsx` | **文案** | header description 收斂；「Reset demo defaults」→「Reset to defaults」。表單 / 邏輯不動。 |
| `apps/web/app/login/page.tsx` | **（可能）文案** | 僅在文案讀起來像 dev note 時做最小收斂（保留 dev-auth / bearer 的必要技術說明，因 session 頁本質需要）。預期極小或不改。 |
| `apps/web/components/AppShell.tsx` | **（僅必要時）文案** | 經查 nav 結構已定稿且不暴露 endpoint / UUID-first。預期 **不改**；若最終 sweep 發現殘留才做文案微調。 |
| `apps/web/app/globals.css` | **（可能）additive only** | 預期 **零新增**（重排序用既有 `.grid` / `.card` / `Card` 達成）。僅在重排序需要既有 class 無法表達時，新增少量沿用 token 的 additive class，不改既有 class 行為。 |
| `docs/frontend-rebuild/PR5-ship-admin-cleanup-spec.md` | **新增** | 本規格。 |

### 不可碰（禁區）

- `apps/api/**`、`packages/**`、`migrations/**`
- `apps/web/lib/api.ts`、`apps/web/lib/platform-context.tsx`（資料模型不變）
- `apps/web/lib/lifecycle.ts`（readiness / freshness 契約）
- `apps/web/components/ui.tsx`（primitive signature / 行為）、`ResourceScopePicker.tsx`、`AgentContextPreview.tsx`
- 既有 redirect 頁面：`/review`、`/ask`、`/evals`、`/resources`、`/repo-agents`、`/import`、`/git-env`（維持可達，不刪、不改）
- 成熟頁面：`/sources`、`/workbench`、`/quality`、`/maintenance`、`/agent-profile`（除非指向 legacy 路由的連結；經查無）

### 一個 PR 的合理性

PR5 沒有新代碼路徑、沒有新 fetch、沒有資料模型變更；改動是分散但**同質**的收尾（連結指向、文案、區塊順序），每一處都可獨立目視驗證，且全部 frontend-only。集中為一個收尾 PR 比拆成多個瑣碎 PR 更易 review 與 rollback。

## 4. Target IA / UX

### 4.1 最終 canonical IA（PR5 確認的定稿狀態）

```
AppShell nav（PR1–PR4 定稿，PR5 不改結構）
  Command Center            /
  Build context
    Sources                 /sources
    Workbench               /workbench
  Assure quality
    Quality                 /quality
  Ship agent pack
    Agent files             /agent-files
    Project agent           /agent-profile
  Operations [secondary]
    Maintenance             /maintenance
    Configuration           /config
    Users & tokens          /users
    Audit & admin           /admin
    Session                 /login

legacy redirects（維持可達，nav 不顯示）
  /review /evals → /quality
  /ask /repo-agents → /workbench
  /resources /import /git-env → /sources
```

### 4.2 Command Center 連結 canonical 化（唯一功能性修正）

`app/page.tsx` 內所有 link 的 href 與 label 對照（僅改指向與標籤，不改觸發條件 / 結構）：

| 位置 | 既有 href → 新 href | 既有 label → 新 label |
| --- | --- | --- |
| attention：no active source | `/import` → `/sources` | 「Connect」（保留，語意正確） |
| attention：review risk 列 | `/review` → `/quality` | 「Review」→「Open quality」 |
| nextAction：connect a source | `/import` → `/sources` | 「Connect a source」（保留） |
| nextAction：attention 時 | `/review` → `/quality` | 「Open review queue」→「Open quality gate」 |
| nextAction：ready 時 | `/repo-agents` → `/workbench` | 「Open Workbench」（保留，已正確命名） |
| Source coverage action | `/resources` → `/sources` | 「All sources」（保留） |
| Attention queue action | `/review` → `/quality` | 「Review center」→「Quality gate」 |
| Source map action | `/resources` → `/sources` | 「Open sources」（保留） |
| Retrieval usage action | `/ask` → `/workbench` | 「Ask & citations」→「Open Workbench」 |
| Retrieval usage ActionLink | `/ask` → `/workbench` | 「Ask a question」→「Try a query in Workbench」 |
| Ship ActionLink | `/agent-files`（已 canonical，保留） | 「Ship agent pack」（保留） |

> 原則：href 一律指向 canonical hub；label 與 nav 命名（Sources / Workbench / Quality）對齊；不引入頁面結構或 derived state 改動，readiness / attention 計算邏輯完全不動。

### 4.3 Ship surface（`/agent-files`）敘事收斂

維持頁面所有功能與 fetch，僅調整**敘事順序與文案**，使其讀起來是「交付面」：

- **PageHeader**：eyebrow 維持 `Agent Files`；title 改為以「Ship」為主的敘事（如「Ship the agent pack」），description 先講「下載可安裝的 Skill Pack（Hermes/Codex/Claude adapter + MCP config）把這個 project agent 交付到 runtime」，legacy 檔案降為「相容性保留」一句。
- **區塊順序（維持既有，明確化權重）**：Skill Pack 安裝/下載 → 遠端 follow-up inspection（smoke）→ **Legacy generated files**（標題或 muted 說明明示「保留給舊整合，新交付請用上方 Skill Pack」）。
- **不改**：`AGENT_PACK_ENDPOINTS`、`load` / `loadPack` / `downloadPackZip` / `loadResources` / `runGrepExample` / `readFirstMatch`、所有 button 行為與 endpoint。capability 名稱（`grep_code`、`read_file` 等）保留，因它們是**交付給 runtime 的工具名**、屬於 handoff 內容（非 console 內部 endpoint），列出有助使用者了解 pack 能力。

### 4.4 Operations / Admin / Session 文案收斂

| 頁面 | 既有文案問題 | 收斂方向（完成品語氣） |
| --- | --- | --- |
| `/admin` | description 含「This is no longer a blank placeholder.」 | 去除施工備註；description 直接說明：provider health、index 狀態、freshness risk、audit events 的運維觀測面。表格與資料不動。 |
| `/users` | description 以 UUID 自我說明 | 收斂為：workspace 成員與 token 權限可視性（誰能 review / 設定 / 查詢 agent），名稱優先。去除施工口吻；表內既有 short-id debug 保留。 |
| `/config` | 「Reset **demo** defaults」按鈕、description 提「給 API operators 看 UUID」 | 按鈕→「Reset to defaults」；description 收斂為「以名稱設定 workspace/project 與 token；ID 僅為次要 debug metadata」。表單 / Debug IDs 折疊不動。 |
| `/login` | 文案偏技術（dev-auth header / bearer） | session 頁本質需要這些技術說明，**保留必要部分**；僅在語氣像 dev note 時最小收斂。預期極小或不改。 |

### 4.5 全站「不暴露 endpoint / 不 UUID-first」最終 sweep

PR5 收尾時確認（並修掉殘留）：

- nav 標籤、PageHeader title 不以 endpoint 路徑命名（現況已符合）。
- 主要識別與選取以**名稱**為主；UUID 僅出現在折疊 `<details>`（如 config「Debug IDs」）、`code` 次要行、或表格內 `short()` debug 列——此為既有設計，PR5 **維持**不退步，不主動移除（移除會傷及 API operator 的 debug 能力，且非本 PR 目標）。
- agent-profile / agent-files 顯示的 `agent_context_endpoint`、`mcp_endpoint`、capability 名稱屬於**交付 / handoff 內容**（operator 需要），保留。

### 4.6 狀態覆蓋（沿用既有，PR5 不新增狀態）

所有頁面既有的 loading / 未簽入 / 無資料 empty state / error notice / 窄屏堆疊行為**完全沿用**；PR5 不引入新狀態分支。

## 5. Data Mapping（現有 usePlatform / endpoints → UI）

PR5 **不新增、不改變**任何資料來源；以下為受影響頁面沿用的既有對應，列出以證明改動不觸及資料層。

### 5.1 Command Center（`app/page.tsx`）

| UI 元素 | 來源（既有，不變） |
| --- | --- |
| readiness / attention / nextAction | `usePlatform()`：`agent` / `provider` / `workspace` / `project` / `settings` / `resources` / `reviewItems` / `usageItems` / `loading` / `error` |
| 連結 href | **靜態字串**（PR5 僅改字串值：legacy → canonical），非資料 |

> PR5 對 page.tsx 的改動只觸及 link 的 href / label 字面值，不觸及任何 `usePlatform()` 欄位或 derived `useMemo`。

### 5.2 Ship surface（`/agent-files`）

| 動作 | endpoint（既有，不變） |
| --- | --- |
| legacy 檔案列 / regenerate | GET/POST `/workspaces/{w}/projects/{p}/agent-files[/regenerate]` |
| Skill Pack artifacts | GET `/workspaces/{w}/projects/{p}/agent-pack/{endpoint}` |
| Skill Pack zip | GET `/workspaces/{w}/projects/{p}/agent-pack.zip` |
| 遠端 grep / read | POST `/workspaces/{w}/projects/{p}/remote-code/{grep_code,read_file}` |
| git resources（grep 對象） | GET `/workspaces/{w}/projects/{p}/resources` |

### 5.3 Operations / Admin / Session

| 頁面 | 來源（既有，不變） |
| --- | --- |
| `/admin` | `usePlatform()`：`auditEvents` / `provider` / `resources` / `reviewItems` / `indexRuns` |
| `/users` | `usePlatform()`：`members` / `tokens` / `workspace` |
| `/config` | `usePlatform()`：`workspaces` / `projects` / `workspace` / `project` / `resources` / `tokens` + POST/DELETE api-tokens、POST resources |
| `/login` | `usePlatform()`：`settings` / `setSettings` / `workspace` / `project` / `provider` / `reload` |

> 以上頁面 PR5 僅改文案 / 按鈕 label，資料抓取與寫入動作完全不動。

## 6. Design Decisions（建立在 PR1–PR4 tokens 上）

### 沿用（不重造）

- **Tokens**：直接用 `globals.css` 既有變數，不新增 one-off hex。
- **Primitive**：`PageHeader`、`Card`、`SectionCard`、`Metric`、`Chip`、`StatusChip`、`ActionLink`、`AttentionRow`、`EmptyState`、`Field`（皆既有 export）。Ship surface 重排序以組合既有 `Card` / `.grid` 達成。
- **狀態語意**：沿用既有 `statusTone()` / `STATUS_TONES`。
- **版面**：`.app-shell`、`.page`、`.grid.two/three/four`、`.health-strip`、`.attention-list`、`.table-wrap`、`.notice`、`.code-block`、`@media`。

### PR5 新增（盡量為零）

- 目標 **零新增 class**：連結改字串、文案改字串、Ship 區塊以既有 `Card` 排序——皆不需新 CSS。
- 僅當 Ship 重排序需既有 class 無法表達時，才於 `globals.css` 新增少量沿用 token 的 additive class，且不改既有 class 行為。

### 視覺方向（延續 PR1–PR4）

- tufte-dataink（evidence-first）＋ bloomberg-terminal（密集運維面）＋ restrained raycast（明確 primary CTA）。
- 避免：generic white SaaS、漸層、emoji icon、fake metric、裝飾動畫、施工備註式文案。
- A11y：semantic landmarks、focus 狀態、status chip 對比；改文案不得破壞既有 landmark 結構。

## 7. Acceptance Criteria

PR5 僅在以下全部成立時可接受：

- [ ] Command Center（`app/page.tsx`）**無任何**指向 `/import`、`/review`、`/resources`、`/ask`、`/repo-agents`、`/evals`、`/git-env` 的 link；所有深連結指向 canonical 路由（`/sources`、`/workbench`、`/quality`、`/agent-profile`、`/agent-files`、`/config`、`/login`、`/maintenance`）。
- [ ] Command Center 連結**標籤**與 nav canonical 命名一致（不再有「Review center」「Ask & citations」指向舊概念的命名）。
- [ ] Command Center 的 readiness / attention / nextAction **觸發條件與 derived state 未改變**（僅 href / label 字面值變動）。
- [ ] `/agent-files` 作為 Ship / handoff 面：敘事**先 Skill Pack**，legacy 檔案明確標示為相容性保留；**所有既有 fetch / 下載 / copy / grep / read 行為與 endpoint 不變**。
- [ ] `/admin`、`/users`、`/config` 文案為完成品語氣：無「no longer a placeholder」「demo」式施工備註；`/config` 按鈕為「Reset to defaults」。資料 / 表單 / 寫入動作不變。
- [ ] AppShell nav 結構不變、不暴露 endpoint 名稱 / UUID-first workflow（最終 sweep 通過）。
- [ ] 既有 redirect（`/review`、`/ask`、`/evals`、`/resources`、`/repo-agents`、`/import`、`/git-env`）維持可達，未被刪除或破壞。
- [ ] 所有受影響頁面既有狀態（loading / 未簽入 / empty / error / 窄屏）行為未退步。
- [ ] 無 fake data / fake metric / placeholder；無新增相依。
- [ ] 無 backend 變更；`lib/api.ts`、`lib/platform-context.tsx`、`lib/lifecycle.ts`、`ui.tsx`、`ResourceScopePicker.tsx`、`AgentContextPreview.tsx` 行為未變。
- [ ] `lint`（`tsc --noEmit`）與 `build`（`next build`）通過。

## 8. Verification Commands

由 repo root 執行（除非另註）。

```bash
# 1. 確認改動範圍乾淨，未碰禁區
git status --short
git diff --name-only origin/main...HEAD
# 預期僅出現：
#   apps/web/app/page.tsx
#   apps/web/app/agent-files/page.tsx
#   apps/web/app/admin/page.tsx
#   apps/web/app/users/page.tsx
#   apps/web/app/config/page.tsx
#   (若有) apps/web/app/login/page.tsx
#   (若有) apps/web/components/AppShell.tsx
#   (若有 additive CSS) apps/web/app/globals.css
#   docs/frontend-rebuild/PR5-ship-admin-cleanup-spec.md

# 2. Command Center 不再指向 legacy 路由（應無輸出）
grep -nE "href[:=] ?['\"]/(import|review|resources|ask|repo-agents|evals|git-env)['\"]" apps/web/app/page.tsx

# 3. 靜態檢查
npm --prefix apps/web run lint
npm --prefix apps/web run build

# 4. 確認禁區未被改動（應無輸出）
git diff --name-only origin/main...HEAD -- apps/api packages migrations \
  apps/web/lib/api.ts apps/web/lib/platform-context.tsx apps/web/lib/lifecycle.ts \
  apps/web/components/ui.tsx apps/web/components/ResourceScopePicker.tsx \
  apps/web/components/AgentContextPreview.tsx

# 5. 確認既有 redirect 仍在（每個都應印出 redirect 行）
grep -l "redirect(" apps/web/app/{review,ask,evals,resources,repo-agents,import,git-env}/page.tsx
```

Browser smoke：

```bash
npm --prefix apps/web run dev -- --hostname 0.0.0.0 --port 13000
```

於瀏覽器確認：

- Command Center 每個連結點下去**直接**到 canonical hub（網址列不再短暫出現 `/review`、`/ask`、`/import` 等再轉址）；標籤與 nav 命名一致。
- `/agent-files` 第一屏先呈現 Skill Pack 下載 / 安裝，legacy 區塊在下方且標示為相容性保留；下載 zip / copy artifact / 遠端 grep+read 皆仍可運作。
- `/admin`、`/users`、`/config` 文案讀起來是完成品；`/config`「Reset to defaults」可用，表單儲存與 token 建立 / 撤銷仍正常。
- 直接訪問 `/review`、`/ask`、`/evals`、`/resources`、`/repo-agents`、`/import`、`/git-env` 仍正確轉址，不 404。
- 其他既有路由 `/`、`/sources`、`/workbench`、`/quality`、`/maintenance`、`/agent-profile`、`/login` 仍正常渲染，無 console error。
- 窄屏（mobile viewport）各頁堆疊行為未退步。

## 9. Risks & Rollback

| Risk | Impact | Mitigation |
| --- | --- | --- |
| 改 Command Center 連結時誤動 readiness / attention 邏輯 | 首頁狀態判斷退步 | 只改 href / label 字面值；§7 明列「derived state 未變」為驗收項；diff 逐行確認無觸及 `useMemo` / 條件 |
| Ship surface 重排序破壞既有 fetch / state | 交付面功能倒退 | 僅重排既有 JSX 區塊與改文案，不動 state / effect / fetch；smoke 驗證下載 / grep / read |
| 文案收斂誤刪必要技術說明（如 login dev-auth） | 使用者不知如何登入 | session 頁保留必要技術說明；文案僅去除「施工備註」語氣，非刪功能性指引 |
| 誤刪 legacy redirect 造成外部書籤 404 | 既有深連結中斷 | 明列 redirect 為禁區、不刪；§8 step 5 grep 確認 redirect 仍在 |
| 移除 UUID 顯示傷及 operator debug | 運維能力下降 | PR5 **不移除**既有 debug UUID（折疊 / code 次要行）；僅收文案語氣 |
| globals.css 新增 class 影響既有頁 | 樣式跑版 | 目標零新增；必要時僅 additive、不改既有 class；smoke 多頁 |
| 改到 `ui.tsx` / context / lifecycle 契約 | 破壞其他頁 | 只複用既有 export，不改 signature；§8 diff guard 檢查 |

### Rollback

PR5 為 frontend-only、純收尾，回滾簡單：

- Revert PR branch 或 merge commit 即可，無 DB migration、無 backend 相容性問題。
- 各項改動彼此獨立（連結 / Ship 文案 / Admin 文案），可整組 revert，亦可單檔 revert 而不互相破壞。
- 後端契約與資料模型全程未變，回滾後既有 API 與 PR1–PR4 不受影響。
