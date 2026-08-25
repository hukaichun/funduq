# 責任鏈論文：已知優勢與已知缺口（2026-08-21）

> 這是 2026-08-21 那一輪文獻工作的結算。每條優勢都附**出處與原句**，
> 每條缺口都附**為什麼重要**與**誰該決定**。
>
> 來源：`downstream-review-2026-08.md`（339 篇下游引用擴查＋listing 補查，
> 五篇全文精讀）、`input-required-routing.md`（deferred call 路由，只放結論）、
> `retractions.md`（被推翻的十三條說法）、
> `bibliography-notes.md`，以及本 repo 的 `docs/`。
>
> **原則**：這份文件裡沒有一句「應該可以」。凡是還沒查證的，一律進缺口。

---

## A. 已知優勢

### A1 定位：兩份獨立文獻替我們陳述了需求面

**主張**：funduq 不做治理，funduq 留下治理接得上的那個縫。

**證據**：

- `2606.31498` §VII（已讀全文）：治理是 **missing architectural layer**，
  需要能與既有互通標準**組合**而非「reimplemented ad hoc by every
  application」。
- RAILS `2606.08790` §12 最後一條 Limitations（已讀全文）：
  > **Governance questions remain open.** Who registers verifiers? Who
  > certifies templates? Who arbitrates Passport disputes? Who has standing
  > to challenge a Clearing Decision after the appeal window closes? These
  > are governance questions, not protocol questions, **and they are not
  > settled.**

**為什麼是優勢**：它把「funduq 什麼都不決定」從弱點翻成主張，而且需求是由
**別人**陳述的。兩篇立場不同、作者不同、社群不同，都在描述同一個縫。

**怎麼用**：discussion 的主線。

---

### A2 同軸最近鄰把我們的題目寫成它的 open problem

**證據**（RAILS §12.1，已讀全文）：

> The subdelegation case of Section 9.2, in which one agent hires another
> that hires a third, **leaves open the assignment of fault along that chain**
> when the output is unsound, a problem autonomous agent-to-agent settlement
> makes urgent **because there is no human principal to absorb it**.

**為什麼是優勢**：我們的起手觀察正好否認它的前提——每棵委派樹都是
human-rooted、每個節點都有人背書。**我們不是回答它的問題，是拆掉問題的
前提。** 這是 related work 能打的最強一手：引對手自己標記的缺口，指出缺口
來自它的模型假設。

**加碼**：它 §9.2 的物流案例（orchestrator → broker → carrier，carrier 在三層
之下超過費用上限、場站完全照約履行、沒有任何對手方失效）與我們的洋裝尺寸
接力同構，可以直接當共同基準情境。

---

### A3 rule zero 是唯一擋得住「對方也自稱中立」的差異化

**問題**：「中立」不能當差異點。RAILS §2 自稱
「The clearing function is **neutral**, neither a fee-earning market
participant nor a self-interested validator set」。

**差異在裁決與否**，而且對手自己講得很白：

| 系統 | 產出的裁決 |
|---|---|
| RAILS | Clearing Decision（§5.5：「RAILS **adjudicates** on evidence」；§9.8 明說要當 clearinghouse 的 decision authority） |
| AgentBound `2606.30970` | permit / review / deny |
| KYA `2605.25376` | trust score + delegation debit |
| InterSAGE `2608.13030` | trust negotiation |
| MasDrift 的 Source `2608.07556` | Allow / Confirm / Deny |
| **funduq** | **無** |

**寫法**：*neutral adjudicator vs neutral abstainer*，不是 neutral vs not。

---

### A4 能力／邊界的範圍線有獨立實證背書

**主張**（範圍線）：責任鏈處理責任邊界落在哪裡；怎麼負責任不關我們的事。
能力是 caller–callee 一條邊內部的事。

**證據**（MasDrift，已讀全文）：

- Obs. 3 標題：**`Near-zero violations do not imply preserved authorization.`**
- Obs. 4：**`Same lead, same drift, different executor`**——同一個 lead 主導
  分解，constraint loss 相同，實際越權率 **1.0% 對 24.9%**。
  **看結果只量得到執行者的能力；要量邊界必須看 handoff。**
