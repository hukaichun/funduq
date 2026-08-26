# 同位置專案與規格的重查 — 2026-08-25,2026-08-26 續

> 起因:`bibliography-notes.md` 的學術側很厚,產品/規格側只有 memory 裡
> 一段名字清單。這一輪只查**跟 funduq 站在同一個位置的東西**:誰在
> 呼叫方與供應方之間、誰記委派、誰記責任。
>
> **第一輪(08-25)推翻了一個既有判斷**,見 §5。**第二輪(08-26)查四家
> 大廠的跨組織狀態,見 §7**——那一節的結論比規格層更硬,因為它引的是已經
> 出貨的產品自己寫下的限制。
>
> 凡標「未證實」或 `[待逐字查證]` 的不得進論文。

---

## 0. 一句話結論

**「簽名跳鏈」在 2026 年 3–6 月之間從空地變成擁擠的地段**——至少五個設計,
其中一個掛著 Okta 與 Cisco 的名字。但**它們全部落在我們 §2 預測的三個前提
裡**,而且每一條都可以用**他們自己的文字**引,不必再靠推論。

---

## 1. 規格層(IETF)——變化最大的一層

| 草案 | 誰 | 日期 | 鏈長什麼樣 | 誰簽 | 帶 scope | 帶時間 | 狀態 |
|---|---|---|---|---|---|---|---|
| `draft-ietf-oauth-identity-chaining-17` | OAuth WG | 2026-07-19 | 跨域 token exchange,逐段換發 | 各域 AS | 是 | 是 | **已採納,已送 IESG** |
| `draft-liu-oauth-chain-delegation-00` | Alibaba×2, Cisco, **Okta** | 2026-06-06 | `delegation_chain` claim,`act` 的伴生 | **AS 簽每一筆** | 是(+ Rego policy) | 是 | 個人投稿,未採納 |
| `draft-niyikiza-oauth-attenuating-agent-tokens-01` | Tenuo(單人) | 2026-06-15 | `par_hash` 連鏈,能力遞減 | 上一跳的 `cnf.jwk` | 是(`authorization_details`) | 是(`exp`,子不得長於父) | 個人投稿 |
| `draft-sato-soos-mjwt-00` | MyAuberge(單人) | 2026-05-24 | `delegation_chain` + Cedar | GEC | 是(`cedar_actions`) | 是 | 個人投稿 |
| `draft-helixar-hdp-agentic-delegation-00` | Helixar(單人) | 2026-03 | append-only hop 陣列 | **issuer 一把 key 全簽** | 是 | 是(24h 預設) | 個人投稿 |
| `draft-haberkamp-ipp-00` (IPP) | — | — | append-only,Ed25519 | — | — | — | 個人投稿 |
| `draft-goswami-agentic-jwt-00` | — | — | 「整條委派鏈」 | — | — | — | 個人投稿 |
| `draft-klrc-aiagent-auth-00` (AIMS) | — | 2026-03 | WIMSE+SPIFFE+OAuth 組合 | — | — | — | 個人投稿 |
| `draft-sharif-agent-audit-trail-00` | — | — | 標準化日誌格式 | — | — | — | 個人投稿 |

**唯一成熟的那一份把我們的題目寫在範圍外。** `draft-ietf-oauth-identity-chaining`
已到 IESG,做的是跨信任域的 token exchange,**不處理 audit trail、
accountability、responsibility attribution**——查證於 datatracker 的
文件頁,2026-08-25。這是「成熟標準留下的空位」的直接證據。

**`delegation_chain` claim 是最該盯的一份。** 四位作者含 Okta 與 Cisco。
它的形狀正好是我們的反面:
- 每一筆 record 由 **AS** 簽(`as_signature` 必填,`delegator_signature` 只是
  RECOMMENDED);
- 「Resource Server **MUST** use token introspection to retrieve the
  authoritative `delegation_chain` from the AS, rather than trusting any
  client-supplied chain data」——**鏈的權威在 AS 手上,不在鏈本身**;
- 每一筆帶 `scope`,且強制 narrowing;帶 `delegation_timestamp`;`sub` 全程不變;
- **只支援線性鏈**,菱形拓撲明文延後;建議最大深度 5 跳。
- **沒有任何機制表示「不延伸」。**

---

## 2. 學術層——四篇 bibliography 裡沒有的

