# deferred call 的路由與決定權（2026-08-21）

> **起點**：使用者提的模型——multi-hop 委託中，中間人只有兩種身分，
> **agency** 或 **resource owner**，而下游的暫停該由誰處理，由這個身分決定。
>
> **本檔只放結論。** 這幾天來回過程中被推翻的說法另存
> `retractions.md`，因為那些錯誤有共同形態，值得單獨讀。
>
> 所有規格與 GitHub issue 內容於 2026-08-21 查證；標示「未讀完整 diff」的
> 地方請以原文為準。

---

## 1. 三件被混在一起的事

| | 是什麼 | 靠什麼解決 | 牽涉權限嗎 |
|---|---|---|---|
| ① **我需要一個事實** | 「尺寸多少？」 | 一次正常的 tool call／對話往返 | 否 |
| ② **我需要憑證去存取某資源** | OAuth 之類 | A2A 的 `AUTH_REQUIRED`，可走頻外 | 是，但是對第三方的 |
| ③ **我要動手了，而這動作是保留的** | 「我要下訂五百塊的布」 | **這才是 deferred call** | **是，對 principal 的** |

**deferred call 是「我要動手了」的那一瞬間**，不是「我有問題想問」。
它是一個再正常不過的 tool call，只是被攔截。

### 1.1 這個混淆不是我們的，是 A2A 的

**#1582**（`Clarify the difference between INPUT_REQUIRED and AUTH_REQUIRED`，
已關閉，11 則討論）就是在吵這件事。Tehsmash 講出了關鍵：

> …the Agent *could* keep operating and perform additional actions in parallel
> with the action that requires input. This is a common pattern in coding
> agents where they might run multiple commands, and **only 1 requires
> confirmation from the user/agent**.

mikeas1 的結論是需要「a more structured representation … allowing multiple
outstanding requests … **disentangling this from TaskState/TaskStatus**」，
並明說「we should consider that for **v2**」。

那個 v2 就是現在的 **#2149**（`Elicitation`，`WAITING`/`BLOCKED`/`RESOLVED`，
脫離 `TaskState`；2026-08-18 開啟，0 comments，stacked on #2129，尚未 rebase
到 `dev-1.1`）。**但據 PR 描述，`Elicitation` 只有
`{elicitationId, state, metadata}`——沒有型別欄位。** ①③ 在新設計裡仍然是
同一種東西。（限制：只讀了 PR 描述，未讀完整 diff。）

### 1.2 我們讀過的文獻全都站在「動作邊界」這一側

- **Stop Means Stop `2607.14166`**：全篇對象是 side effect；SOUNDGATE 是
  **effect gate**
- **MasDrift `2608.07556`**：環境暴露「準備工作的工具」與
  「**被保留待核准的動作**」，reference monitor 判的是 **tool call**
- **SteerBench-Work `2608.12654`**：標題就是 *Agent Steering at Action
  Boundaries*
- **SAGE-Fin `2608.09025`**：把「**被提議的 effect**，而不是它的文字」當成
  runtime 控制對象

### 1.3 「model 夠強就不需要暫停」——正確的版本

分清楚之後，這個論證變成一句**定義**而不是經驗主張：

> **模型變強會消掉的那些暫停，本來就不是 deferred call。**

第 ① 類隨模型變強而減少，而它根本不在 deferred call 的範圍內。第 ③ 類與模型
能力無關，因為授權不是知識：**一個完美預測你會同意的模型，並沒有得到你的
同意。** MasDrift Principle 1 是這句話的規範版：

> Task readiness, role expectations, inter-agent agreement, and successful
> completion of prerequisite work **do not themselves constitute user
> authorization**.

更根本的理由：**這個暫停的功能不是彌補無知，是產生證據。** 一個全知的 agent
依完美預測直接行動，從外部看與一次未經授權的行動**無法區分**。

---

## 2. 決定權

> **用詞**：「決定權」＝設計記錄的 *the right to act on a paused thread*——
> 對一個卡住的 deferred call 給出批准或否決的資格。A2A 的用語是 resolve
> （elicitation 狀態 `RESOLVED`）。