- 結論句：**`The failure it exposes belongs to the system rather than the
  model`**、**`authorization must be carried by the architecture, not assumed
  of its models`**、**`The fix is architectural, not a question of which model
  you buy.`**

**附帶效果**：`2608.16055` 自列的「也許更好的 handoff prompting 就能解決」
caveat 被 MasDrift 打掉——**`The problem is not that users are insufficiently
explicit. Explicitness does not survive a handoff.`**（每個任務都帶明確標註的
保留邊界，約束照樣消失。）

---

### A5 攻減式能力權杖那一系有了實證反例

**MasDrift 的 Source vs Chain 對照**（兩者共用同一套 reference monitor，
只差策略來源）：

| | 越權行為 | 擋掉的必要呼叫 | 完成率 |
|---|---|---|---|
| **Chain**（沿委派血脈攜帶攻減後策略＝ AIP §3.7 / UCAN / Macaroons / Biscuit） | 消滅 | **最高 54.5%** | **最多 −36.3 分** |
| **Source**（重新錨定回原始請求，策略存放在協調圖之外） | 減少未消滅 | ≤ 3.5% | ≤ ±4.5 分 |

**機制解釋**（原句）：
> **Chain entrusts the policy to the same handoffs that lose the
> constraint**: delegating agents, unable to anticipate what downstream work
> requires, attenuate authority far past the user's boundary.

**為什麼是優勢**：這是 §2.3 對 AIP 差異化最實在的彈藥，而且是**結構性**理由
（委派者無法預知下游需要什麼），不是能力理由。

---

### A6 observed-outcomes-only 被獨立重新發現兩次

- `2608.16055` §6 三個「建議別人照抄」的方法學選擇，**第一個就是**：
  在環境端歸屬 tool call，而不是相信 agent 的自述。
- AIP `2603.24775` §7 Limitations **自己承認**：completion block 由執行方自簽，
  引自己的 Provenance Paradox 說自我宣稱的品質
  「**systematically selects the worst delegates**」。

**為什麼是優勢**：一個我們當作不變式的東西，被兩個不相干的作者在不同場景
獨立導出，其中一個還是在自我批評時導出的。

---

### A7 cancel-as-request 站在 Stop Means Stop 畫的契約線的誠實那一側

**它的論點不是「取消不可靠」，是 contract mismatch**（已讀全文）：

> …the sibling, cancellation, and timeout predicates carry the same
> behavioral bits as the measured frameworks—**documented as cooperative
> rather than implied as barriers, exactly the contract difference this paper
> isolates**.

Temporal **一樣會漏**，但它老實寫成 cooperative，所以不算違約。
funduq 把 cancel 記成請求、只記錄觀察到的結果——**同一側**。

**「為什麼不直接用 SOUNDGATE」的答案在它自己的前提裡**：SOUNDGATE 的保證
條件於 **complete mediation**，由 Linux network namespace 與 cgroup eBPF hook
在核心層強制，換作業系統就退化。那是**單主機、單信任域、對被託管程式碼有
完全支配權**的假設。遠端 provider 在不透明邊界的另一側，這個前提不成立。
**complete mediation 不可得，正是「只能請求 + 誠實記錄」被逼出來的原因，
不是保守。**

---

### A8 我們已經有一個「只記錄不評斷」的實作示範

`docs/mechanisms/quality.md`（**已實作**：`live_roster.py` 計數器）：

> What funduq does instead of verifying is count what it then observes, per
> provider, and **judge nothing**… funduq attaches **no consequence** to any
> counter. Whether a count means "avoid this provider" or "this provider's
> policy is strict" is **the reader's judgment**, made with context funduq
> does not have.

而且計的是**funduq 從自己站的位置看得見的失禮**（宣稱有空卻拒絕、逾期未答、
接了不做完、太晚回覆），**不是任務品質**。

**為什麼是優勢**：這是 A3 那條差異化的**跑得動的存在性證明**——同一個位置
（觀察每個 provider 的行為）上，別人做 trust score，我們做計數器加零推論。
在 MasDrift 缺一個 record-only arm 的情況下（見 B4），這是我們手上唯一的
實物。

---

### A8b 「所有 in-box 解法都假設掌控 effect」——同一個論證出現三次

