# HANSARD — forensic readiness, runtime witnessing, graded attribution

- **id** — arXiv:2608.22512v1 [cs.AI]
- **who** — Sardianos, Pla, Efthymiou, Varlamis（Harokopio University of
  Athens）＋ Lagkas（Democritus）、Sarigiannidis（W. Macedonia）、
  Papadopoulos（Harokopio / Athena RC）。七位作者，三所大學＋一所研究中心，
  Horizon Europe 經費
- **when** — 2026-08-23
- **where** — https://arxiv.org/abs/2608.22512 ／ 全文 PDF 同資料夾
- **status** — `verbatim`（`pdftotext -layout` 全文，引文逐字比對）
- **read on** — 2026-09-12
- **怎麼找到的** — 查 `2605.13077` 的被引清單（Semantic Scholar，2026-09-12）。
  那篇四個月只有 3 筆引用，扣掉自引剩兩篇，**兩篇都在「追究」這一線**，
  模式設計與授權兩線是 0。本篇是其中之一。**2026-08-21 那輪 sweep 之後才
  出現，我們的筆記裡原本一個字都沒有**（B11 預告過的缺口）。

## What it is

一份**參考架構**（作者自陳 "an architecture, not a system"），把 accountability
當成生命週期屬性來處理。執行平面整個視為不可信，證據平面永不接受被捕獲內容
的指令，兩者之間只有一條 **mediation & witness boundary**，上面五個 choke
point：**W1 model call／W2 tool call／W3 agent message／W4 memory write／
W5 delegation**。事後四階段：封存擷取 → agentic causal graph → 反事實引擎
（determinism capsule 重放）→ graded attribution。

目標失效模式叫 **attribution laundering**：把一個行為攤到多個可互換的 agent
上，直到沒有任何一個是 but-for cause。

**它是目前為止跟本文最近的一篇——比 HDP 還近。** 詞彙重疊到需要逐條劃線。

## Quotes we use

> integrity alone is insufficient: **the record is produced by the suspects.**
> （Fig. 1，stage 1）

**Where** — §5。**Why** — 我們主張需要一個看得見兩條邊的第三方，理由是
自我記錄不可採。這句是同一個主張，別人寫的，而且寫得比我們短。

> (A3) cannot be defeated within one trust domain, only converted into a
> detectable inconsistency **across domains**, whence federation is an
> architectural requirement, not an optional mode.（§IV-B 前）

**Where** — §5。**Why** — 「省略無法在單一信任域內被偵測」是見證者必要性
的獨立論證，而且它推到的結論是跨域，不是更好的內部稽核。

> since no formal responsibility measure tracks human judgment reliably [16],
> HANSARD emits the evidence and the measure, **never a verdict**.（§IV-F）

**Where** — §2.3、A3。**Why** — **它也不裁決。** 見 Cautions 第一條。

> In a realistic incident the evidence is split across a model provider, an
> orchestration framework, a tool provider, and the deployer, with **MCP
> offering no audit primitive and A2A only a correlation identifier**.
> （§IV-G）

**Where** — §1、§2.1。**Why** — 協定層缺口的第三方陳述，點名 MCP 與 A2A。
與 Governance Gaps 的「zero governance extensions」互補：那篇數擴充，這篇
指primitive。

> **Standardization.** None of this composes across organizations without an
> interchange format; the PROV-DM-aligned ACG serialization is the natural
> candidate, and **the missing audit primitive in current agent protocols the
> natural starting point.**（§VI）

**Where** — §1（最強的需求面引文）。**Why** — **他們自己說下一步是協定層的
那個缺口，然後沒有做。** 這是本文的題目被一份 8 月底的架構論文寫成 future
work。比 Auditable Agents 的 OP3 更具體，因為它指名了協定。

> Determinism capsules are effective where the model is **self-hosted or
> exposes seeds**; for **closed APIs subject to silent version drift the
> intervention distribution may not be estimable at all**, and the sound
> response is to withhold the (E2) tier rather than report a meaningless
> interval.（§VI）

**Where** — §5、§7.2。**Why** — 它整套量化的前提在**閉源 API 上失效**，而
這是作者自己畫的線。跨組織正是閉源那一側。與 `refs/chain-verifiability/` 的
replay 需求同一個病根。

> A witness observes only what traverses it, where an effect achieved through
> an unwitnessed channel (an unmediated side effect, a covert encoding) leaves
> no discontinuity to expose, so **enumerating a deployment's unwitnessed
> channels is a prerequisite to any completeness claim.**（§VI）

**Where** — §8.1（這條線把誰排除在外）。**Why** — 見證者的完整性主張必須
channel-relative，這一句可以直接拿來寫我們自己的限制，而不必自己發明說法。

## 它與責任鏈的四條線

1. **測不測。** 它不下裁決，**但它出數字**——Shapley share of v(A)，加上
   synergy residual ρ（式 1），再 "lift to principals along the delegation
   chain, weighted by control and oversight"。責任鏈**兩樣都不出**。線在
   「不裁決」與「不測量」之間，不在中立與否。
2. **什麼時候。** 它是事後鑑識，物件是一次事故調查；四階段全部要重放。
   責任鏈在行為當下寫下，物件是**還在跑的那件工作**，被當事人用來升級，
   不是被調查人用來翻案。
3. **要什麼才成立。** 它要 determinism capsule（seed、模型雜湊、所有工具
   回應）＋五個 choke point 的完整中介。它自己承認閉源 API 上估不出來。
   責任鏈從不重放。
4. **跨組織怎麼辦。** 它的 federation 是**各信任域持續公布 witness log 的
   Merkle root，內容只在法律程序下揭露**——一套為訴訟保全證據的方案。
   責任鏈的鏈是**營運中的**：它在工作進行時決定升級往哪裡走。

## Cautions

- **A3 要改寫。** `strengths-and-gaps.md` A3 的表是「對手都產出裁決，funduq
  沒有」。**HANSARD 那一格也是空的**，而且是自己明說的（"never a verdict"、
  "findings, never verdicts"、"the runtime face is a sensor, not a guard"）。
  **funduq 不再是唯一的 neutral abstainer。** 還站得住的差異是上面第 1 條
  （不測量）與第 2 條（當下而非事後），必須改成逐條寫，不能再寫成
  adjudicate/abstain 的二分。這正是 `retractions.md` §A 的判準。
- **不要把它寫成競品。** 它是**需求面最強的一筆**：一份跨組織鑑識架構，
  自己說沒有協定層的 audit primitive 就組不起來。引它是為了那句
  standardization 限制，不是為了比高下。
- 它**沒有實作、沒有評估**，作者明說是架構不是系統，ρ 未校準，
  「Establishing when replay is valid is the largest single gap」。
  引它的機制時要一起講，否則等於替它背書。
- 它的 accountability 那一步 "lift to principals along the delegation chain"
  **是一條責任鏈**，但 weight 是 foreseeability 與 control——又是能力。
  與 `refs/causal-responsibility/` 同一個前提，同一個弱點。
