# 下游文獻擴查與導讀（2026-08-21）

> 這是 `bibliography-notes.md` 的補篇，不是 document of record。
>
> **方法**：以 `bibliography-notes.md` 的 21 篇 arXiv 條目為 seed，經
> Semantic Scholar Graph API 取其全部下游引用（339 篇 distinct citing
> papers），以「delegation / authority / responsibility / accountability /
> interrupt / cancel / escalation / provenance / attribution / institution /
> commitment」等詞過濾出 87 篇，再讀 abstract 收斂。另以 arXiv API 對
> 2026-05 之後的 cs.MA / cs.AI / cs.SE listing 做一輪不依賴引用關係的補查，
> 補進 seed 圖之外的新文獻。
>
> **誠實聲明**：以下每一則導讀都只根據 title + abstract（S2 與 arXiv 的
> 原文摘要），**沒有一篇讀全文**。標成「必讀」的意思是「進 introduction /
> related work 之前必須讀全文」，不是「已經讀過」。數字（benchmark 分數、
> 論文篇數）都是抄摘要的，引用前要回原文核。所有連結 2026-08-21 撈取。

---

## 0. 一句話結論

擴查最重要的結果不是多找到幾篇可引的文獻，而是**三件會改寫論文定位的事**：

1. **motivating evidence 已經有人用學術形式寫過了——但寫的不是我們這件事。**
   `2606.31498`〈Governance Gaps in Agent Interoperability Protocols〉對五個
   協定做治理面 gap matrix，其中一維就叫 **human escalation**，五個協定全部
   判 Absent。所以「授權軸在文獻中不存在」這句不能再寫。
   但它的 escalation 是**合議體把投票結果按 trigger 路由給人類主管**，
   我們的是**委派樹裡的責任路徑**——**同名不同物，是互補不是撞題**（§1.1）。
2. **同軸最近鄰是 RAILS，而它在 future work 裡把我們的題目寫成未解問題。**
   §12.1：subdelegation 鏈上的過失歸屬「leaves open」，理由是
   「**because there is no human principal to absorb it**」——而我們的起手
   觀察正是「每棵委派樹都是 human-rooted、每個節點都有人背書」。
   **我們否認它的前提，因此拆掉問題**（§1.4）。
3. **定位確認：funduq 不做治理，funduq 留下治理接得上的那個縫。**
   `2606.31498` §VII 說治理是 missing architectural layer、必須能與既有標準
   **組合**；RAILS §12 逐條列出它自己解不掉的治理問題。兩篇都需要一個下層
   基質：記錄、保存、只驗證自己的動詞、不替任何人決定。**兩份獨立文獻替我們
   陳述了需求面。** 建議升格成 discussion 的主線。

其餘新文獻大部分是好消息：cancel-as-request、interjection、per-thread
serialization 這三個原本只有哲學論證的點，2026 年都出現了實證後盾。

> **本檔在精讀過程中推翻過自己三次**（對 Governance Gaps 的威脅評估、
> AIP 的 down/up 二分、「RAILS 沒有 escalation」）。三條都已改正，
> 完整紀錄與判準見 **`retractions.md` §A**。

---

## 1. 必讀（進 related work 之前要讀全文）

### 1.1 `arXiv:2606.31498` — Governance Gaps in Agent Interoperability Protocols: What MCP, A2A, and ACP Cannot Express (v1, 2026-06-30，cs.MA)

**已讀全文 2026-08-21。** Richard Kang + Yudho Diponegoro（DoiT International，
一家雲端顧問公司），IEEE 雙欄格式、約 8 頁、無實作無評估，純規格閱讀。
文末有 AI Declaration：用 Claude 做文獻搜尋與草稿結構。

**它說什麼**：核心句是「**Yet coordination is not governance.**」五個協定
（MCP v1.1、A2A v1.0.1、ACP、ANP、ERC-8004）解決的是 identity、capability
declaration、discovery、tool access、message passing、reputation——它把這些
統稱為 coordination，並主張真正的問題不是「哪個 agent 能做這件事」，而是
「agents 該如何集體決定要相信什麼、測試什麼、做什麼」。

由三支文獻導出六維 taxonomy（G1–G6）：組織理論（Habermas 的溝通理性、
羅伯特議事規則）、MAS（Ostrom 的制度分析、Sierra 等人的 electronic
institutions）、企業治理標準（SR 11-7、ISO/IEC 42001、EU AI Act）。

| | 維度 | 定義 |
|---|---|---|
| G1 | Membership | 協定編碼准入、邀請、移除、角色指派 |
| G2 | Deliberation | 結構化論證交換，含輪次、挑戰、回應語意 |
| G3 | Voting | 偏好聚合，含法定人數、回合、立場裁決 |
| G4 | Dissent preservation | 少數立場保留在決策產出中，不被靜默丟棄 |
| G5 | **Human escalation** | 協定定義**在什麼條件下、用什麼機制把決策路由給人類權威** |
| G6 | Audit/replay | 防竄改事件日誌，可決定性地重建決策過程 |

判定結果：**G3、G4、G5 在五個協定中全數 Absent**；G1、G2 至多 Partial；
G6 只有 ERC-8004 是 Partial，而且是區塊鏈基底的副產品，不是刻意的治理稽核
設計。A2A 那一列全部是 Absent（G1 Partial），並特別指出 A2A 官方四個
extension（Secure Passport、Timestamp、Traceability、Agent Gateway Protocol）
一個都沒碰治理。

方法學上有一條很乾淨的線，值得我們借：

> Classification is based on **what the specification encodes**, not what
> could theoretically be built on top… any protocol can serve as transport
> for governance messages, but we assess whether governance semantics are
> **protocol-native**.

**對我們的三個判斷**：

**（一）威脅比 abstract 看起來小得多——它的 G5 不是我們的 escalation。**
（本檔初版只讀 abstract，把它列為最高威脅，過重了；見 `retractions.md` §A3。）
看它 §V-D 給的具體訊息長什麼樣就清楚了：

```
ESCALATE decision: arch-compliance-2026-q3
  TRIGGER: mean_confidence < 0.6
  ROUTE_TO: human:vp-engineering
  CONTEXT: [claim:c-041, dissent:d-003]
```

這是「五個 agent 對一份架構文件投票，信心不足時把**這個決策**交給 VP」。
整篇的心智模型是**合議體 / 議事廳**（它連 room、moderator、skeptic 這些
角色都定義了）。責任鏈的 escalation 是**委派樹**：誰派了誰、誰為誰背書、
出事沿哪條邊往上找、哪條邊宣告 break。同名不同物。

更關鍵的是它的 §III-A「sufficiency argument」**明確把我們最在意的東西劃到
範圍外**：「Incentive alignment/payment operates at a different architectural
layer (economic coordination, not decision governance)」——funding attribution
出局；「Reputation/trust is a prerequisite for governance… not itself a
governance primitive」——信任出局。而 delegation、authority-to-act、
interruption、cancellation、timing 在六個維度裡一個都沒有。

所以正確關係是**互補，不是撞題**。它問「一群 agent 怎麼合議」，我們問
「一條委派鏈上責任怎麼流動」。