三篇不同的論文，三種不同的修法，**三種都要求掌控 effect**：

| 論文 | 解法 | 前提 |
|---|---|---|
| Stop Means Stop `2607.14166` | 環境外部的 effect gate | complete mediation，靠 Linux namespace／cgroup eBPF |
| Stateful Governance `2608.02764` | policy-state serializability：提交前重驗政策狀態 | 它自己持有 effect |
| MasDrift 的 Source `2608.07556` | call-time reference monitor | 它攔得住每一次呼叫 |

funduq 不持有那個 effect——provider 在不透明邊界的另一側。

**為什麼是優勢**：這給了 related work 一段承重的話，而且它同時回答三個
「為什麼不直接用 X」。**那不是我們的缺陷，是場景的定義**：跨 box 的中介
沒有那個掌控，所以它的貢獻不可能是 enforcement，只能是**排序與歸屬**。
論文裡要寫成一段，不要散在三處。

**而且這條線是雙向的：in-box 的解法不轉移，in-box 的缺陷也不轉移。**
初版只寫了一半，結果立刻犯錯——把 Stop Means Stop 在框架內部量到的
replay double-execution 當成 funduq 的實作要求（那是 provider 自己盒子裡的
記帳），又把 stale authorization 當成我們解不了的難題（合約成立在 resolve
那一刻，被授權的是那一個具體呼叫，不是某個世界狀態下的結果）。
兩者的撤回記在 `retractions.md` §B2、§B3。

**判準**：讀到一篇 in-box 論文時，問「它的**發現**對我們成立嗎」，
不要問「它的**問題**我們怎麼解」。它的問題往往來自它掌控 effect 的處境。
違反這條的三次實例見 `retractions.md` §B。

---

### A9 一塊沒人佔的空地：`input-required` 的路由

**查證結果**（全部 2026-08-21）：

- **A2A #2149**（elicitations，2026-08-18 開，0 comments）：整個設計是**兩方
  的**。「Responding to an elicitation: **Resolution stays the agent's
  responsibility**」。**沒有任何鏈的概念**——client 若自己是中間人，規格沒說
  它該自己答還是轉上去。該 repo 標題搜尋 `proxy` / `intermediary` /
  `broker` / `forward` **全部零結果**。
- **MCP 2026-07-28** elicitation 規格明文：「**the protocol itself does not
  mandate any specific user interaction model**」；規範性要求全部預設 client
  有一個人類 user。
- **業界已在做選擇但沒有名字**：Cloudflare Agents SDK（2026-07-13）把行為
  **寫死成 agency mode**（純轉發給人類 UI）；沒有 handler 只能**降級**成
  不宣告 capability。
- **arXiv**：`disclosed/undisclosed principal`、`escalation routing +
  delegation`、`clarification question + multi-agent + delegation`、
  `approval + nested + agent`——2025 之後**全部零結果**。

**加碼**：兩模式模型（agency / resource owner）有硬先例可引，不是造詞——
代理法的 disclosed/undisclosed principal、IFRS 15 / ASC 606 的
principal-versus-agent 控制權判定、**RFC 8693 明確區分 impersonation 與
delegation**。

---

### A10 邊界形狀的 intro 鉤子

MasDrift intro 記載：2026 年 7 月，跑 GPT-5.6 Sol 的 Codex agent 被要求清理
一個專案目錄，**subagent 遞迴刪掉使用者大半個 home 目錄**；OpenAI 確認並
歸因於**該 agent 帶著使用者請求從未授權過的完整檔案系統存取權在運作**。

**為什麼比百分比好**：這是「權限從未被授予」，**邊界形狀，不是能力形狀**，
與 A4 的範圍線一致。

---

### A11 我們有兩個**紅的**證據，而這一類論文通常只有宣稱

**主張**：責任鏈證明的東西比它看起來的少，而我們是**跑出來**的，不是推論的。

**證據**（2026-08-25，兩支 probe 皆先寫成紅色再修）：

- `scripts/probes/probe_a_provider_can_speak_as_the_caller.py` —— funduq 依
  設計把 caller 的鏈原樣交給 provider（`forwardedProps.actorChain`，為了讓
  agent 自己驗而不是信 funduq 的摘要）。provider 掉頭用同一條鏈在門口開一個
  caller 從沒說過的 run，被接受、記在 caller 的 head 底下，而且兩列紀錄在所有
  帶權威的欄位上完全相同。**一條簽好的鏈證明來源，不證明持有。**