### 2.1 一句話規則

deferred call 一定出現在某條鏈的終點——誰要動手，誰就是那個點。

> **從那個節點往上走，遇到的第一個 break 邊，它的上端就是決定者。
> 一路沒有 break，就一路走到 root。**

```
root ──extend──> A ──extend──> B ──break──> C
```

- **C 卡住** → 往上第一個 break 是 B→C → **決定者是 B**（設計記錄：
  「its human resolves the subtree's interrupts, its KYOK offering funds
  them」）。root 看不到，也不付這筆錢。
- **B 卡住** → 一路都是 extend → **決定者是 root**。

**恰好一個決定者，沒有競爭，不需要任何人宣告誰是決定者。** 設計記錄已有的
「segment head」就是這個東西，只是從來沒有人把「往上走到第一個 break」寫出來。

### 2.2 從同一個宣告推導出來的五條

**per-edge 的 break/extend 是唯一的宣告。以下全部是推導結果，不是另外加的
規則**——這正是論文要主張的形狀。

1. **誰是決定者** = §2.1 的規則。
2. **自我核准在 break 下合法、在 extend 下非法。** break 之下決定者與付錢者
   是同一方（自己的錢、自己的風險政策）；extend 之下自我核准就是「看得到但
   不付錢」，正是三件綁定所禁止的。
3. **誰定保留集合**（哪些 tool call 是 deferred call）。break 之下 root 連
   subtree 的工具名字都叫不出來，只能由 provider 定；extend 之下 root 的邊界
   才伸得進去。中間那條路——把 root 的策略沿鏈攻減傳下去——**已被 MasDrift
   測掉**：Chain 擋掉最多 54.5% 的必要呼叫、損失 36.3 分完成率，因為委派者
   猜不到下游需要什麼。
4. **揭露開關只在 extend 之下有意義。** 設計記錄的「Authorization is not
   disclosure」講的是**往下**的方向——答案回去時，提問者知不知道是誰答的
   （「the provider learns only that the head resolved」）。break 之下決定者
   就是提問者的直接上游，沒什麼好揭露或隱藏；**extend ＋ 不揭露** 就是代理法
   的 **undisclosed agency**，現行設計已經表達得出來。
   上行由 break/extend 管、下行由揭露開關管，**兩者正交**。
5. **break 與 extend 對「問問題」的定價相反。** break 之下想問就得用自己的
   名義往上一次來回，壓力是少問；extend 之下問題直接浮到上游，可以放手問。
   同一個 agent 實作掛在不同宣告的邊上，成本完全不同。

兩條不是推導、是既有規則的直接套用：

- **決定是驗簽，不是知道名字**（rule zero）。
- **agent 不能自己去找第三方來批准**——那是換個方式的自我核准。
  MasDrift Principle 1：委派不能生出權限。

### 2.3 為什麼「回答權／成本／可見性」三件必須綁在一起

設計記錄給的理由是防賴皮（「使用者付錢但不准看」「provider 看得到但不付錢」
都不可表達）。那是**結果**，不是原因。原因是三件事本來就是**一件事的三個
階段**：

> **看見 → 回答 → 花錢。** 看見是回答的前提，花錢是回答的後果。

拆開等於要求某人做一件他做不到或不該做的事：

- 給回答權但不給看 → **他做不到**，他不知道問題是什麼
- 給回答權但錢算別人頭上 → 他在花別人的錢，**沒有節制的理由**
- 給看但不給回答權與成本 → 他看到了卻什麼都不能做，**那只是洩漏**

**一個要在論文裡畫的例外**：稽核員與營運人員應該看得到、不該有回答權、
也不付錢。所以綁的是**「回答權」這一束**，不是「所有的可見性」。純觀察是
另一件事。現行記錄沒有畫這條線。

---

## 3. 兩模式模型的定位

### 3.1 先例很硬——這界定了新意在哪

- **代理法／會計**：IFRS 15 / ASC 606 的 principal-versus-agent 判定看
  **控制權有沒有先移轉給中間人**；商法另有 disclosed / undisclosed principal。