**HDP** — arXiv:2604.04522,Helixar(紐西蘭,單一作者),2026-03。
**目前與 funduq 機制最接近的一篇**,而且它自己講了我們的那句話:
> "Semantic validation of agent actions against declared scope is an
> application-layer concern; **HDP provides the record, not the enforcement**."(§4.2.3)

差別在哪(全部引得到原文):
- **§7.1:「HDP v0.1 uses the issuer's key for all hop signatures, meaning
  agents do not sign with their own keys… hop signatures attest that a hop
  was recorded at the issuer, not that the specific agent produced it.」**
  ——它的鏈證明的是**中央記錄過**,不是各方簽過。per-agent key 是 v0.2 計畫。
- 它記 scope(`intent` 自然語言 + `authorized_tools` + `data_classification`
  + `network_egress` + `persistence` + `max_hops`),然後把檢查推給應用層。
  我們是**根本不記 scope**。「record not enforcement」這句話兩邊都說得出來,
  **差別在記的是什麼**,論文必須把這條線畫在這裡,否則審稿人會說已經有人講過。
- 它綁 `session_id` 與 `expires_at`(預設 24 小時);我們的 hop 不帶時間。
- 它的重放防禦就是 expiry + session binding,**不驗持有**。

**SentinelAgent** — arXiv:2604.02767。中央 Delegation Authority Service 發證、
攔截、阻擋,NIST 800-53 寫進 token。**裁決者那一格的當代實例**,而且它自報
intent 驗證對改寫過的敵意輸入只有 13% TPR。

**Auditable Agents** — arXiv:2604.05485v2,USC/ASU/JHU,**2026-08-13**。
五個 auditability 維度,其中第四個就叫 **Responsibility Attribution**
(「full delegation chains recoverable from immediate executor to originating
principal」)。兩句要引:
- 「**no existing work covers all five dimensions jointly**」,而 Evidence
  Integrity 與 Lifecycle Coverage 最被忽略;
- 開放問題 **OP3:「Capturing full responsibility chains across multi-agent
  delegation」**;**OP6:跨組織持有部分軌跡時的稽核彙整**。

→ **這是目前為止最好的 §1 鉤子候選**:三校合著、兩週前、把我們做的事寫成
未解問題。比 CSA 那兩個百分比強得多,而那兩個數字的 n 到現在還沒查證。

**Authorization Propagation as Infrastructure** — arXiv:2605.05440,Kamiwaza,
2026-05。只提 R1–R7 需求、不提機制,自陳「Whether these mechanisms can be
composed without introducing new failure modes remains an open architectural
question」。需求側引用用。

(尚未讀:Anumati arXiv:2604.16524 —— proof of adherence 的形式化同意模型。)

---

## 3. 產品層——誰站在中介位置

