# Audita — certified auditing and causal attribution

- **id** — arXiv:2608.22160v2 [cs.AI]
- **who** — Zhixu Du（一作，構思方法、做實驗、寫稿）＋ Yiran Chen（指導），
  Duke University ECE。兩位作者，一個實驗室
- **when** — v2 2026-08-29
- **where** — https://arxiv.org/abs/2608.22160 ／ 全文 PDF 同資料夾
  ／ **程式與資料 MIT 授權公開**：https://github.com/ZhixuDu/audita
- **status** — `verbatim`（`pdftotext -layout` 全文 24k 字＋ Extended Data，
  引文逐字比對；Supplementary Note 的證明只讀敘述未驗算）
- **read on** — 2026-09-12
- **怎麼找到的** — 同 `refs/hansard/`：查 `2605.13077` 的被引清單。兩篇外部
  引用之一，2026-08-21 sweep 之後才出現

## What it is

一個**事後稽核層**：把每一則 agent 之間的指令變成可驗證的簽章紀錄，再在
上面跑一個帶證書的因果歸責引擎。排版是 Nature 系列的體例（Author
contributions／Data availability／Extended Data），**有完整實作、有自建
benchmark（CulpaBench）、有 5 條定理、MIT 開源**。

**這是這一線目前最紮實的一篇**，而且它站在跟我們相反的立場：它認為帳算得出來，
並且把「算得出來的條件」寫成了假設。

證據單元（Definition 1）：一則訊息是 `m = (a, π, C, φ, σ)`——作者、內容、
**引用集 C（它所依據的那些訊息的雜湊）**、**效果述詞 φ（作者承諾的世界狀態
改變）**、以及簽章。引用集把訊息串成一張有向圖，**結構上跟責任鏈很像，
但它串的是指令，不是責任**。

歸責分三步：**gate**（事實上有沒有一條完好的產生路徑）→ **grade**（用修正版
Halpern–Pearl 實際因果，Chockler–Halpern 責任度 `ρ = 1/(|X*|+|W*|)`）→
**certify**（重放驗證，過不了就不報）。

## 三條承重引文

> **A1 (Replayable stack).** The audited deployment runs on components that
> can be re-executed exactly: **pinned model weights, deterministic serving,
> and seeded environments.** … On hosted or non-deterministic components the
> same checks degrade to statistical corroboration with reported action-match.

> **A2 (Recorded channel).** Inter-principal influence traverses the recorded
> bus. Under A2 exonerations are complete. Influence outside the bus … is
> **invisible to any record-level auditor**.

**Where** — §5、§7.2。**Why** — 整套機器的前提被作者自己列成兩條假設，而
**兩條在跨組織時都不成立**：別人的模型你釘不住，別人的匯流排你看不到。
不是我們說的，是它的 Methods 第一頁。

> **Theorem 4 (Completeness barrier).** … Wherever duty-compliant conduct is
> fallible (honest errors exist), no content-determined standard is both sound
> and complete; and any standard that closes the gap **decides output
> correctness for the audited task itself**. **Innocence is certifiable from
> the record alone; outcome-guilt-completeness is not.**

**Where** — §5（rule zero 的必要性）、A3。**Why** — **這是我們要的那條不可能
性結果，而且比 fair-exchange 近得多。** 它說：只看紀錄的稽核者證得了清白，
證不全罪責；要補上那個缺口，就得**替被稽核的任務判定輸出對不對**——也就是
得變成領域裁決者。**「record-only 的中介不裁決」因此不是保守，是定理的另一面。**

## 最有用的那個數字

它自己做了一個對照：在 **Who&When**（184 條靜態軌跡，**不能重放**）上，把
密碼學與反事實機器全部拿掉之後——

| 方法 | agent-accuracy | step-accuracy |
|---|---|---|
| LLM judge（all-at-once） | 0.413 | 0.255 |
| LLM judge（step-wise） | **0.511** | 0.304 |
| LLM judge（binary-search） | 0.418 | 0.337 |
| **Audita-structural** | **0.408** | 0.321 |

作者自己的結論：

> where the log cannot be re-executed, Audita matches the field's methods, and
> **its advantage appears only where counterfactual access exists.**

**Where** — §5、§7.2。**Why** — **沒有重放權限，這整套就退化成一個 LLM
judge。** 而跨組織正是沒有重放權限的那一側。這比任何論證都有力，因為它是
這一線做得最認真的那篇，用自己的實驗量出來的。

另一個可引的量：**刻意把 31% 的協調移出被記錄的匯流排時，0.157 的責任變得
不可見，但 over-attribution 在 1,200 次抽樣中維持 0.000**——見證者失去的是
覆蓋率，不是健全性。這句可以直接支持我們自己的限制寫法。

## 它對 `2605.13077` 的批評（第三方替我們寫的）