**（二）它反而是禮物，有三句話可以直接進我們的 introduction。**

- 「Yet coordination is not governance.」——一句話的問題陳述，出自第三方，
  比我們自己下判斷有力。
- §V-A：「After 6+ months of A2A being publicly available with an active
  extension ecosystem, **zero governance extensions have been proposed or
  implemented**.」——這是我們原本想用 GitHub issue 連結證明的事，被人用
  可引用的形式寫掉了。**改引它，不要引 issue**：reviewer 通常不接受
  issue tracker 當證據。
- §VII：「We recommend the research community treat the design of governance
  protocol primitives as **an urgent open problem**.」——它明確在呼籲我們
  這種論文。§V-B 還給了 why-now：以觀察到的演化速度估計缺口會在 6–12 個月內
  被 extension 填掉，**在 ad hoc 實作變成事實標準之前**是研究社群的窗口。

**（三）不要採用它的 taxonomy，只引它的 finding。** 如果我們把 G1–G6 當
related work 骨架，就會連帶繼承合議體框架，然後被迫解釋自己為什麼 G3
（投票）、G4（少數意見）交白卷。正確做法是：引它證明「協定編碼協調而非
治理」這個共識，然後說明責任鏈處理的是它劃在 G5 之外、也不在 G1–G6 任何一格
的那條軸——委派關係中的授權與責任。順帶一提，funduq 的 rule zero（永不裁決）
使 G2/G3/G4 成為**刻意的設計選擇**而非缺口，這點要正面寫，否則看起來像是
我們沒做到。

**可以攻擊它的地方**（若需要在 related work 標示其限制）：

- 它讀的是 **A2A v1.0.1**（2026-05）。我們追的是 v1.1 dev 的 task timeline
  與 elicitations（見 memory `funduq-a2a-v11-watch`）。**它的 G5 判定可能
  已經被 elicitations 改變**——這是我們能加值、也必須自己去核的一格。
- 「necessary and sufficient」是宣稱的，不是論證出來的；它自己在 §V-F
  承認 Partial 的判定涉及主觀判斷，且 taxonomy 來自西方組織理論。
- 無實作、無評估、無使用者；作者來自顧問公司，不是這個領域的既有研究群。
  當「有人已經指出這個缺口」的引用完全夠用，但不要把它當權威分類法。

**它帶出的一整串我們漏掉的文獻**（都是「agent 社會的制度設計」這一叢，
我們原本只抓到 `2603.25100` 一個成員）：

- `arXiv:2604.11337` Governance by Design: A Parsonian Institutional
  Architecture for Internet-Wide Agent Societies（它的 [12]，用 Parsons 的
  AGIL 導出 16 格制度架構並診斷 MCP/A2A 的治理缺口——**又一份先於我們的
  缺口診斷，要讀**）
- `arXiv:2601.11369` Institutional AI: Governing LLM Collusion in
  Multi-Agent Cournot Markets via Public Governance Graph（它的 [13]，
  實測治理機制把串通從 50% 降到 5.6%）
- `arXiv:2511.03434` Inter-Agent Trust Models: Brief, Claim, Proof, Stake,
  Reputation, Constraint（它的 [17]，Hu & Rong——與 `2605.30169`
  Dissociative Identity、`2512.08737` Insured Agents 同一作者群）
- `arXiv:2603.23801` AgentRFC: Security Design Principles and Conformance
  Testing for Agent Protocols（它的 [19]，六層參考堆疊）

### 1.2 `arXiv:2607.14166` — Stop Means Stop: Measuring and Repairing the Enforcement Gap in Agent-Framework Control Primitives (v1, 2026-07-15，cs.SE)

**已讀全文 2026-08-21**（arXiv 無 HTML，讀 PDF）。Sajjad Khan，獨立研究者，
倫敦，**單一作者**。IEEE TSE 格式、約 30 頁。Artifact 齊全：probes、harness、
formal models、SOUNDGATE 實作，`reproduce.sh` 一行指令從 committed data
重算每一個 headline 數字，且**不需要 API key**；gate 已上 PyPI
（`pip install soundgate`）。六個框架在送審版匿名為 FW-A…FW-F（供應商已被
告知；artifact 檔名 `e2e_structural_langgraph.txt` 洩漏了 FW-A 是誰）。

**它的論點不是「取消不可靠」，而是 contract mismatch。** 這個區別很重要，
我在只讀 abstract 時把它講鬆了（見下方修正）。它的原話：

> It is an **implied contract**—implied by the primitives' names, by framework
> documentation, and by practitioner guidance—**not promised as a formal
> specification**—and our claim throughout is a contract mismatch: the
> semantics operators are led to assume are stronger than the semantics the
> primitives deliver.

也就是說：問題不在停不下來，而在**框架用命名與文件暗示了 barrier 語意，卻只
交付 cooperative 語意**。它拿 Temporal 當對照組，一句話點破：

> …the sibling, cancellation, and timeout predicates carry the same
> behavioral bits as the measured frameworks—**documented as cooperative
> rather than implied as barriers, exactly the contract difference this paper
> isolates**.

Temporal 的取消行為跟那些框架**一樣會漏**，但它老實寫成 cooperative，所以
不算違約。**funduq 站在誠實那一側**：我們把 cancel 記成請求、只記錄觀察到的
結果。這比「取消不可靠」精準得多，也是我們該引的角度。

**測到的四類違反**：

- **sibling leak**（核心發現）：approval gate 與一個有副作用的動作在同一個
  執行步驟裡是兄弟節點時，gate 只暫停自己那一支，**兄弟的副作用在暫停期間
  照常執行**，事後的 reject 無力回天。在**五個出貨 pre-execution gate 的框架**
  上重現（第六個只有 post-hoc review，無 barrier 可違反），橫跨**四種執行
  模型**（Pregel/BSP supersteps、event bus、message-passing fan-out、單一
  model turn 內的 parallel tool calls）與**兩種語言 runtime**——所以不是單一
  實作的 bug
- **replay double-execution**：resume 點之前的副作用執行兩次
- **cancellation orphan**：取消後 worker thread 上的副作用仍然落地
- **timeout zombie**：逾時回報之後副作用才完成

**最漂亮的一組數字（randomized structural sweep）**：1000 個 seeded 隨機
workflow 跑真實 FW-A runtime，結果**完全決定性**——與 gate 同一 superstep 並行
的副作用**577/577 全部在暫停期間執行**；gate 的後代節點副作用 **0/363**；
排在後面 superstep 的並行副作用 **0/331**。也就是說洩漏窗口精確地就是「引發
暫停的那一個 superstep」。這種「把機制講到可以預測每一格」的做法，是我們
probe 腳本該學的形態。

**活體端到端（Experiment A）**：真模型驅動未修改框架，**1200 次未中介的 run
有 215 次在暫停期間執行了副作用；每個會產生該 plan shape 的 arm 裡
P(leak | emitted) = 1.00；P(leak) 最高 0.44；加上 gate 之後 0/1200。**