- **身分協定**：RFC 8693 明確區分 **impersonation** 與 **delegation**
  （`act` 鏈保留兩個身分）。A2A 的 actor-chain 提案 #2028 刻意照抄這個形狀。
- **Kerberos**：forwardable / proxiable ticket、constrained delegation。

**新意不在二分本身**，在於把它接到 deferred call 的路由上。好消息是論文站得
穩（可引法律與 RFC 先例，不是憑空造詞）；壞消息是不能把二分本身當貢獻賣。

### 3.2 它已經在 funduq 的設計記錄裡了

design-records「One question per delegation edge decides the whole
tree」（頁面已隨 `5503c91` 刪除，引文釘在
[歷史](https://github.com/hukaichun/funduq/blob/c3bbc5c65fa0ced3520d2858c94fd9fed70a81ab/docs/design-records.md)）：

> *if the sub agent gets stuck or fails, can I carry on without it?*
> **Yes breaks the chain**（且為預設）… **No extends the chain**.

**break ＝ resource owner，extend ＝ agency。** 而機制頁（已隨 `5503c91`
刪除，釘在
[歷史](https://github.com/hukaichun/funduq/blob/c3bbc5c65fa0ced3520d2858c94fd9fed70a81ab/docs/mechanisms/responsibility-chains.md)；
機制本身已實作：`identity.verify_resolution`、
`test_responsibility_chains.py`）的開場問題**逐字就是這個問題**（2026-09-03 對釘住的原文校正——原引文多了
一個原文沒有的 "Now:"）：
「the sub-agent pauses for a human answer (`input-required`). **Who may
answer**, what proves they were entitled to, and what records that it was
them?」

被獨立重新導出一次，是這個設計自然的證據。

### 3.3 宣告，不是推導——因為推導需要裁決

| | 這個 bit 怎麼來 |
|---|---|
| 設計記錄 | provider **自己宣告**，宣告錯了自己付錢（自我修正） |
| 兩模式模型 | 由 provider **是什麼**推導出來 |

**推導需要有人判定「你是代理還是資源擁有者」——那是一次裁決，直接撞
rule zero。**

**結論**：兩者都留，但分層。

- **機制**：宣告自由 ＋ 錯了付錢。funduq 只記錄宣告與後果，**不判定任何人
  是什麼**。
- **詞彙**：agency / resource owner 是那兩個宣告各自**意味著什麼**的名字，
  解釋為什麼自由宣告會塌縮成兩個吸引子。

**論文裡的寫法**：不要寫「中間人分兩種，因此路由如此」（那需要判定身分），
要寫「**一個自由的、被定價的每邊宣告，會產生兩個穩定型態，而它們恰好對應
代理法早就命名過的兩種關係**」。

### 3.4 模式由行為呈現，不由誰判定

可觀察的其實是兩件被記錄的事：

| | break | extend |
|---|---|---|
| 問題用誰的名義提出 | **中間人自己** | **subagent 的名義往上浮** |
| 誰被記錄為決定者 | 中間人（為它轉述的內容負責） | segment head，在那條邊的授權下 |

兩件都不需要判定任何人是什麼，兩件 funduq 都記錄得到。

**一個常見的誤解**：「provider 把 subagent 藏在 funduq 之外，我們就看不到」
**不是漏洞**。他的資源是他的，藏起來就代表責任全在他身上——鏈根本沒有延伸
出去，**是最無歧義的情況**。

---

## 4. 文獻與規格查詢：沒有人問過這個問題

### 4.1 A2A

- **#2149**（elicitations）：整個設計是**兩方的**。「Responding to an
  elicitation: **Resolution stays the agent's responsibility**」；
  `SendMessageRequest.elicitationId` 是 client hint——clients **never
  required** to set it、servers **MAY** ignore、servers **MUST NOT** reject
  a message solely because it is absent。**沒有任何鏈的概念。**
- **#2061**（多輪語意提案）有一張「三種輸入的授權意涵」表，方向相鄰但仍是
  兩方。
- **#2028 actor-chain**（kennethsinder，24 comments，開著）處理的是**往下的
  歸屬鏈**（照 RFC 8693 `act`），不是往上的路由。
- repo 標題搜尋 `proxy` / `intermediary` / `broker` / `forward`：**零結果**。

### 4.2 MCP（2026-07-28）

elicitation 規格明文：

> Implementations are free to expose elicitation through any interface pattern
> that suits their needs—**the protocol itself does not mandate any specific
> user interaction model.**

規範性要求全部預設 client 有一個人類 user（「Provide UI that makes it clear
**which server is requesting information**」）。**沒有中間人的概念**；
spec 裡的 "nested" 指的是巢狀在 server 功能之內，不是鏈式巢狀。

### 4.3 業界已經在做選擇，但沒有名字

Cloudflare Agents SDK（changelog 2026-07-13）把行為**寫死成 agency mode**：
agent 只轉發，「Show the request in your UI and resolve after the user
responds」。唯一的另一條路是**降級**而非另一個模式：沒有 handler 就不宣告
elicitation capability，讓 server 用 fallback。

### 4.4 arXiv

以下查詢在 2025-01 之後**全部零結果**：`"disclosed principal"` /
`"undisclosed principal"`、`escalation + routing + delegation (cs.AI)`、
`clarification question + multi-agent + delegation`、
`approval + nested + agent (cs.AI)`。

相鄰但不同題：`2601.23211`（Multi-Agent Systems Should be Treated as
Principal-Agent Problems——關切資訊不對稱與 agency loss，不是路由）、
`2509.13597`（Agentic JWT，impersonation vs delegation 但在權杖層）。
multi-principal 那一叢（`2604.09744` MPAC 明說 MCP 與 A2A「both assume a
**single controlling principal**」、`2604.08567`、`2606.21856`、`2606.18829`）
處理的是**多個 principal 之間的衝突**，不是一個 principal 穿過中間人。

### 4.5 結論

**既沒有被驗證可行，也沒有被驗證不可行——是沒有人問過。** 兩個主要協定都停在
兩方模型（client ↔ agent／client ↔ server），中間人是什麼在規格裡根本不是
一個概念，於是每個實作各自寫死一種行為。

---

## 5. 兩個可以直接提給 A2A 的具體改進

兩者都是**一個物件在做兩件事**：

1. **`Elicitation` 沒有型別欄位**，分不出「我要一個事實」（正常往返）與
   「我要動手了請批准」（真正的 deferred call）。見 §1.1。
2. **「已回答」與「已生效」沒有分開**。`RESOLVED` 的意思是那個問題被回答了，
   不是那個動作發生了。理由是 observed-outcomes-only 套用到狀態機與 UI 上——
   決定者需要知道對方到底有沒有做。若在 UI 上併成一個綠勾，使用者會以為布
   買好了。

---

## 6. 值不值得發表

**值得，但不是當獨立論文，是當責任鏈論文裡的一組推論。**

二分本身有成熟先例（代理法、RFC 8693），不能當貢獻賣。真正新的是
**一個宣告推導出五條結果**（§2.2），而它的形狀正好是論文主張的形狀——
在一個最小中立中介之下，規格未定義的問題塌縮成可推導的答案。這是既有
outline 裡 T1/T3 的具體實例，不是新的一支。

**它可以被證偽，這是最大的優點。** 檢驗方式很具體：拿 A2A #2149 的
elicitation 設計，構造一個三跳中繼情境，證明兩種模式給出**不同的正確答案**，
而現行規格**兩種都允許**——那就是「規格未定義」的存在性證明，可以寫成一支
probe（符合 CLAUDE.md「用跑得動的東西驗證」）。

**發表前必須先做的兩件事**：

1. multi-principal 中間人落在哪一格（或明確劃出範圍外）。
2. 追蹤 A2A #2149 落地後的最終語意——它還開著、還要 rebase 到 `dev-1.1`。

**不要寫進去的**：「如果 model 夠強就不需要這個暫停」的原版。用 §1.3。