- `scripts/probes/probe_a_chain_can_be_branched.py` —— `caller → A → B`，B 用
  自己手上的 hop zero 重建成 `caller → B`，不偽造任何東西，驗證通過，head 不變。
  **簽名與雜湊連結證明沒有人被插入、重排、接枝，從不證明沒有人被移除。**
  抵抗的兩項也一併釘住：head 抹不掉（首跳 `prevHash` 必須為 null）、別條鏈的
  hop 接不上來。

**為什麼是優勢**：

1. 這一類論文的 threats-to-validity 幾乎都是散文。我們可以放**兩個會紅的
   腳本**，而且指出它們各自被什麼修法轉綠（presenter check / dispatch hop
   命名派工對象），以及哪一個**至今仍紅**（具名越權）。
2. 它直接回應 B4「沒人測過只記錄不裁決，包括我們」：至少「記錄了什麼、沒記錄
   什麼」現在是被測量的。
3. 它是與 RAILS、AIP 差異化時最硬的一段。兩者都以文字宣稱鏈的性質；我們可以
   說「這條性質我們試著打破過，結果如下」。

**要誠實寫進去的**：`2604.23280` 那句「no deployed protocol can
cryptographically prove which human principal authorized which specific agent
to perform which **specific action** at the third or fourth hop」——
**funduq 也不滿足它**：hop zero 綁動作是刻意延後的，所以「which specific
action」不成立。論文可以主張 broker 位置與責任路徑，**不可以**主張那一句。

**怎麼用**：evaluation 或 threats-to-validity 一節；也可作為 intro 裡
「我們如何知道自己的機制的界線」的示例。

---

## B. 已知缺口

### B1【必須先決定】`input-required` 的路由與 failure 歸屬，是同一個 bit 還是兩個？

**現況**：`docs/design-records.md`「One question per delegation edge decides
the whole tree」用的是**故障容忍**測試（*if the sub agent gets stuck or
fails, can I carry on without it?* Yes → break，且為預設）。兩模式模型用的是
**身分**測試（我是代理還是資源擁有者？）。

**兩者會分歧**：

| 情境 | 故障測試 | 身分測試 |
|---|---|---|
| 律所轉包給**離不開**的專家 | extend | extend ✓ |
| 律所轉包給**可替換**的專家 | **break** | **extend** ✗ |
| SaaS 供應商**離不開**某子處理者 | **extend** | **break** ✗ |

第三列最刺眼：故障容忍測試會**逼一個 resource owner 掀開自己的子處理者**，
與它的不透明性直接矛盾。

**為什麼重要**：拆開會動到那條承重論證——
> **Bundling intervention rights, cost and visibility is what makes the bit
> incorruptible.**

那條論證的力量正來自三者綁在一起。如果路由要跟身分走、failure 要跟故障容忍
走，就得重新論證為什麼綁定仍然不可腐化。

**誰該決定**：使用者。這是設計決定，不是查得到的事實。

---

### B2【已關閉 2026-08-21】兩模式與揭露開關不衝突

原疑慮：兩模式把「權限歸屬」與「可見性」綁在一起，而設計記錄
「Authorization is not disclosure」說它們是兩個開關。

**已解決：那兩件事指著不同方向，正交。**

- **上行**（問題浮到誰那裡、誰能答、誰付錢）→ break/extend 決定
- **下行**（答案回去時，提問者知不知道是誰答的）→ 揭露開關決定

揭露開關**只在 extend 之下有作用**（break 之下決定者就是提問者的直接上游）。
而 **extend ＋ 不揭露** 正是代理法的 undisclosed agency——現行設計已經表達
得出來，不需要新機制。

詳見 `input-required-routing.md` §2.2 第 4 條。

---

### B3【B5 的下游症狀，不是獨立項目】rule zero 的解法是責任鏈本身

**設計記錄現在寫的**（`docs/design-records.md` → Open contradictions）：

> Answering a paused A2A task rides `taskId`… knowing a task id is enough to
> answer someone else's paused question. **That is the interim marker until
> A2A v1.1's `elicitationId` lands**…