**它誠實到會傷害自己論點的地方（值得整套抄）**：在自然任務上模型其實不太踩雷。
τ-bench episode 上模型傾向「平行讀、序列寫」，所以它明說 the gap is
**latent rather than prevalent**——「a severe failure that is **rare by model
habit rather than absent by construction**」。但接著它把問題轉了個方向問：
當任務**本身**就含兩個獨立的後果性步驟時呢？答案很利：五種真實多副作用操作
（deploy-and-notify、delete-and-deploy、merge-and-announce…）各跑 100 次，
**GPT-4o 在 500/500 次全部把兩個後果性動作放進同一個平行 turn**。而且
τ-bench 自己的 gold action sequence 裡，**115 個 retail 任務有 45 個、50 個
airline 任務有 15 個**至少需要兩次後果性寫入。結論：**這是任務結構的性質，
不是模型不肯平行化**。它還把「這些任務是特意挑的、是條件機率不是母體比率」
講在明面上。

**⚠️ 範圍要講準**（初版把這篇說成「證明取消不可靠」，過度；見
`retractions.md`）：這篇同時證明了 **barrier 是做得到的**——SOUNDGATE 在
complete mediation 之下
擋掉全部四類違反，形式驗證（Verus + TLA+/TLC 窮舉到 7.5×10⁷ 狀態 + TLAPS +
Loom）加 1.2×10⁷ 次 differential conformance 零分歧。所以 reviewer 會問：
**「既然 SOUNDGATE 證明停得住，funduq 為什麼只能請求？」**

**答案在它的前提，而那個前提正是我們的場景所否定的。** SOUNDGATE 要求
**complete mediation**——每一條有副作用的路徑都必須向 gate 提交；它靠 Linux
network namespace 與 cgroup eBPF hook 在**核心層**強制，並明說換作業系統就
退化成 placement discipline 加 linter。這是一個**單主機、單信任域、對被託管
程式碼有完全支配權**的假設。funduq 的 provider 在**不透明邊界的另一側**、
可能在別的組織、別的資料中心；我們無法把它的 syscall 塞進我們的 cgroup。
**complete mediation 不可得，正是 funduq 只能請求而必須誠實記錄的原因。**

這一段要寫成 related work 裡的一個明確段落，因為它同時做到三件事：
(1) 承認 barrier 在 intra-box 可以做到、不假裝我們比它強；
(2) 用它自己的前提說明為什麼跨 box 做不到；
(3) 讓「只記錄觀察到的結果」從保守變成**被逼出來的正確設計**。

**還可以抄的體例（對我們的 genre 最有價值的部分）**：

- **claim scope 一次講清並貫徹到底**：C1（量測）無條件成立；C3（修補）
  以 complete-mediation 契約為條件，且全文每一個 “closes” 都定義為
  「suppresses the mediated effect under that condition」
- **Non-goals, stated once**：一次列完不提供什麼（injection 偵測、非網路
  外洩通道、多階段 API 的原子性、**人類決策本身的品質與時效**、金鑰派送）
- **每個 probe 的 violation predicate 事先固定**（fixed a priori），避免
  事後挑條件
- **形式驗證與程式碼之間的關係講得很小心**：「refinement **evidence**, not a
  mechanized refinement proof」——這正是我們寫 T1–T4 時該有的用詞紀律
- `reproduce.sh` 從 committed data 重算每個數字、無需網路

**可攻擊處**：單一作者、獨立研究者、非同行評審版本；框架匿名使外部複驗較難
（雖然 artifact 公開）；SOUNDGATE 的 soundness 全部條件於 complete mediation，
而該契約在真實部署中靠的是 placement 紀律加一個 best-effort linter；
評估是單節點。

### 1.3 `arXiv:2608.16055` — Governance at the Boundary: How Agent Decomposition Degrades Policy Compliance (v1, 2026-08-17，cs.AI)

**已讀全文 2026-08-21。** Bowen Li（LinkedIn）+ Guojun Wang（Uber），但署名用
個人 gmail，看起來是業餘時間的獨立作品。短篇（約 8 頁 + 附錄），benchmark
與 harness 開源。**這次沒有翻案**，先前 abstract 級的摘要事實上都正確；但有
一項必須補上的限定（見「引用時務必附上 n」）。

**它問的問題**：既有 benchmark 問「agent 有沒有完成任務」，它問
**「有沒有在政策內完成」**——該升級時有沒有升級、該棄權時有沒有棄權、
有沒有留下可稽核的軌跡。然後問一個沒人問過的問題：**把一個 agent 拆成多個
component，會不會損害它的可治理性？**

**實驗設計乾淨在哪**：唯一的自變數是**拓撲**。三個 arm 共用完全相同的工具、
政策語料、ROLE / CONDUCT prompt block，只有描述拓撲的那一段不同：

| Arm | 架構 | 邊界數 | context 隔離 |
|---|---|---|---|
| D0 | 單一 ReAct 迴圈 | 0 | 完整 |
| D1 | pipeline：intake → research → decide | 2 | 每階段只看得到上一次 handoff |
| D2 | orchestrator + scoped subagents | 2/round-trip | 嚴格 + 工具範圍限制 |

「A component sees a tool result only if it made the call—**context cannot
leak across a boundary**.」100 個 KYC/AML 任務變體、兩個模型、626 個 episode。

**核心結果**（distance 2、conditional on discovery）：

| 模型 | D0 | D1 | D2 |
|---|---|---|---|
| Qwen2.5-32B | 0/16 (0%) | 9/16 (56%) | **22/26 (85%)** |
| gpt-4.1-mini | 0/27 (0%) | 1/30 (3%) | 1/18 (6%) |

**⚠️ 引用時務必附上 n。** 我先前說「85% 是 introduction 第一段可以直接引的
數字」——成立，但**分母是 26**。gpt-4.1-mini 那兩格更是 1/30 與 1/18。
裸引百分比而不給 n，是自找 reviewer 的第一發子彈。

**對我們最有價值的一句話**（整輪掃查裡最好的一句）：

> **The component that violates is not the component that failed.**

配對的鏡像任務把機制講得很透：kyc-0004 掉的是風險訊號 → **under**-escalation；
kyc-0005 掉的是**免責**發現 → **over**-escalation。同一個 summarizer 行為、
同一種資訊流失，兩個相反的治理後果，**而且承擔後果的都不是出錯的那個
component**。這正是責任鏈要解的形狀：出事時「找誰」與「誰錯」是兩件事，
需要一條被宣告的路徑，而不是事後從 trace 推。

順帶一提，這也順手殺掉「那就一律升級」這個廉價解法——benchmark 兩個方向都
計分，always-escalate 不是可行策略。

**第二個好發現**：D2 在 100 個 episode 裡問出 27 個 trigger fact（D0 只有
16 個），**但接著弄丟了其中 22 個（81%）**。

> The architecture that is **better at finding** policy-relevant information
> is **worse at carrying it**.

**一個排除競爭解釋的控制組**：D0 分別在 P0（政策全文在 context 裡）與 P1
（按需檢索）之下跑，三個模型都沒有系統性差異。
「**Decomposition, not policy access mode, drives the effect.**」

**它自己就在呼籲我們要做的東西**（§6 Discussion）：