> Recent work on retrospective counterfactual responsibility in concurrent
> stochastic games lets agents trade their own expected responsibility against
> reward in equilibrium, forward-looking strategy synthesis, with no
> adversarial manufacture of a victim's responsibility and **no evidence
> layer**.

**Where** — §2.2。**Why** — 「責任量化那一線預設了一個它自己不提供的證據層」，
出處是別人，不是我們的詮釋。

## 論文沒寫出來的那個條件（2026-09-12 推導，→ `strengths-and-gaps.md` A12）

Definition 3 使義務檢查**跨得過信任邊界**——定義域裡沒有一樣東西在 provider
內部。這是三篇裡唯一不需要重放、不需要能力模型的一段。

**但它成立有一個條件，論文從頭到尾沒有寫。** 用他們自己的兩個實例對照：

- 彙總者「輸出等於已認證輸入的宣告彙總」**成立**，因為**輸入是上游簽的**。
  被檢查者偽造不了自己的輸入，一端在對手手上。
- 任何「我夠努力了」形狀的義務**不成立**：查了幾個候選、看了多久、考慮過
  哪些——**搜什麼、記什麼，兩端都在被檢查者手裡**，沒有對手方簽名，於是
  它是自我認證的，通過與否與實際工作無關。

**條件**：content-determined 的義務只在**一條被雙方簽過的邊**上有意義。
一方**內部**的盡職程度沒有對手方，因此對任何 record-confined 的稽核者都
不可查——**包括責任鏈**。

反例（論文裡沒有，是我們構造的）：使用者說「找最便宜的機票，超過 1000
不要，航空公司不好或體驗不佳的也跳過」。價格上限登記得了；「最便宜」只
能是「我已認證輸入裡最便宜」，搜尋範圍夠不夠判不了；「體驗不佳」是關於
世界的判斷，Definition 3 明文排除。**使用者真正在乎的正是登記不了的那一列。**

## Cautions

- **不要說它「假設單一信任域」時講得太滿——要用 grep 的方式講。**
  全文對 `federation` / `cross-organi` / `trust domain` / `trust boundary`
  的命中數是 **0**。摘要列了 vendor／operator／insurer／regulator 互相推諉，
  但機制是**一條共用的被記錄匯流排＋一個指定的（複製的）recorder**。
  **它的多方是「誰被歸責」的多方，不是「誰各自記錄」的多方。** 準確的寫法是
  「它不處理跨組織的記錄問題」，不是「它承認自己只能在單一組織內用」。
- **它會出數字，而且比 HANSARD 更硬**（Chockler–Halpern 責任度，不是
  Shapley 分配；作者強調「these degrees are not a normalised allocation and
  need not sum to one」——所以 `refs/causal-responsibility/` 那條
  Efficiency 的批評**打不到這篇**，不要誤用）。
- **它有 conduit 標記**：「a principal whose messages merely relay upstream
  content faithfully is additionally flagged as a conduit, so that the verdict
  can distinguish **originating from transmitting responsibility**」。這跟
  break／extend 的區分是同一個關切，但**它用內容算出來，我們由當事人宣告**。
  §4.2 要提到它，否則審稿人會問。
- **開源且可跑。** 送出前若要對它下任何「它做不到 X」的斷言，**出處必須是
  跑過那份程式碼**，不是讀論文——`retractions.md` §G1 的判準。
- Supplementary Note 的證明我只讀了敘述沒驗算。任何引用它定理細節的句子
  要標明這一點。
- **不可以寫成「它假裝一切都能算成一個數字」。** Theorem 4 證的正是不能，
  而且他們用實驗選擇了不判輸出正確性（不看答案的 0.159 勝過看答案的
  0.170）。**該批評的是包裝**——摘要那句「turns the question of who is to
  blame from an argument about logs into a calculation over evidence」，
  以及物理傷害的動機（機制是軟體，證據是模擬）。**批評機制會直接撞上
  `retractions.md` §A。**
- **responsibility error 的正規化沒查清楚。** 正文只寫「ℓ1 距離」，但
  Table 2 的 redundancy 那格（真值 0.5/0.5，judge 指認一人）純 ℓ1 應為
  1.0，表上是 0.500，看起來有除以當事人數。**在讀過程式碼之前，只引相對
  比較（三倍、最低誤差），不引絕對值**——`retractions.md` §E 的同型情況。
- **判定對登記的標準極度敏感**：「holding causal facts fixed and varying
  only the standard leaves the causal profile identical but **flips
  culpability in 69.8%**」。因果機器是穩的，**判定不是**——決定答案的是
  登記簿 D。而 D 的格式、誰寫、何時寫、跨組織怎麼對齊，**正文一字未提**；
  他們明說是消費既有的委派憑證與義務條款。**那一層就是本文的題目。**