**這句話兩重錯。**

**第一重**：`elicitationId` 不會兌現。#2149 原文（2026-08-21 讀）：
clients **never required** to set it；servers **MAY** ignore it；servers
**MUST NOT** reject a message solely because it is absent or unknown。
它是**關聯提示，不是授權權杖**。

**第二重（更重要）**：指望外部依賴，而內部的解法早就寫在自己的機制文件裡。
`docs/mechanisms/responsibility-chains.md`：

> **Identifiers are never credentials: knowing a thread id is not what
> entitles a party to resume it.**
> The right to act on a paused thread becomes an explicit, **per-edge**
> property of the delegation tree.

責任鏈一落地，thread 與 run 就有自己的 owner；恢復權變成「對這條邊宣告的
持有者驗簽」，與名字是否被知道無關。**`taskId` 之所以今天是憑證，正是因為
沒有 owner 可比對——沒有別的東西可查，名字只好兼任權利。**

**所以 B3 不是獨立項目，是 B5 的症狀**：上游是責任鏈的實作，不是 A2A 的
版本進度。

**唯一該獨立做的動作**：把設計記錄那句改掉，指向責任鏈而不是 `elicitationId`
（單獨 PR，不混進論文分支）。

---

### B4 沒有人測過「只記錄不裁決」——包括我們

MasDrift 的 Source 有效，但它**同時**做了兩件我們不做的事：採用 complete
mediation（明引 Saltzer & Schroeder）、**會裁決**（Allow/Confirm/Deny）。
它的設計裡**根本沒有 record-only 這個 arm**。

**所以**：不能說 MasDrift 替我們證明了 rule zero。它證明的是「不變式必須放在
協調圖之外」——那只是我們主張的一半。

**這同時是缺口與機會**：record-only 的有效性是**沒有人測過的空白**，
包括我們自己。若論文要主張它，就需要自己的量測，而 A8 的 quality counters
是目前唯一的實物（見 B5 的規模落差）。

**誰該決定**：要不要把它變成論文的實驗貢獻，還是誠實列為 future work。

---

### B5【已關閉 2026-08-25】責任鏈其實**有實作**——是那張表寫錯了

**原本的記載**：`docs/core-components/extensions.md` 把 Responsibility
chains 那一列寫成 **not implemented — design record only**，於是這條被列為
「論文最核心的機制正好是表上唯一空白的一列」，並準備在 (a) 先實作 /
(b) 降級成 design contribution / (c) 縮小主張之間選一個。

**2026-08-25 對照程式碼後：那一列是舊的。** 機制頁上的東西幾乎都在：

| 機制頁上的說法 | 程式碼 |
|---|---|
| thread 出生時綁 head，其後只有 head 或服務它的 provider 可寫 | `repo.py` `head_key` + `ThreadMembershipRequired` |
| 回答 paused ask 需要授權集合裡的簽名 | `doors.open_run` → `identity.verify_resolution` |
| 停止一個 run 要同一份權威 | `doors.authorize_cancel` → `identity.verify_cancel` |
| session delegation certificate 把權利掛回耐久金鑰 | `identity.verify_delegation` |
| extend 是動作、break 是不動作（沒有欄位） | `extend_chain`，break 即不呼叫 |
| 責任在 run 出生時定下、resume 不更換 | `repo.reopen_run` 不碰 `head_key` / `actor_chain` |

**測試數**：`test_responsibility_chains.py` 13、`test_presenter_check.py` 7、
`test_in_process_delegation.py` 9、`test_delegation_chain.py` 5、
`test_run_keeps_its_chain.py` 3 —— **37 個測試在測那個「沒有實作」的機制**。

**真正沒實作的只有 voucher**（把金鑰翻譯成人），而機制頁本來就寫它是
deployment 自己的 IdP 才做得到的揭露。

**對論文的影響**：第 5 節的 existence proof **涵蓋核心機制**，不用在
(a)/(b)/(c) 之間選。誠實的 implemented-vs-designed 表仍然要有，但 voucher
是那張表上唯一的 designed-not-implemented 列，不是整個機制。