> Structured handoff protocols—**defining what a summary must contain and
> what it is not permitted to omit**—are a natural intervention, and one that
> **current practice largely ignores**.

**方法學上三個它建議別人照抄的選擇，其中第一個就是我們的不變式**：

1. **在環境端歸屬 tool call，而不是相信 agent 的自述**（＝ funduq 的
   observed-outcomes-only，被獨立地重新發現一次，可以當旁證引用）
2. 每個驗證步驟 replay 狀態，而不是只檢查最終狀態
3. 過度升級與升級不足都計分

**怎麼回應「等模型變強就沒事了」——正確答案是不進入這場辯論**（定位見
§4.5）。這個反駁預設我們主張了某個失敗率；我們沒有。責任鏈處理的是**責任
邊界落在哪裡**，不是任何人把責任履行得多好。**即使衰減率是 0%，
「誰為這條邊背書」仍然是同一個問題**，因為它問的不是有沒有人出錯。

所以這篇對我們的價值**不是那些百分比**，是這一句：

> **The component that violates is not the component that failed.**

這句話是邊界命題，不是能力命題——它成立與否跟模型多強無關。百分比只是讓
邊界的未定義狀態變得可見的顯影劑。**引百分比反而把我們拖進能力戰場**，
那裡我們沒有立場也不需要立場。它 §6 要的 structured handoff protocol 同理：
規定摘要必須帶什麼、不准漏什麼，是在**宣告邊界**，不是在提升能力。

**必須誠實標示的弱點**（引用時要一起講，否則被抓）：

- 分母極小（見上）
- **governed success 只有 8/596 = 1.3%**。它自己列在 Limitations 第一條：
  「a model that passes D0 is needed to anchor the headline chart」。
  benchmark 幾乎沒有正例，這是真的問題
- 只有兩個模型，一個還是 GPTQ-Int4 量化的本地 Qwen2.5-32B；都不是 frontier
- 腳本化模擬器 + 子字串觸發，它承認「measures phrasing alongside governance」
- 它自己列了三個 caveat：未證實在 frontier 規模成立、未證實可推廣到
  KYC/AML 以外、**未證實不能靠更好的 handoff prompting 解決**。最後這條
  看起來對我們不利，其實不然——只要我們不把論證架在失敗率上。prompting
  能改善的是履行責任的品質，動不到「這條邊的責任歸誰」。這正是 §4.5 那條
  範圍線存在的理由

**它帶出的四篇 2026 治理 benchmark，我們一篇都沒有**：

- `arXiv:2603.03116` Beyond Task Completion: Revealing **Corrupt Success** in
  LLM Agents through Procedure-Aware Evaluation — 任務完成度與程序合規之間的
  落差「large and systematic」，在 τ-bench 上量的
- `arXiv:2607.10059` **AgentAbstain**: Do LLM Agents Know When Not to Act? —
  配對任務（該動 vs 該忍），8 種 abstention 情境的分類法
- `arXiv:2604.08588` **Act or Escalate?** Evaluating Escalation Behavior in
  Automation with Language Models — 把升級建模成不確定下的決策，五個領域的
  真人決策紀錄；發現各模型的隱含門檻差異極大且**與架構或規模無關**，
  自我信心估計則各有各的失準方式
- PhantomPolicy（把政策事實藏出 context）——arXiv 上查無此標題，待確認出處

### 1.4 `arXiv:2606.08790` — RAILS: Verification-Native Clearing for Agentic Commerce (v1, 2026-06-07，cs.AI)

**已讀全文 2026-08-21。** Adrian de Valois-Franklin + Alex Bogdan
（Evolutionairy AI，Toronto）。約 40 頁，形式模型 + 威脅模型 + 評估 +
reference implementation（合成資料集，20 tasks / 48 scenarios，committed
model-response cache，單一指令離線重現）。份量遠大於前面兩篇。

**它說什麼**：核心區分是 **performance failure ≠ counterparty failure**。

> An agent can hold valid authorization, settle a valid payment, to an
> honest merchant who delivers exactly what was asked, and still leave the
> user harmed, **because the agent asked for the wrong thing**.

授權對、付款對、對手方誠實履約，使用者還是受害——因為 agent 要錯了東西。
現有任何 rail 都抓不到這個。它把一筆交易拆成六個不可互換的問題：
**Authorization**（准不准做）、**Execution**（實際做了什麼）、
**Performance**（有沒有滿足被委派的義務）、**Attribution**（出事是誰造成的）、
**Loss**（損害是什麼）、**Settlement**（後續的財務/聲譽/程序後果）。
現有基礎設施各答一塊：授權協定答第一題、tool log 答第二題、benchmark 答第三題、
資安工具答第四題、保險答第五六題。「零件都在，**綁住它們的生命週期不在**。」

七個 primitive：Obligation Object（把自然語言意圖編譯成已簽署、機器可清算的
契約）、Evidence Envelope、Verification Mesh（多類 verifier：receipt、
constraint、semantic、human arbiter…）、Clearing Decision、Settlement
Instruction、Clearing Passport（跨交易可靠度紀錄）、Finality Rules。
形式性質只有一條，但可對規格證偽：`Emit(S) ⟹ cls(B) ⪰ φ_O`——**不會有財務
重大的結算，建立在低於該義務所宣告 admissibility floor 的證據上**。

**RAILS 是有 escalation 的**（本檔初版說它沒有，錯，見 `retractions.md`
§A2）：§6.3 定義兩個 escalation 側迴圈——mesh 達不到信心門檻時**升級給
human arbiter**，以及 appeal window（對 PROVISIONAL 結算提異議，退回
Verification 重新裁決）。性質與我們不同，見下面第 5 點。

**為什麼必讀（真正的原因）**：**它在 §12.1 Future Work 裡把我們的題目寫成
未解問題，而且給的理由正好被我們的立論前提否定。**

> The subdelegation case of Section 9.2, in which one agent hires another
> that hires a third, **leaves open the assignment of fault along that chain
> when the output is unsound**, a problem autonomous agent-to-agent
> settlement makes urgent **because there is no human principal to absorb
> it**.

我們論文的起手觀察正是相反的：**每一棵委派樹都是 human-rooted，而且每個節點
都有人背書**。所以我們不只是回答它的 open problem，是**否認它的前提**——
「沒有人類 principal 可以承接」在 funduq 的模型裡不成立，因為責任鏈保證每條邊
的兩端都指得出人。這是 related work 能做的最強一手：引用對手自己標記的缺口，
然後說明那個缺口是它的模型假設造成的。

它 §9.2 對這個問題**已經給了一半的答案**，必須據實引述：每次 subdelegation
綁定一個新的 Obligation Object `O'`，由委派方（在自己的 `O` 之下）與接收方
共同簽署，**obligation hash 的鏈就是 fault-attribution chain**，每一環產生自己
的 Clearing Decision 與 Passport delta。它舉的例子跟我們的「洋裝尺寸接力」
同構：物流 orchestrator → broker → carrier，carrier 在三層之下超過了
orchestrator 的費用上限並訂下不可逆的碼頭時段，**場站完全照約履行、沒有任何
對手方失效**，損害是三層之下的授權違反，而「誰的 passport 承擔」今天沒有標準
答案。

