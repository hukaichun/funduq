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

原出處 `docs/mechanisms/quality.md` 已隨 `5503c91` 刪除；引文釘在
[歷史](https://github.com/hukaichun/funduq/blob/c3bbc5c65fa0ced3520d2858c94fd9fed70a81ab/docs/mechanisms/quality.md)。
**實作仍在，而且是行為證據**：`broker.quality()` / `kyok.quality()`、
`live_roster.py` 的 per-identity 計數器——而 code 裡**沒有任何東西讀這些
計數器來做決定**，這就是 judge nothing 的可驗形式（引文原文）：

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

### A12 可查的界線是「有兩個簽名的那條邊」——別人的定義逼出來的，他們沒寫

**主張**：跨組織能被查證的事情有一條硬界線，而它不在「能不能記錄」，
也不在「有沒有裁決權」。**界線在：比較的兩端，有沒有一端不在被檢查者
手裡。**

**怎麼推出來的**（`refs/audita/`，2026-09-12 讀全文）。Audita 的 Definition 3
把義務述詞 `Φ_p` 的定義域鎖死在 (i) p 自己簽章的訊息與 p 登記過的缺席，
(ii) 這些訊息的已認證輸入前緣；明文排除 ground truth 與第三方對 p 的說法。
**這一條使義務檢查跨得過信任邊界**——定義域裡沒有一樣東西在 provider 內部。
它是三篇裡唯一不需要重放、不需要能力模型的一段。

但論文沒有寫出它成立的條件。用他們自己的兩個實例對照就看得出來：

- **成立**：彙總者「輸出等於已認證輸入的宣告彙總」。**輸入是上游簽的**，
  被檢查者偽造不了。一端在對手手上，比較是真的。
- **不成立**：任何「我夠努力了」形狀的義務——我查了幾個候選、我看了多久、
  我考慮過哪些。**搜什麼、記什麼，兩端都在被檢查者手裡。** 沒有對手方簽名，
  於是它是自我認證的，通過與否與實際工作無關。

**推論（要寫成論文裡的一句話）**：content-determined 的義務只在**一條被
雙方簽過的邊**上有意義。一方**內部**的盡職程度沒有對手方，因此不可查——
對任何 record-confined 的稽核者都一樣，**包括我們**。

**running example（比抽象講法有效，建議直接用）**：
使用者說「找最便宜的機票，超過 1000 就不要，航空公司不好或體驗不佳的也跳過」。

| 使用者說的 | 登記得了嗎 | 為什麼 |
|---|---|---|
| 超過 1000 不要 | ✅ | 對自己輸出的可計算述詞 |
| 最便宜 | ⚠️ 一半 | 只能是「我已認證輸入裡最便宜」；**搜尋範圍夠不夠判不了** |
| 跳過體驗不佳的 | ❌ | 關於世界的判斷，Definition 3 明文排除 ground truth |

**而使用者真正在乎的是第三列**，第一列是一行 SQL 的 WHERE 條件。
**義務層的覆蓋範圍，與雇用 agent 的理由成反比。**
使用者心裡真正的標準更糟：「至少要做得比我自己好」——相對於一個不存在的
反事實，連使用者自己事前都說不出它，**不是一個述詞**。

**為什麼這是優勢而不是自曝其短**：

1. 它把 §3 的區分從宣稱變成推導。「責任問的是誰被攪進來，不是誰該賠」
   現在有個機械理由：**被攪進來是一條邊上的兩個簽名，是事實；做得好不好
   沒有第二個簽名，不可查。**
2. 它給 §8.1 一個乾淨的範圍線，而且**同時適用於我們**——不是「他們做不到
   我們做得到」，是「這條界線畫在哪裡，界線外沒有人做得到」。這正是
   `retractions.md` §A 要求的逐項差異化。
3. Audita 的 Theorem 4 是同一件事的定理形式（任何補完缺口的判準等於要替
   被稽核的任務判定輸出對不對），所以這條推論有別人的定理背書，不是我們
   自己的立場宣告。

**不可以寫成**：「Audita 假裝一切都能算成一個數字」。他們沒有——Theorem 4
證的正是不能，而且他們用實驗選擇了不判輸出正確性（不看答案的變體 0.159
勝過看答案的 0.170）。該批評的是**包裝**（摘要的「把爭論變成計算」、物理
傷害的動機），不是機制。誤寫會直接撞上 `retractions.md` §A。

---

### A13 我們這一端的門檻,量出來了(2026-09-12,出處全是程式碼與測試)

**為什麼要有這一條**：A12 主張「加強保證就會抬高門檻」。要能這樣講,
**我們自己那一端的門檻必須寫得跟別人一樣清楚**,否則「幾乎不用事前準備」
只是廣告詞。以下每一列的出處都是程式碼或測試,不是任何一頁文件
(`retractions.md` §E′ 的規矩)。

**兩個素未謀面的組織,在第一次呼叫之前必須各自準備什麼**：

| | 責任鏈 | Audita | HANSARD |
|---|---|---|---|
| 金鑰 | 各自產一對 Ed25519。**無 CA、無簽發機構** | 各方持簽章金鑰(A3) | PKI + TEE 中的金鑰 |
| 事先談好的詞彙 | **無** | **義務登記簿 D**(正文未給格式) | 整備側寫:通道列舉、capsule、門檻 |
| 共同設施 | **無**。收的那道門要能說出「這條線握有哪把金鑰」——**持有證明,不是身分** | 一條共同被記錄的匯流排 + 指定的 recorder | 五個 choke point 的中介 |
| 事故**之前**必須完成 | **無**。傳輸層的持有證明是本來就在做的事 | A1／A2／A3 成立 | **封存整備側寫;事後補不回** |
| 金鑰↔真實主體 | 在 wire 的准入層,**funduq 看不到也不需要** | 隱含於 A3 的金鑰保管 | PKI + TEE |
| 模型要能重放 | **不需要** | **需要**(釘死權重、確定性服務、序列重放) | 需要(determinism capsule) |
| 驗一條鏈要什麼 | **只要那條鏈** | 重放環境 | 重放環境 + 跨域 federation |

**最右上那格是真的便宜,而且可以指著程式碼講**：

- `verify_chain(chain)` 的**唯一參數就是那條鏈**。每一跳自帶公鑰,簽章對著
  自帶的那把驗;`verify_exp: False`,**不看時鐘**;不查註冊表,不連網路。
  〔`funduq-contract/funduq_contract/chain.py`〕
- **一跳剛好兩個 claim**:`actorPublicKey` 與 `prevHash`,沒有 subject、
  沒有時間。〔`test_a_hop_is_exactly_two_claims`〕派工時多一個
  `dispatchedTo`。
- 握手是**雙向挑戰-回應,沒有憑證機構**:funduq 對該金鑰發一張 ticket,
  對方簽 (funduq 的身分金鑰, ticket, 自己的 nonce),funduq 驗完再簽回去,
  所以對方也驗得了 funduq。〔`funduq/funduq/core.py` 的 open/connect〕
- 指紋是 TOFU:**第二把金鑰搶不走已存在的指紋**。
  〔`test_a_second_key_cannot_take_an_existing_fingerprint`〕

**門口那一步要求的是持有證明,不是身分**:

1. **一條鏈本身不帶權威。** 鏈**最後一跳的簽章金鑰**,要等於**這條線上正在
   說話的那把金鑰**。就這樣。
   〔`test_a_chain_carries_authority_when_its_presenter_authenticated`、
   `test_a_chain_presented_by_anyone_else_is_refused`〕
2. 那一把從哪裡來,**核心不問**。`verify_caller` 只收一個 `presenter_key`,
   由傳輸層交進來;A2A 那側是 `presenter_key_of(context)` 這個掛勾,測試的
   註解寫著「**它怎麼建立那把金鑰是它自己的事**」。mTLS 給你一把,SDK 連線
   的挑戰-回應給你一把,funduq 不在乎是哪一種。
   〔`funduq/funduq/doors.py`、`test_a2a_request_handler.py`〕
   **沒有附預設實作不是缺口,是不問身分的結論。**
3. **金鑰對到哪個真實主體,在 wire 的准入層決定,funduq 看不到也不需要。**
   所以這裡沒有 CA、沒有註冊表、沒有事先談好的詞彙。
4. 所以「離線就驗得完」**只對鏈的內部一致性成立**——證明這串跳是由持有那些
   金鑰的人依序簽的。要主張權威,還要那一步持有證明。

**跨 funduq 不需要 funduq 有腳。** 核心裡沒有任何 HTTP client
(`test_core_is_network_free`),但走路的一直是 agent:provider 在跑一個 run
的時候自己打到另一個 funduq 的 A2A 門,鏈就放在 A2A 訊息的
`metadata.actorChain` 裡,那道門自己驗、自己比對。**funduq 是門,不是編排器。**

**所以精確的說法是**(這句就是論文要主張的那一句):
**責任鏈把事前協商壓到「各自有一把自己產的金鑰」加「你的傳輸層本來就在做的
持有證明」,代價是它只證明經過了誰的手,不證明任何一手做得對不對。**
再往上走一格——要認證因果——就要求釘死的模型與共同的重放環境;再上一格——
要指名一方——要求事故發生前就簽好的跨域承諾。**每一格都同時買到更多、
也要求更多。**

---

## B. 已知缺口

### B1【必須先決定】`input-required` 的路由與 failure 歸屬，是同一個 bit 還是兩個？

**現況**：design-records「One question per delegation edge decides
the whole tree」（頁面已隨 `5503c91` 刪除，引文釘在
[歷史](https://github.com/hukaichun/funduq/blob/c3bbc5c65fa0ced3520d2858c94fd9fed70a81ab/docs/design-records.md)）
用的是**故障容忍**測試（*if the sub agent gets stuck or
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

**活文件現在寫的**（原出處 design-records 已隨 `5503c91` 刪除、引文釘在
[歷史](https://github.com/hukaichun/funduq/blob/c3bbc5c65fa0ced3520d2858c94fd9fed70a81ab/docs/design-records.md)；
**同一個主張搬進了 `docs/integration-contract.md` 的「Current gaps, stated
plainly」，逐字**：「Who may do so is gated by nothing more than knowing the
id… (a recorded contradiction, not a position). When A2A v1.1's
`elicitationId` lands, **that is the marker this interim rule yields to**」）：

> Answering a paused A2A task rides `taskId`… knowing a task id is enough to
> answer someone else's paused question. **That is the interim marker until
> A2A v1.1's `elicitationId` lands**…

**這句話兩重錯。**

**第一重**：`elicitationId` 不會兌現。#2149 原文（2026-08-21 讀）：
clients **never required** to set it；servers **MAY** ignore it；servers
**MUST NOT** reject a message solely because it is absent or unknown。
它是**關聯提示，不是授權權杖**。

**第二重（更重要）**：指望外部依賴，而內部的解法不只寫了，**已經實作**
（bound thread 的回答走 `identity.verify_resolution`、rev 16 起簽 ask
實例）。機制頁原文（頁面已隨 `5503c91` 刪除，引文釘在
[歷史](https://github.com/hukaichun/funduq/blob/c3bbc5c65fa0ced3520d2858c94fd9fed70a81ab/docs/mechanisms/responsibility-chains.md)）：

> **Identifiers are never credentials: knowing a thread id is not what
> entitles a party to resume it.**
> The right to act on a paused thread becomes an explicit, **per-edge**
> property of the delegation tree.

責任鏈一落地，thread 與 run 就有自己的 owner；恢復權變成「對這條邊宣告的
持有者驗簽」，與名字是否被知道無關。**`taskId` 之所以今天是憑證，正是因為
沒有 owner 可比對——沒有別的東西可查，名字只好兼任權利。**

**所以 B3 不是獨立項目，是 B5 的症狀**：上游是責任鏈的實作，不是 A2A 的
版本進度。

**唯一該獨立做的動作（2026-09-03 更新目標）**：design-records 沒了，但那句
話活在 `docs/integration-contract.md`——把「yields to `elicitationId`」改成
指向責任鏈（單獨 PR，不混進論文分支）。

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
| ~~session delegation certificate 把權利掛回耐久金鑰~~ | **已於 2026-09-02 隨 funduq#238 移除**——授權是 policy，policy 歸 wire 側；權利直接由耐久金鑰簽 |
| extend 是動作、break 是不動作（沒有欄位） | `extend_chain`，break 即不呼叫 |
| 責任在 run 出生時定下、resume 不更換 | `repo.reopen_run` 不碰 `head_key` / `actor_chain` |

**測試數（2026-09-03 重數）**：`test_responsibility_chains.py` 12、
`test_presenter_check.py` 7、`test_in_process_delegation.py` 9、
`test_delegation_chain.py` 5、`test_run_keeps_its_chain.py` 5 ——
**38 個測試在測那個「沒有實作」的機制**。（`test_delegation_chain.py` 與
`test_in_process_delegation.py` 名字帶 delegation，測的是活著的 actor chain
`extend_chain`/`verify_chain`，不是被移除的 certificate——不要因名字誤刪。）

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

### B6 rule zero 與程式碼的矛盾【2026-09-03 對 main 重推：證據搬家，矛盾縮小】

**原證據**：design-records 自承 `thread_id` 今天**就是**憑證——
「the de facto resume credential is knowledge of `thread_id`」、
「Answering a paused A2A task rides `taskId`, so this contradiction now has
**money and authority** behind it rather than just read access」。該頁已隨
`5503c91` 刪除（引文釘在
[歷史](https://github.com/hukaichun/funduq/blob/c3bbc5c65fa0ced3520d2858c94fd9fed70a81ab/docs/design-records.md)）——
但**自承沒有消失，搬進了活文件**：`docs/integration-contract.md`「Current
gaps, stated plainly」逐字寫著「Who may do so is gated by **nothing more
than knowing the id**, the same capability-by-identifier trust every thread
reference carries today (**a recorded contradiction, not a position**)」。

**對 2026-09-03 的 main 重推，矛盾只剩 unbound 路徑**：綁了 chain 的
thread，寫入限 head/provider（`ThreadMembershipRequired`）、回答 pause 要
`identity.verify_resolution`（contract rev 16 起簽 ask 實例，proof 對別的
ask 永不驗過）、cancel 要 `verify_cancel`——rule zero 在 opt-in 之處是
**實作了的**（38 tests）。沒綁 chain 的 thread 維持 open behavior，
`taskId` 依然是 de facto 憑證。funduq#238 又拆掉了 delegation certificate
（製造權力的憑證＝policy，歸 wire 側），方向一致。

**動作（取代原來的二選一）**：**不必**標 designed-not-implemented，也不必
「先修」。誠實的寫法：identifiers-never-credentials 是 **opt-in 機制的
性質**——鏈在，識別子就不是憑證；鏈不在，開放行為是**被記錄的預設**
（契約文件自己標明 recorded contradiction），不是被忽略的洞。B6 於是不再
undercut A3：record-only 的中介對不 opt-in 的呼叫方本來就無權利可給。

---

### B7【已關閉 2026-09-12】Chain Verifiability Theorem 沒有瞄準我們

**原本寫的**：`2603.14332` 證了鏈上一個不可驗證的中間節點會破壞所有下游節點的
端到端驗證，而 per-edge break 刻意製造這種節點，所以欠一個命題。

**讀完全文後，這條不成立。** 該篇的「不可驗證節點」由 Definition 8 定義為
`ρ.level = none`，而 ρ 是 Definition 6 的 **Reproducibility Commitment**
（`full` ＝ `∀(context, seed): O_v(context,seed) = O_v^replay(context,seed)`）
——**是「這個 agent 承不承諾自己的模型可被重跑比對輸出」**，屬於它的 G2
behavioral verifiability，不是委派紀錄。break 不會讓任何節點的計算變得不可
重跑。定理要碰得到我們，前提是我們主張 end-to-end behavioral verification，
而 rule zero 與 observed-outcomes-only 正好是不主張它。撤回記在
`retractions.md` §H1，形態是**只讀 abstract 就判斷定理瞄準誰**。

**真正的鄰居是同一篇 §5.5 的 Property 2 / Definition 12（Chain
Auditability）**，而且對我們有利：

> CAD(vₙ) = min{ j ≥ 1 : record for v_{j-1} → v_j **absent from ℒ** }

分界線畫在 `absent`。**被宣告的 break 不是 absent**——邊界本身是一筆紀錄。
Property 2 在責任鏈上讀出來是「追溯止於被宣告的邊界」，正是 §4.2 要講的話。
要寫的不是反駁命題，是**用他們的詞彙對齊**。

**隨之而來的一條紀律**：這條對齊只在我們**從不主張** break 之後還有
end-to-end provenance 時成立。draft §4.2／§5 任何一句暗示「鏈外仍可追溯」的
話都會把 Property 2 從同義複述變成反例。**送出前掃一次**。

**附帶的收穫，動到 §5**：該篇 §8.7 自己承認「the current G3 instantiation
assumes a centralized operator honest for availability and ordering」，而那個
ledger 只保 integrity 與 ordering、**不判誰對**——**一個不裁決的見證者先例**。
§5 目前靠 Pagnia & Gärtner 的 TTP 不可能性結果撐必要性，但那條 lineage 的
TTP 是**裁決者**（見 `bibliography-notes.md` §2.3 的警告）。這一篇更近，而且
不會把 adjudicator 帶進門。**§5 的靠山該不該換，是新的待決項。**

收據（含全文 PDF）：`refs/chain-verifiability/`。

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