| 東西 | 位置 | 委派怎麼處理 | 跟 funduq 的距離 |
|---|---|---|---|
| **agentgateway**(Solo.io → AAIF) | 線上 proxy | OAuth token exchange:`sub` = 使用者、`act` = agent。**只記當下這一段** | 佔了 gateway 的位子,但在線路上;我們不碰線路 |
| **MuleSoft Agent Fabric / Agent Broker + A2A Bridge**(Salesforce) | **持有 task lifecycle 的 broker** | 協定轉譯、ID mapping、task lifecycle 狀態管理、context propagation、task cancellation | **商業側最接近的一個**。閉源,綁 Salesforce |
| **IBM ContextForge** | registry + proxy | 統一端點、集中治理與可觀測 | registry/proxy,不記責任 |
| **Google Gemini Enterprise Agent Gateway**(2026-04) | 政策執行點 | 對 A2A / agent-to-tool 連線施加政策 | 裁決者 |
| **Microsoft Entra Agent ID**(已 GA) | 目錄 | agent 在租戶目錄裡有自己的身分,Conditional Access | **agent-as-principal 那一列的當代實例** |
| **AWS AgentCore Identity** | 目錄 + 憑證保管 | 代使用者取得各 SaaS 的 OAuth 同意 | 同上,偏 authn |
| **A2A Registry**(discussion #741 / a2a-registry.org) | 目錄 | discovery + entitlements;**規格仍未定** | 我們的 join target |

---

## 4. 需求側與趨勢

- **EU AI Act**:高風險系統的自動事件記錄義務,2026-08 起進入較廣的執行階段;
  Art. 12(1) 要求日誌保存**至少六個月**。合規語言已經在講 append-only、
  hash-chained、tamper-evident。**這是最硬的需求側證據**,但要引法條原文,
  不要引部落格。
- **AAIF**:八個工作組,其中 **Identity & Trust** 自述為「Defining portable
  identity and dynamic trust for autonomous agents — delegation protocols,
  cross-domain identity, and how permissions flow across agent-to-agent
  interactions」(查證於 aaif.io,2026-08-25)。A2A 移交 AAIF 的日期,新聞寫
  **2026-08-20**,memory 裡寫 08-17,**兩者不一致,要查**。
- **未證實**:某二手部落格稱 AAIF 路線圖有「A2A governance spec — RFC-complete
  inter-agent trust chain standard targeting Q3 2026」。**aaif.io 上沒有任何
  路線圖**。這件事如果為真會直接影響定位,必須查到一手來源才能用。
- A2A 側有 `trust.signals[]` extension(issue #1628),以及多個彼此詞彙不同的
  `governance_attestation` 實作。

---

## 5. 這一輪推翻的判斷

**舊說法**:「scope-in-chain 還太早,116 份草案裡只有 5 份用
`authorization_details`」——那個數字講的是 **scope**,不是**鏈**。
拿它去支持「沒人在做委派鏈」會是錯引。實際情況是:

- **鏈**這件事,2026 年上半年至少五個設計同時出現;
- **scope 進鏈**這件事,那五個裡有**四個**都做了(AAT 的
  `authorization_details`、MJWT 的 `cedar_actions`、`delegation_chain` 的
  `scope` + Rego、HDP 的 `scope` 物件),而**四套詞彙互不相容**——
  這反而讓「沒有共同權限詞彙」的論證變強,但**證據要換一組**:
  從「沒人往裡放」換成「大家各放各的,四份規格四套詞彙」。

---

## 6. 給論文的直接影響

1. **§2 那張表可以改成引原文的**。三個前提各有當代實例,而且每一格都能引
   對方自己的句子——這正是 `retractions.md` 要求的門檻。
2. **§1 的鉤子換成 Auditable Agents 的 OP3**,CSA 的百分比降級或刪掉。
3. **必須新增一段跟 HDP 的區隔**,因為 record-not-enforce 這句話已經有人講過。
   我們的差異是三條,不是一條:**每跳自己的金鑰**(HDP §7.1 自認未做)、
   **不帶 scope 與時間**、**break 是一級行為**(五個設計沒有一個處理拒絕延伸)。
4. **要盯 `draft-liu-oauth-chain-delegation`**。如果它被 OAuth WG 採納,
   `funduq-contract` 就從補充變成競爭者。

---

# 第二輪(2026-08-26):四家大廠的跨組織狀態

> 問題:IBM / Google / AWS / Microsoft 在**跨單位** agent 互動上做到哪裡。
> 答案很整齊——**他們的產品邊界正好畫在論文說的那條線上,而且是他們自己
> 畫的**。以下每一句引文都從一手文件取得;凡是「文件沒有談」的一律標成
> **沒寫**,不得寫成「明文排除」。

## 7.1 Microsoft — 身分不出租戶,自己寫明

`docs/agent-id/agent-identities.md`(MicrosoftDocs/entra-docs,2026-08-26 取):

> 「Agent identities can only be issued tokens in the Microsoft Entra tenant
> where they're created. **They can't access resources or APIs in other
> tenants.**」
>
> 「While agent identities are single-tenant, agent identity blueprints can be
> configured as multitenant. A multitenant blueprint can be published and
> added to other tenants, where it creates **tenant-local** agent identities.
> **The agent identities themselves always remain single-tenant.**」

**跨租戶的做法是在對方租戶裡再造一個本地身分。** 於是同一個 agent 在兩個
組織裡是兩個身分,而沒有任何東西把它們連起來——「跨邊界的連續性」在這個
模型裡不是做得不好,是不存在。

同一份 FAQ 裡一句對責任歸屬直接不利的自陳:

> 「Audit logs **don't distinguish agent identities from other Microsoft
> Entra identity types by default**… Operations initiated by agent identities
> appear as **service principals**.」

值得記一筆的概念:Copilot Studio 建立的 agent,「The user who created the
agent is recorded as its **sponsor**」。這是廠商產品裡最接近責任根的東西,
但它綁的是**建立者**,不是**每一次呼叫的委派者**——一個 sponsor 對應一個
agent 的一生,不對應一次工作。

## 7.2 Google — SPIFFE 身分,跨組織沒寫

`docs.cloud.google.com/agent-builder/agent-engine/agent-identity`:每個 agent
拿到 SPIFFE 身分與自動配發的 X.509 憑證;

> 「Unlike service accounts, agent identities are **not shared by multiple
> workloads by default, can't be impersonated**, and don't allow developers
> to generate long-lived service account keys.」

代使用者行事走 3-legged OAuth。**文件沒有談跨組織**——是沒寫,不是寫明在
範圍外。`[若要在論文裡用,只能寫「未見規範」]`

## 7.3 AWS — 一跳的 on-behalf-of 加憑證保管

Bedrock AgentCore Identity:agent 身分實作成 workload identity;inbound 用
IAM SigV4 或外部 IdP 的 OAuth/JWT,outbound 用憑證提供者去取第三方服務,
目的是

> 「enable agents and tools to access AWS resources and third-party services
> **on behalf of users**」

也就是**一跳的 OBO**。跨帳號有(Memory 2026-06 支援),**跨組織沒有**,
多跳委派的紀錄也沒有。

## 7.4 IBM — 集中式控制平面,範圍是「你的企業」

watsonx Orchestrate 的 Agentic Control Plane(2026-06,AWS 與 IBM Cloud):
集中式身分與憑證管理、政策執行、稽核日誌、隔離控制,治理「agents from any
source with consistent policy enforcement and full auditability」,範圍寫的是
「across your entire **enterprise** environment」。
`[一手公告頁回 403;引文目前是二手,進論文前要另找可引來源]`

Agent Catalog 被描述成一個受治理的市集——**位置上最接近 funduq**,但它是
單一廠商內的目錄,不是跨信任邊界的中介。

## 7.5 交棒鏈是完整的,而且每一棒都引得到

四家都把跨組織交給 A2A。A2A 自己說(`a2a-protocol.org/latest/topics/
enterprise-ready/`):

> 「A2A delegates authentication to standard web mechanisms.」
>
> 「A2A protocol payloads, such as `JSON-RPC` messages, **don't carry user or
> client identity information directly. Identity is established at the
> transport/HTTP layer.**」

**廠商說跨組織找 A2A,A2A 說身分在傳輸層。沒有人接住責任。**

(A2A 文件同樣**沒有**明文說它不處理責任鏈或跨跳稽核——只是沒寫。上面兩句
引文本身已經夠用,不需要再加一句我們自己的推論。)

## 7.6 這一輪對論文的六個影響

1. **§1 的三個支撐點多了一種證據。** 原本靠規格草案;現在四家出貨產品的
   邊界就畫在那條線上。規格是提案,產品是已經做出的取捨——後者更硬。
2. **§2 少一格,要補:大廠不是解決了跨組織,是把它定義掉了。** 應對支撐點
   缺失的第四種方式,是**把邊界縮進支撐點存在的範圍內**。
3. **agent-as-principal 那一列改寫。** 別再寫「沒有自己目錄的供應方不可
   表達」,改引微軟原文:身分永遠單租戶,跨租戶靠複製,連續性不存在。
4. **§6.1 拿到一句協定原文。** 「Identity is established at the
   transport/HTTP layer」正是為什麼呈交者的認證必須留在門外、而比對留在
   門內——presenter check 的形狀有了協定自己的解釋。
5. **§8 要準備一個反問:「廠商明年就做跨租戶了」。** 答案:他們會做的是
   目錄聯邦,而那需要兩個組織先聯邦——**同一個中央發證方支撐點,只是換了
   個尺度**。
6. **sponsor 是一個要處理的鄰居。** 微軟已經記錄「誰建立了這個 agent」。
   要講清楚差別:那是一個 agent 一生一個,而責任鏈是**一次工作一條**。

## 7.7 待辦

- IBM 的一手可引來源(公告頁 403)。
- Google / A2A 的「沒寫」不得寫成「排除」——已在 §2 的檢查清單裡。
- 新增五筆一手來源進 `bibliography-notes.md`:Entra Agent ID 文件、A2A
  enterprise-ready 頁、Google agent identity、AWS AgentCore Identity、
  IBM Agentic Control Plane。