**差異化（讀完全文後的版本）**：

1. **「中立」這個詞不能當差異點——它也自稱中立。** §2 明寫「The clearing
   function is neutral, neither a fee-earning market participant nor a
   self-interested validator set.」真正的差別不是中立與否，是**裁決與否**：
   RAILS 是中立的**裁決者**（§5.5 自己的話：「RAILS **adjudicates** on
   evidence」；§9.8 更直接：它要當 clearinghouse 的 decision authority，
   「owns the risk-policy and settlement-decision surface」，只把資金託管
   留給下游）。funduq 是中立的**非裁決者**。差異化要寫成
   *neutral adjudicator vs neutral abstainer*，不是 neutral vs not。
2. **人在模型裡的地位相反。** RAILS §6.3：human arbiter「is itself a verifier
   in role-tag terms (r=human), and its output re-enters Adjudication as
   **one more verifier vote**」。人被降維成 mesh 裡的一票。責任鏈把人放在
   樹根與每條邊的背書位置。這是哲學分歧，不是功能差異，值得單獨一段。
3. **前置條件天差地別。** RAILS 每一跳都需要一個雙方簽署、帶 admissibility
   floor、acceptance criteria 機器可讀的 Obligation Object。它自己在 §12
   劃了兩邊的界：義務太主觀就 clear 不了（應標為 human-review-required）、
   義務太容易機器驗證則 clearing 沒有加值——**它只在中間那條帶子上有用**。
   責任鏈不要求義務可機器判定，只要求關係被宣告。
4. **取消語意不同。** RAILS 的 `CANCELLED` 是「parties **agree** to abort
   before settlement」——雙方合意。它沒有單邊 cancel、沒有 mid-flight 停機
   請求、沒有「請求了但對方不停」這個狀態。我們的四行 outcome table 在它的
   狀態機裡無處安放。
5. **escalation 的性質不同（取代初版那句錯的）。** RAILS 的 escalation 是
   **裁決內部的**：mesh 信心不足 → 升級給人類仲裁者投一票。責任鏈的
   escalation 是**責任路徑的**：誰為這個 agent 背書、出事沿哪條邊往上找、
   哪條邊被宣告 break。前者問「這次判不出來，找誰判」，後者問「這個
   participant 出事，找誰負責」。

**它也替我們證明了『留治理切入口』這個定位。** §12 最後一條 Limitations：

> **Governance questions remain open.** Who registers verifiers? Who
> certifies templates? Who arbitrates Passport disputes? Who has standing
> to challenge a Clearing Decision after the appeal window closes? These
> are governance questions, not protocol questions, and they are not
> settled.

RAILS 需要治理、明說自己不提供。`2606.31498` 說治理是缺失的架構層、要求它能
與既有互通標準**組合**而非各自重造。兩篇合起來就是 funduq 定位的需求面證據：
**我們不做治理，我們留下治理可以接上的那個縫**——記錄、保存、只驗證自己的
動詞，不替任何人決定。這一段建議直接寫進 discussion。

**可以攻擊它的地方**：評估全為合成資料（它自己說「Synthetic coherence is not
field realism」）；soundness 是**有前提的**（三個 precondition 都是 §10 的攻擊
目標）；§12 承認 clearing 可被 Goodhart、Passport 可能變成不公平標籤、
admissibility floor 是當事人的政策不是 RAILS 的保證；並且明說
「**No novelty is claimed for conditional settlement as such**」——它的新意
只在「證據可採性分級 + 可證偽的 soundness + 中立」三點上。


### 1.5 `arXiv:2608.07556` — MasDrift: Benchmarking Authorization Preservation Across Multi-Agent Architectures (v1, 2026-08-18)

**已讀全文 2026-08-21**，讀完後從 §2「應讀」升格到必讀。理由：**在 §4.5 的
範圍線之下，這是目前最強的盟友**——它整篇都在邊界語域，而且明確把「這是系統
的問題不是模型的問題」寫成結論句。

**它的框架就是我們的框架**：

> Delegation can improve task completion through decomposition and
> parallelism, but **a delegated goal and its authorization boundary are not
> the same object**.

> **Principle 1 (Authorization preservation).** Delegation may copy or narrow
> authority already granted by the user, but it may not create, widen, or
> prematurely activate authority. **Task readiness, role expectations,
> inter-agent agreement, and successful completion of prerequisite work do
> not themselves constitute user authorization.**

> An action has **valid authorization lineage** only if its authority can be
> traced to `u` through the handoff path.

最後這句是 down-flow 版的 actor chain，跟 Lampson 的 speaks-for 同源；
Principle 1 的第二句更是純粹的邊界命題——**跟任何模型多強完全無關**。

**威脅模型刻意良性**：沒有 prompt injection、沒有惡意 agent、沒有污染觀察、
沒有串通。「Any authorization failure is therefore **endogenous**: it arises
from decomposition, restatement, and delegation.」600 個可執行任務、八個
生產力領域；每個任務環境同時暴露「準備工作所需的工具」與「使用者保留待核准的
工具」（要你草擬轉診信，就同時看得到傳真那支工具），**壓力來自把工作做完的
慣性，不是來自對手**。

**比百分比好用得多的 intro 鉤子**（而且是邊界形狀的真實事件）：2026 年 7 月，
跑 GPT-5.6 Sol 的 Codex agent 被要求清理一個專案目錄，**subagent 卻遞迴刪掉了
使用者大半個 home 目錄**；後續還有弄丟正式資料庫的回報。OpenAI 確認了該行為，
並歸因於**一個 agent 帶著使用者的請求從未授權過的完整檔案系統存取權在運作**。
這是「權限從未被授予」的故事，不是「模型不夠強」的故事。

### 這篇最重要的四句話（全部在 §4.5 的線內）

1. **`Near-zero violations do not imply preserved authorization.`**
   （Obs. 3 的標題）
2. **`Same lead, same drift, different executor.`** 同樣由 Sol 主導分解，
   Sol–Nano 與純 Sol 的 constraint loss 一樣高，但實際越權率是 **1.0% 對
   24.9%**。也就是說：**看結果只量得到執行者的能力；要量邊界必須去看
   handoff。** 這正是使用者定的那條線，被獨立實證了一次。
3. **`The problem is not that users are insufficiently explicit. Explicitness
   does not survive a handoff.`** MasDrift 每個任務都帶明確標註的保留邊界，
   **約束照樣消失**。這一句直接把 `2608.16055` 自列的那個「也許更好的
   handoff prompting 就能解決」caveat 打掉。
4. **`Upgrading the model buys restraint at the last hop and nothing across
   the hops before it, so a system can become more capable, cheaper, and less
   authorized at once.`** 接著是：**`The fix is architectural, not a question
   of which model you buy.`**

再加一個定位數字：evaluator 把 Sol 的約束流失**92% 定位在第一次 handoff**——
lead 在任何 worker 看到之前重述任務的那一刻。

### 機制對照：Source vs Chain（AIP 那條路線的實證反例）

兩個防禦實例共用同一套策略表示與 call-time reference monitor（三種裁決
Allow / Require-Confirmation / Deny），**只差在策略的來源**：