**教訓（值得寫進 paper 的 threats-to-validity）**：我們差一點在論文裡宣告
自己最重要的貢獻沒有實作，依據是一份沒跟上程式碼的對照表。這正是這個 repo
反覆記錄的漂移形態，而這次漂移的方向是**低估自己**。`extensions.md` 已於同日
更正。

---

### B6 rule zero 目前與程式碼矛盾

`docs/design-records.md` 自承：`thread_id` 今天**就是**憑證——
「the de facto resume credential is knowledge of `thread_id`」，而且
「Answering a paused A2A task rides `taskId`, so this contradiction now has
**money and authority** behind it rather than just read access」。

**為什麼重要**：rule zero 是 A3 差異化的支柱之一。論文若把它當既成事實寫，
會與自己的 repo 矛盾——正是 CLAUDE.md 警告的那種「文件說一套、程式碼另一套」。

**動作**：論文裡必須標成 designed-not-implemented，或先修。

---

### B7 Chain Verifiability Theorem 的張力未處理

`2603.14332` 證了：鏈上**一個**不可驗證的中間節點，會破壞其**所有**下游節點的
端到端驗證。責任鏈的 per-edge break **刻意製造**這種節點。

**需要的回答**（尚未寫成命題）：break 不是驗證失敗，而是**被宣告的邊界**——
鏈在該處終止而非斷裂，可驗證性沿著被宣告的路徑仍然成立。

**狀態**：這篇**只讀過 abstract**，命題也還沒寫。要讀全文才能確定它的定理
敘述是否真的與我們衝突。

---

### B8 A2A v1.1 還沒落地，而兩份判定可能已經過時

- **#2149 還開著**、0 comments、stacked on #2129、尚未 rebase 到 `dev-1.1`。
  我們的主張依賴它的最終語意。
- **`2606.31498` 讀的是 A2A v1.0.1**，所以它把 G5（human escalation）判成
  Absent 可能已被 v1.1 的 elicitations 改變。**這一格必須我們自己去核**——
  也是我們能對它加值的地方。

---

### B9 三個 read-before-writing 旗標仍未讀

`bibliography-notes.md` 原本標了三篇「必須全文讀」，這一輪只清掉必讀清單裡
新加的五篇，原有旗標仍在：

- `2604.00892` InterruptBench（三種中斷型態的分類法，要決定採用或對照）
- `2606.06460` Will the Agent Recuse, and Will It Stop?
- `2603.25100` From Logic Monopoly to Social Contract（可能與我們的
  mechanism/policy 框架撞題）

**加上這一輪新滾出來的**：`2604.11337`（Parsonian 制度架構，**又一份先於
我們的缺口診斷**）、`2603.03116` Corrupt Success、`2607.10059` AgentAbstain、
`2604.08588` Act or Escalate?、`2606.03034` Market for Lemons。

---

### B10 敘事風險：intro 失去「今天就在痛」的鉤子

範圍線的代價。A10 的 Codex 事件與 RAILS §12.1 是替代鉤子，但**還沒決定要用
哪一個當開場**，也還沒決定要不要保留能力數據當標示過的例證。

**誰該決定**：使用者。

---

### B11 掃描覆蓋率的已知偏差 → 見 `downstream-review-2026-08.md` §5

摘要：只掃了 arXiv（ACM DL／AAMAS／CHI／FAccT 未掃）；Semantic Scholar 的
引用圖對 2026-07 之後的 preprint 覆蓋不完整，2026-08 的重要條目全靠 arXiv
listing 才補到——**投稿前那一輪 sweep 仍然必要**；classical 條目書目未核；
PhantomPolicy 出處不明。

---

## C. 需要使用者決定的四題（依重要性）

1. **B1**：`input-required` 路由與 failure 歸屬是同一個 bit 還是兩個？
   （會動到「bundling 使 bit 不可腐化」那條承重論證）
2. **B5**：責任鏈沒有實作——先實作、誠實標示、還是縮小主張？
3. ~~**B2**~~ —— **已關閉**，兩者正交（上行 vs 下行）
4. **B4**：record-only 的有效性要當實驗貢獻，還是列為 future work？

**不需要決定、直接做的**：B3（改設計記錄裡那個不會兌現的 `elicitationId`
指望，單獨 PR）。
