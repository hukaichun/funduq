# Governing Dynamic Capabilities — the Chain Verifiability Theorem paper

- **id** — arXiv:2603.14332v2 (cs.CR)
- **who** — Ziling Zhou（單一作者，arXiv 頁未列 affiliation）
- **when** — v1 2026-03-15，v2 2026-03-19（本檔讀的是 v2）
- **where** — https://arxiv.org/abs/2603.14332 ／ 全文 PDF 同資料夾
  `2603.14332v2.pdf`（28 頁）
- **status** — `verbatim`（arXiv HTML v2 全文，18.8k 字讀完；引文逐字比對）
- **read on** — 2026-09-12

## What it is

從 **capability-context separation**（transformer 內部分不出工具定義與使用者
context，但 orchestration 層兩者安全語意完全不同）推出三個 Agent Governance
Requirements：**G1 capability integrity**、**G2 behavioral verifiability**、
**G3 interaction auditability**。證兩個結構性定理（Bounded Divergence、Chain
Verifiability），給兩套 crypto-agnostic 實作（Ed25519/SHA-256；BBS+ 與
Groth16 DV-SNARK），加一份 9 模型 7 供應商的 reproducibility 研究。

**這篇的 G2 是「重跑模型、比對輸出」**——不是委派紀錄，是計算忠實性。
記住這一點，下面整個判斷都靠它。

## B7 的結論要翻案：我們打錯定理了

`strengths-and-gaps.md` B7 寫的是「per-edge break 刻意製造 Chain Verifiability
Theorem 說的那種不可驗證節點」。**讀完全文後，這句不成立。**

> **Definition 8 (Chain Verifiability Depth).** CVD(vₙ) = min{ j ≥ 1 : v_j is
> an agent with ρ_{v_j}.level = *none* }

而 ρ 是 **Definition 6 (Reproducibility Commitment)**，`level ∈ {full,
statistical, none}`，full 的定義是
`∀(context, seed): O_v(context,seed) = O_v^replay(context,seed)`。

**也就是說：他們的「不可驗證節點」＝一個不承諾自己的模型可被重跑的 agent。**
與「鏈在這裡不再延伸」是兩個不同的物件。責任鏈的 break 不會把任何節點的
*計算* 變得不可重跑。Theorem 2／4 要能碰到我們，前提是我們主張 end-to-end
behavioral verification——而 rule zero 與 observed-outcomes-only 正好是不主張
它。**B7 原本的張力是誤讀，不是未處理的張力。**

## 真正的鄰居是 Property 2，不是 Theorem 2

同一篇 §5.5 有第二個、對稱的結果，那個才貼著我們：

> **Definition 12 (Chain Auditability Depth).** CAD(vₙ) = min{ j ≥ 1 : record
> for v_{j-1} → v_j **absent from ℒ** }

> **Property 2 (Chain Auditability).** If CAD(vₙ) = k < n, then for all i ≥ k:
> 1. **Provenance gap**: the auditor cannot trace v_i's output back to the
>    trust anchor v₀, because the input v_k received from v_{k-1} is
>    unrecorded.

> interaction auditability is a chain property: a single missing interaction
> record along an execution path breaks forensic reconstruction for all
> downstream nodes on that path.（§5.5）

**Where** — §4.2（延伸是宣告，沉默是邊界）與 §5（為什麼需要一個見證者）。
**Why** — 這是 break 的代價被別人用他們的詞寫出來的樣子，而且**對我們有利**：
CAD 的分界線畫在 `absent from ℒ`。**一個被宣告的 break 不是 absent**——邊界
本身是一筆紀錄。所以 Property 2 在我們身上讀出來的是「追溯止於被宣告的邊界」，
正是 §4.2 要講的話，不是反例。要寫的命題因此不是反駁，是**對齊**：在他們的
詞彙裡，責任鏈的 CAD 等於鏈被宣告的長度，而不是 0。

**但有一條紀律**：這條對齊只在我們**從不主張** break 之後還有 end-to-end
provenance 時成立。draft §4.2／§5 任何一句暗示「鏈外仍可追溯」的話都會把
Property 2 變成反例。送出前掃一次。

## 可以拿來用的第二件事：他們自己承認見證者是集中的

> **Ledger operator trust.** The current G3 instantiation assumes a
> centralized operator honest for availability and ordering; record integrity
> is enforced cryptographically (bilateral signatures, hash chains)
> regardless.（§8.7）

**Where** — §5。**Why** — §5 目前靠 Pagnia & Gärtner 的 TTP 不可能性結果撐
「為什麼需要一個見證者」，而那條 lineage 的 TTP 是**裁決者**（見
`bibliography-notes.md` §2.3 的警告）。這一篇提供了一個**不裁決的**見證者
先例——它的 ledger 只保 integrity 與 ordering，不判誰對——而且作者自己把
集中性寫成已知限制。比 fair-exchange 更近，而且不會把 adjudicator 帶進門。

另外 §5.3 的 commitment-only 儲存（ledger 只存 hash，鑑識時才揭露原文）是
對「記錄 vs 揭露」問題的另一個答案，與我們的 per-edge visibility 是可比的
對照組，不是競品。

## Cautions

- **它的 G3 要求 bilateral signatures on every edge，而且是單一 ledger ℒ。**
  這是跨信任邊界拿不到的東西，也正是我們的保證比較弱的原因。要引它就要把
  這一句一起寫出來，否則審稿人會問「他們做到了為什麼你們不做」。
- **不要把 Theorem 2 寫成「與我們衝突但被我們回答了」。** 它根本沒瞄準我們。
  硬去回答一個不存在的攻擊，只會讓審稿人以為我們沒讀懂 ρ 的定義。
- 它的 adversary model 假設 **non-agent node 不會被攻陷**（§8.7 明講），而
  v₀ 是 non-agent trust anchor。我們的 broker 也是 non-agent node，所以這個
  假設兩邊一樣，不構成差異化材料。
- 數字都附 n 了（9 models／7 providers／5–20 agent pipelines），但
  **CharMatch 0.987 vs 0.169 那個 5.8× 是模型決定論的量測，與責任無關**。
  不要因為好看就引。
- 單一作者、cs.CR、沒有部署證據（評估是自建 pipeline）。份量與 AIP 同級，
  引它是為了定理不是為了背書。