- **Source**：策略由原始使用者請求編譯而成，**存放在協調圖之外**，每次呼叫
  重新錨定回源頭。「A handoff therefore cannot create authorization
  evidence.」
- **Chain**：策略沿委派血脈攜帶，可保留或收窄、不得放寬——**就是 AIP §3.7
  與 macaroons / UCAN / Biscuit 那一系的做法**。

結果（Obs. 3）：

| | 越權行為 | 擋掉的必要呼叫 | 完成率變化 |
|---|---|---|---|
| **Chain** | 消滅 | **最高 54.5%** | **最多 −36.3 分** |
| **Source** | 減少但未消滅 | ≤ 3.5% | ≤ ±4.5 分 |

只看越權率，Chain 完勝；把效用一起看，結論反轉。原因講得很漂亮：

> **Chain entrusts the policy to the same handoffs that lose the
> constraint**: delegating agents, unable to anticipate what downstream work
> requires, attenuate authority far past the user's boundary, so drift is
> converted into over-restriction rather than eliminated.

**攻減式能力權杖那一整系（AIP、UCAN、Macaroons、Biscuit）第一次有了實證反例**，
而且反例的機制是結構性的：委派者無法預知下游需要什麼，只好過度收窄。
這一段是 §2.3 AIP 差異化最實在的彈藥。

### 但要誠實：這篇也可以被拿來打我們

Source 之所以有效，是因為它**在協調圖之外**持有不變的策略——這個架構位置
就是 funduq 的位置。但 Source 同時做了兩件我們不做的事：它**採用 complete
mediation**（明引 Saltzer & Schroeder），而且它**會裁決**（Allow / Confirm /
Deny）。所以有人可以說「這篇證明了應該要有一個會裁決的中央權威，也就是
RAILS / AgentBound 那一路，不是你們」。

**我們能主張的、也只該主張的，是更窄的那一半**：不變式必須放在協調圖之外，
不能交給 handoff 攜帶。至於那個外部元件是**裁決**（Source）還是**只記錄**
（funduq），MasDrift 沒有測——它的設計裡根本沒有「只記錄不裁決」這個 arm。
這是一個真實的空缺，**要在 related work 明說，不要假裝它替我們證明了 rule
zero**。反過來說，這也正好是我們可以主張的實驗性貢獻方向。

**其他限制**（引用時附上）：全部英文、八個生產力領域、合成的工具中介環境，
沒有 coding agent 與開放網路；主要防禦實驗中每個 Require-Confirmation 都被
**自動核准**，所以殘餘違規量的是「自主授權」而非實體攔阻（有另跑一組全部
拒絕的補充上界）；over-disclosure 與 constraint-loss 兩個指標**來自單一 LLM
judge**；scale-up 條件下深度與 handoff 數、工具暴露量共變，架構效果只能在
bundle 層級識別。


---

## 2. 應讀（強相關，至少讀 intro + 貢獻列表）

| 條目 | 為什麼相關 | 落在哪一節 |
|---|---|---|
| **`arXiv:2608.07556` MasDrift: Benchmarking Authorization Preservation Across Multi-Agent Architectures** (2026-08-18) | 600 個良性任務，比較 single-agent / centralized / decentralized，量「授權邊界有沒有隨委派一起傳下去」。關鍵結果對我們極有用：**兩種防法的對照**——「re-anchor 到原始 user request」在每個模型設定下都降低越權（代價 1.6 分完成率），而「沿 delegation chain 傳遞衰減後的 policy」（＝ AIP 那條路線）反而擋掉該做的工作，最多損失 36.3 分。這是對「沿鏈傳遞攻減後 policy」這條路線的**實證反例**，也就是 AIP §3.7 的做法 | §2.3（AIP 差異化的實證彈藥） |
| **`arXiv:2608.09025` Context Is Not Authority: Structured Runtime Governance for Financial Market Agents** (2026-08-10) | 標題就是我們的論點之一。SAGE-Fin 提「authority-handoff contract」，把**被提議的 effect**（而不是它的文字）當作 runtime 控制對象；記錄 coverage debt；要求 exact-artifact receipt；state 改變後**重查**先前授權。「evidence and workflow progress cannot substitute for effect authority」這句可以直接引 | §2.3 / §2.5 |
| **`arXiv:2608.02764` Stateful Governance for Concurrent Agentic Systems** (2026-08-03) | 定義 **stale authorization** 為核心失效模式，提 **policy-state serializability**：已提交的 effect 必須能被解釋為對「effect 發生前一刻的 policy state」是被授權的。MasuGate 用 PostgreSQL 原型驗證。這是我們 per-thread serialization 問題的正規化對應物，比 `2606.17182` 更貼近「授權」而非單純併發 | §2.5（與 2606.17182 並列） |
| **`arXiv:2608.15242` LongRCA Bench: Diagnosing Responsible Roles and Root Causes in Long-Horizon Agent Failures** (2026-08-15) | 1140 條真實失敗軌跡（無注入錯誤），人工標注**責任角色**與最早的決定性根因步驟。中位數 145 步，最強 baseline 只有 13.2% exact root-step accuracy；他們的方法 RCTA 透過追溯 **handoff instruction** 達到 51.1% 責任角色準確率。這是「事後從 trace 推責任」有多難的量化證據——正是「責任要在協定層事前宣告、而非事後從 log 推」的論證後盾 | §2.6 或獨立一節 |
| **`arXiv:2606.09751` Collaborative Human-Agent Protocol (CHAP)** (2026-06-08) | 明講「MCP 標準化工具存取、A2A 標準化 agent 互通，**兩者都沒有定義人與 agent 共同進行可歸責工作的共享工作區**」。核心是把「人類覆寫/編輯」這個判斷時刻變成一級記錄。與我們的 interjection / 兩入口分類法直接對話；是 §2.4 目前最接近的協定層近鄰 | §2.4（必列） |
| **`arXiv:2605.13077` Counterfactual Reasoning for Causal Responsibility Attribution in Probabilistic Multi-Agent Systems** (2026-05-13) | 把 MAS 建成 concurrent stochastic multi-player game，定義回溯式反事實責任，用 **Shapley value** 分配並證明滿足 fairness / consistency，再以 Nash equilibrium 求 responsibility-aware 的穩定策略。這是**古典 MAS 社群對「責任」既有的形式化定義**，我們的 reviewer 大概率來自這一群。必須處理：我們用「責任鏈」這個詞而**不做**責任量化分配，要說明為什麼（我們給的是 escalation path 這個結構物，不是 blame 的量測——中介永不裁決） | §2.2（與 Singh commitment 並列） |
| **`arXiv:2605.10481` Safe Multi-Agent Behavior Must Be Maintained, Not Merely Asserted: Constraint Drift in LLM-Based MAS** (2026-05-18, position) | 提出 **constraint drift**：約束在通過 memory、delegation、communication、tool use、audit、optimization 時流失/扭曲/弱化。主張「fresh, inherited, enforceable, auditable」四性。是 2608.16055（實證）與 2606.22528（實證）的 position 版本，適合當一句話的傘狀引用。也引了 AIP | §2.3 |
| **`arXiv:2606.22528` Governance Decay: How Context Compaction Silently Erases Safety Constraints** (2026-06-21) | context compaction 會靜默刪掉治理約束：政策在 full context 時違規率 0%，compaction 後升到 30%（某些模型 59%）。1323 個 episode。這是「約束放在 agent 的 context 裡＝不可靠，必須放在 agent 外的協定層」最乾淨的實證 | §2.3 / §2.5 |
| **`arXiv:2608.12654` SteerBench-Work: A Benchmark for Agent Steering at Action Boundaries** (2026-08-12) | 量 pre-commit 邊界的 proceed / hold 決策，106 個以真實事故為錨的場景。失敗高度不對稱：模型**錯誤扣住**已授權且證據齊全的工作佔 28.1%，**錯誤放行**不安全工作只有 1.0%。對我們的 interjection 設計有直接含意——過度保守才是主要成本 | §2.4 |
| **`arXiv:2608.13030` InterSAGE: The Secure and Verifiable Interoperability Protocol for An Internet of Agents** (2026-08-13) | 四層（Persistent Identity / Discovery / Trust Negotiation / **Accountability**），明講「既有協定定義了 agent 怎麼交換訊息，但沒定義它怎麼證明身分、授權、宣稱的能力，或**委派之後的可歸責性**」。用 kernel-mediated 密碼學稽核軌跡（不上鏈）。比較了 50+ 個既有努力——**它的比較表是我們 related work 的現成起點**。同時引了 AIP，是 AIP 的直接下游 | §2.1 / §2.3 |
| **`arXiv:2606.04990` From Agent Traces to Trust: A Survey of Evidence Tracing and Execution Provenance in LLM Agents** (2026-06-03) | 把 execution provenance 定義成 agent 執行的 typed graph，evidence tracing 是它在證據支持關係上的投影。process-level accountability 的 survey——我們「記錄」那條主張的 survey 級引用 | §2.6 |
| **`arXiv:2605.30169` Dissociative Identity: Language Model Agents Lack Grounding for Reputation Mechanisms** (FAccT 2026) | 主張 LM agent 在本體上是「解離的」（模型、system prompt、工具政策、記憶皆可變），因此缺乏 identifiability / predictability / credibility / rehabilitability 的基礎，聲譽機制無法成立。這對我們有兩面：一方面支援「不要建 reputation，只建可驗證路徑」；另一方面**質疑 provider identity 本身的意義**，要正面回應 | §2.6 |

---

## 3. 分節補充（可直接併入 `bibliography-notes.md`）

### §2.1 協定與 survey
- `arXiv:2606.31498` Governance Gaps in Agent Interoperability Protocols — **見 §1.1，優先度最高**
- `arXiv:2602.11327` Security Threat Modeling for Emerging AI-Agent Protocols: MCP, A2A, Agora, ANP（16 citations，2026 年被引最多的協定安全分析）
- `arXiv:2607.23884` A Comparative Study of MCP and A2A（筆記已有，補：S2 上 0 citations，51 refs，可能不必列為「empirical state of the art」）
- `arXiv:2606.07150` From Privacy to Workflow Integrity: Communication-Graph Metadata — A2A/MCP 保護內容但暴露通訊圖；observer 能在 workflow 完成前搶先動作。若論文談 visibility，這是相鄰威脅模型

### §2.2 古典 MAS
- `arXiv:2605.13077` Counterfactual Responsibility Attribution（Shapley）— **見 §2**
- `arXiv:2607.09766` Norm Enforcement for AI Agents — 簡單的規範執行機制會被錯位 agent 利用；robust 機制需要「隨時間估計可靠度 + 對重犯遞增懲罰」。跟 Esteva 的 electronic institution 血脈同源，是它的 LLM 時代版本
- `arXiv:2511.17332` Agentifying Agentic AI（筆記已有）— 補：S2 只有 2 citations，且兩篇都是 fairness 方向，不是我們這一路。當「向 MAS 社群握手」的引用仍成立，但別高估它的中心性

### §2.3 委派、授權、身分
- `arXiv:2608.07556` MasDrift — **見 §2，AIP 差異化的實證彈藥**
- `arXiv:2512.06914` SoK: Trust-Authorization Mismatch in LLM Agent Interactions（survey 200+ 篇）— 提 Belief-Intention-Permission 框架，主張各種威脅共同根因是「動態信任狀態與靜態授權邊界失同步」。SoK 級引用
- `arXiv:2605.08460` When Child Inherits: Modeling and Exploiting Subagent Spawn — 子 agent 繼承：不安全的記憶繼承、弱資源控制、post-spawn stale state、**improper termination authority**。最後一項跟我們的取消語意直接相關
- `arXiv:2603.14332` Governing Dynamic Capabilities — 證了 **Chain Verifiability Theorem**：鏈上任一個不可驗證的中間 agent 會破壞其所有下游節點的端到端驗證。這條定理跟責任鏈的 per-edge break/extend 有直接張力，**要正面處理**
- `arXiv:2606.30970` AgentBound: Behavioral Governance — 三個獨立權威（delegated authorization / owner-signed behavioral constitution / site action contract）保守合成，產生密碼學可驗證的 governance receipt
- `arXiv:2605.25376` KYA (Know Your Agents) — only-tighten composition algebra、跨 human/agent/service account 的統一 principal schema、**two-axis delegation attribution**（對高風險 delegate 收靜態溢價 + 對實際失當收 runtime debit）。跟我們的 funding attribution 是同一個問題的不同解
- `arXiv:2607.21325` Cryptographically Verifiable Agent Authorization — 形式化 identity binding / request binding / execution context 三者的結構分離
- `arXiv:2608.04292` BIND: Binding Biometrics with AI Agent Identifiers — 把人類生物特徵綁進 agent ID 與授權範圍，建立「人類確實授權過」的不可否認證明。是 responsibility chain 最上游那個端點的一種實作
- `arXiv:2605.14859` Do Coding Agents Understand Least-Privilege Authorization?（AuthBench）— 模型自己推不出最小權限邊界，且更多推理只會讓它更一致地錯（model-specific authorization attractor）。支援「授權不能交給模型自我判斷」

### §2.4 HITL、混合主動、可中斷性
- `arXiv:2607.14166` Stop Means Stop — **見 §1.2**
- `arXiv:2606.09751` CHAP — **見 §2**
- `arXiv:2608.12654` SteerBench-Work — **見 §2**
- `arXiv:2607.26300` AgentGUI: An Interface for Observing and Steering Long-Running AI Agents — 多個並行長跑 session 的觀察與介入介面，含使用者研究。是 interjection 的 UX 端證據
- `arXiv:2608.17834` AdaLens: Interactive Storyline for Monitoring and Steering Long-Running Agentic Data Analysis — 同上，另一個實作點
- `arXiv:2607.07097` Operational Reframing and Approval-Framed Delegation in Multi-Agent LLM Safety — 拆解「pipeline effect」為三個機制，其中一個是 **executor 在暗示已獲核准的 delegation prompt 下變得更順從**。這是「核准這件事必須可驗證、不能靠 prompt 裡的措辭」的直接證據

### §2.5 持久執行與交易語意
- `arXiv:2608.02764` Stateful Governance / policy-state serializability — **見 §2**
- `arXiv:2608.11632` Beyond Memory: A Transactional Continuity Kernel for Long-Lived AI Agents — 把 continuity 定義成「未中斷、經授權的 accepted branch head 血脈」；activation transaction 重新驗證 ownership、pre-state authority、freshness、effect uniqueness，記一個 disposition（Commit / Reject / **Quarantine** / **Defer**）。**Defer 這個 disposition 跟我們的 queue 模型可以互相參照**
- `arXiv:2608.13900` Agentic Transaction: Towards ACID-Compliant Agent Systems
- `arXiv:2607.23929` MemTX: Transactional Belief Commit for Stateful Agent Memory
- `arXiv:2606.08049` SKILL.nb: Selective Formalization and Gated Execution for Durable Agent Workflows
- `arXiv:2606.22528` Governance Decay — **見 §2**
- （待查）Bonded Recourse for Smart-Contract Settlement of **Compensable Agent Side Effects** — S2 上沒有 arXiv ID，但主題正對 Sagas 補償語意那條線，值得追出處

### §2.6 agent 經濟、發現、信任
- `arXiv:2606.08790` RAILS — **見 §1.4，最近的近鄰**
- `arXiv:2606.03034` Capability Advertisement as a Market for Lemons — 把 MCP/A2A 的能力廣告當成檸檬市場：品質隱藏、宣稱廉價，於是好壞供給者無法區辨。經濟學三帖藥（signaling / screening / reputation）在現行協定中一個都沒有。**這是 funduq 作為中立中介的經濟學正當性論證**，比技術論證更容易說服非技術 reviewer
- `arXiv:2512.08737` Insured Agents: A Decentralized Trust Insurance Mechanism — 專門的保險 agent 為營運 agent 押保證金換保費，透過 TEE 取得隱私保護的稽核權。與 funding attribution 同一個問題空間的另一種解
- `arXiv:2605.30169` Dissociative Identity（FAccT 2026）— **見 §2**
- `arXiv:2605.23218` Foundation Protocol: A Coordination Layer for Agentic Society — graph-first 協調層，統一 agent / tool / resource / human / institution / organization，含 metering、receipt、settlement，policy/provenance/audit 為一級概念，且明講「wrap and bridge 既有協定而非取代」。**定位與我們高度重疊**，要讀
- `arXiv:2606.03163` / `2606.03161` OpenAgenet (OAN) Yellow/White Paper — trust-governed resource identity and discovery
- `arXiv:2608.18232` Contracting for LLM Delegation: Moral Hazard in Technology and Effort Choice — principal-agent 框架擴到「agent 同時選模型與 effort（token budget）」；推導最優線性合約與觸發技術切換的 threshold reward share，並用 open-weight 模型在 MATH / MMLU-Pro 上校準。**這是 funding attribution 最正統的經濟學基礎**，責任鏈的 cost 那一支若要形式化，這是起點

### 新增一節建議：§2.7 責任歸屬與稽核
現有 §2.1–§2.6 沒有一格放得下 LongRCA Bench / Correct Is Not Governed /
execution provenance survey 這一群。它們構成一條獨立的線：**事後從 trace
重建責任有多難**——正是「事前在協定層宣告責任鏈」的反面論證。
- `arXiv:2608.15242` LongRCA Bench（見 §2）
- `arXiv:2608.12761` Correct Is Not Governed: Provenance Integrity in Agentic Workflows — 定義 **governed execution**：決策、完成、與對變更的反應都由可檢視的 provenance 支持。Matrix 是 deterministic causal-state layer，記錄 authority 與 fact 相依、驗證完成證據、選擇性作廢受影響的工作。**誠實地報告了一次失敗**（role-separated transfer 下完整性契約過度阻擋），這種寫法值得學
- `arXiv:2606.04990` From Agent Traces to Trust（survey）
- `arXiv:2512.18561` Adaptive Accountability in Networked MAS — 記錄密碼學可驗證的互動 provenance、偵測分布改變點、以因果影響圖歸責、施加成本有界的介入。古典 MAS 那一側的完整 pipeline

### §7 聯邦先例
維持 SMTP / XMPP / Matrix / ActivityPub。可補 `arXiv:2607.18242`
（AI Tool Discovery at Scale: All You Need is DNS）作為 domain-based
discovery 的當代對照——跟 memory 裡 `funduq-anp-applicability-conditions`
那條「funduq 擁有無 domain 那一層」的論證直接相關。

---

## 4. 對論文定位的修訂建議 → 已結算到 `strengths-and-gaps.md`

本節初版列了五條建議，其中：

- 「motivating evidence 換敘事」「rule zero 是唯一擋得住『對方也自稱中立』的
  差異化」「範圍線：模型能力不在考慮範圍內」→ 已成為
  **`strengths-and-gaps.md` 的 A1／A3／A4**，附原句出處。
- 「down-flow vs up-flow 整條撤掉」「bibliography-notes 有兩處要改」
  → 已執行完畢；撤回的理由與判準見 **`retractions.md` §A1**。
- 「`2603.14332` 的 Chain Verifiability Theorem 要正面處理」→ 仍未處理，
  列在 **`strengths-and-gaps.md` B7**（該篇只讀過 abstract）。

**這一節不再維護，以 `strengths-and-gaps.md` 為準。**

---

## 5. 這次掃查的覆蓋率與偏差

**（這一節講的是「這次的掃查」本身；論文層級的缺口清單在
`strengths-and-gaps.md`。）**

- **精讀進度**：六篇讀完全文——AIP `2603.24775`、Governance Gaps
  `2606.31498`、Stop Means Stop `2607.14166`、Governance at the Boundary
  `2608.16055`、RAILS `2606.08790`、MasDrift `2608.07556`，均 2026-08-21。
  **§1 的必讀清單已清空**；`bibliography-notes.md` 原有的三個
  read-before-writing 旗標仍未讀（`2604.00892`、`2606.06460`、`2603.25100`）。
  六篇裡五篇各修正了一句我們寫過的話——**這正是「必讀」清單存在的理由**
  （十三條撤回的完整紀錄見 `retractions.md`）。
- **只掃了 arXiv。** ACM DL／AAMAS 2026 proceedings／CHI／FAccT 沒掃；
  `2605.30169` 已經在 FAccT 2026，暗示那一側還有東西。
- **下游查詢有結構性偏差。** Semantic Scholar 的引用圖對 2026-07 之後的
  preprint 覆蓋不完整（多篇新論文 `citationCount = 0` 但明顯已被討論）。
  §3 裡那些 2026-08 的條目**是靠 arXiv listing 補到的，不是靠引用圖找到的**
  ——投稿前那一輪 sweep 仍然必要。
- **`bibliography-notes.md` 的 pre-writing checklist 第 1、3 項沒動**：
  古典條目的書目細節未核、seed 的 arXiv 版本號未記。這次只補了第 4 項
  （listing sweep）的一部分。
- **PhantomPolicy 出處不明**（`2608.16055` 引它，arXiv 查無此標題）。
