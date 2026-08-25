# 投稿場域的守備範圍（2026-08-21）

> **問題**：哪些地方收我們這種論文？以聲量計最好跟 LLM／agent 掛勾。
>
> 日期於 2026-08-21 查證；標「需查」的沒查到權威來源，不要當數字用。

---

## 先講那個張力

**LLM 的聲量在 arXiv 和 model-centric 的會議；我們的論文在那些地方會被桌拒。**

NeurIPS / ICLR / ICML / ACL / CoLM 要的是學習成果。一篇「協定機制 + 存在性
證明」在那裡沒有位置——不是品質問題，是 scope 問題。

**而這個領域現在的聲量，事實上就在 arXiv 上。** 我們讀的那七篇沒有一篇是
peer-reviewed 的，但它們被讀、被引、被 A2A 的人看見。所以：

> **聲量走 arXiv，可信度走場域。兩者不衝突，因為預印本不排除投稿。**

---

## A. 直接收我們這種東西，而且與 agent 掛勾

| 場域 | 守備範圍 | 合不合 | 時程 |
|---|---|---|---|
| **AAMAS**（主會） | 11 個 subject area。我們的是 **EMAS**（工程）＋ **COINE**（概念）；LLM 的 **GAAI** 是學習導向 | **合，走 EMAS 不是 GAAI**（見下） | **2027：摘要 10/1、正文 10/8/2026**，通知 12/21，會期 2027-05-03～07 河內 |
| **AAMAS Blue Sky Ideas Track** | 挑釁性、有遠見、**不要求完整評估**的想法 | **在 B5 未落地時最務實的一條**。我們有推導、有機制、缺實作——這個 track 就是為此設的 | 摘要 11/5、正文 11/12/2026 |
| **EMAS@AAMAS** | Engineering Multi-Agent Systems。工程方法、程式設計框架 | 合，而且 **Baldoni 那組 2019 就在這裡發過同主題**。門檻低於主會，適合先落地 | 隨 AAMAS，需查 |
| **JAAMAS**（Springer） | IFAAMAS 官方期刊。基礎、理論、開發、分析、應用 | 合。**那條 accountability 線的旗艦論文在這裡**（Baldoni et al. 2023）。滾動投稿，無截止日 | 審期長（月級） |
| **AAAI**（含 special tracks，如 AI Alignment） | 通用 AI，有 workshop 生態 | 中等。主會競爭激烈且偏 ML；**workshop 是實際入口**（`2511.17332` 走 WMAC@AAAI） | AAAI-27：2027-02-16～23 蒙特婁，投稿已過 |

### AAMAS 2026 實際收了什麼（2026-08-21 清點官網 accepted 名單）

**規模**：main track **338 篇 full paper ＋ 207 篇 extended abstract**。
（2025 有 1361 篇摘要投稿、過濾後 1021 篇進審；2023 是 1015 投 → 237 full
（23.3%）＋ 221 EA。2026 的投稿總數官網未列。）

**LLM／agentic 相關：44 / 338 ＝ 13%。**
但**口味很明確**——幾乎全是「**把 LLM 當工具，去做一個 MAS 問題**」：

- LLM 驅動的規劃／組合最佳化／VRP／水庫調度
- LLM agent 在賽局、模擬、推薦裡的行為研究
- LLM 引導的 MARL、機器人任務規劃
- LLM MAS 的合作崩潰、聲譽、規範形成、操縱脆弱性

**一篇協定／基礎設施論文都沒有。** 而且這 44 篇裡凡是靠近我們主題的
（`LLM Performance Predictors: Learning When to Escalate…`、
`Reputation as a Solution to Cooperation Collapse`）**全部落在能力那一側**
——量的是模型做得好不好，正是 `funduq-capability-out-of-scope` 劃出去的那半。

**制度／規範／責任相關：只有 6 / 338 ＝ 1.8%。**

- **The Triad of Identity, Trust and Responsibility in Multi-Agent Systems** ← **直接先例**
- Reasoning About Responsibility for Taking Risks
- Disobedience in normative multi-agent systems
- Grassroots Federation: Fair Democratic Governance at Scale
- The Role of Social Learning and Collective Norm Formation in LLM MAS
- LLM Performance Predictors: Learning When to Escalate…

**Blue Sky：只收 17 篇**，而且多半是有份量的名字（Peter Stone、Milind
Tambe、Munindar Singh、Francesca Toni、Brian Logan）。它不是「門檻較低的
備胎」——它是**另一種選擇標準**：立場要挑釁、人要有份量。對外來者不一定
比主會容易。

### 讀「宣告的 scope」而不是「單年的收錄名單」

**方法學修正（使用者指出）**：用一年的收錄名單推導需求是錯的。沒人投跟投了
被拒，數字上長一樣；而 AI + HITL 本來就難開話題，跨 provider 的題目現在根本
還沒有人投。**空缺是機會，不是禁區。**

去讀 AAMAS 自己列的 subject area topic：

| 分區 | 宣告的範圍（節錄原文） | 對我們 |
|---|---|---|
| **EMAS**<br>Engineering & Analysis of MAS | **"Interoperability, business agreements & agent-to-agent protocols"**、**"Sociotechnical governance tools for norms, ethics & accountability"**、"Runtime infrastructures and deployment platforms"、"Requirements capture & formal specification"、"Engineering MAS with LLM methods"、"Open-source toolchains, benchmarks & reproducible MAS testbeds" | **主場，字面命中。** 第一條就是 A2A，第二條就是責任鏈 |
| **COINE**<br>Coordination, Organizations, Institutions, Norms, Ethics | "Organizations and institutions"、**"Policy, regulation, and accountability"**、"Responsible socio-technical systems"、"Safety, robustness, trust, and reputation"、"Ethical challenges of using LLMs for coordination" | **概念上的家** |
| **HAI** | 只有 "Mixed-initiative and shared autonomy" 一條命中；其餘是社會機器人、虛擬人、互動設計 | 不是 |
| **GAAI**<br>Generative & Agentic AI | "Agency and **learning** in LLMs"、"RLHF"、"Learning for value alignment"、"Planning or **learning** for agentic workflows"、"**Multi-agent training** of LLM agents"、"Evaluation of LLMs" | **學習導向。協定機制論文在這裡沒有位置** |

**所以是 EMAS（工程）＋ COINE（概念），不是 GAAI。**

### subject area 不影響聲量，只決定誰審你

一篇 AAMAS main-track full paper 掛哪一格都一樣是 AAMAS full paper。差別在
審稿人：

- **GAAI 的審稿人**會問「評估在哪？baseline 呢？學到什麼？」——協定機制答不出來
- **EMAS 的審稿人**會問「機制清楚嗎？可實作嗎？跟既有平台怎麼組合？」——答得出來

結果是二元的，聲量是會議給的。**投給聽得懂你的那群人，不是人多的那群。**

### 主會的重心在哪（關鍵字估，2026 收錄名單 338 篇 full paper）

LEARN ~25%、GTEP ~22%、GAAI 13%、**EMAS 名目 12% 但扣掉假陽性後遠低於此**
（抓 `protocol|interoperability|middleware|runtime|testbed` 的 5 篇，
沒有一篇真的是 EMAS 論文）。

AAMAS 主會是**賽局理論 + MARL** 為主，工程翼小。這與「宣告的 scope 歡迎」
不矛盾——**是投稿量的問題**。

### 兩個 EMAS 不要搞混

- **EMAS ＝ 主會的 subject area** ← 建議走這個。投上就是 AAMAS full paper
- **EMAS ＝ AAMAS 旁邊的 workshop** ← 另一回事

**workshop 本身不是水貨，但很小**：13 屆不間斷（2013–2025）、**每屆出 Springer
LNCS revised selected papers**（有編輯篩選＋一輪修改）、編者是工程翼建制
（Brian Logan、Baldoni、Dastani、Ricci、Winikoff、Bordini、Weyns、Müller）。
Baldoni 那條線走過 **EMAS@AAMAS 2019 → AAMAS 主會 → JAAMAS 2023**，
是真的 feeder。

**但規模**：2023 年 15 篇、2024 年 11 篇、2025 年 14 篇，且一半是「Towards…」
的早期工作。**那是 workshop 的功能，不是缺陷**，但引用影響力低。
它是**拿回饋**的地方，不是製造聲量的地方。

### 四種貨幣，互不替換

| 想要什麼 | 去哪裡 |
|---|---|
| 學術份量 | **AAMAS 主會，routing 掛 EMAS** |
| 對的人給回饋 | EMAS workshop |
| 領域能見度 | **arXiv ＋ A2A 的 issue**（做 A2A／MCP 的人不讀 AAMAS proceedings） |
| 長期 | JAAMAS |

### 順帶：協定不發期刊

TCP、HTTP、OAuth、TLS 沒有一個是先發論文的，它們是 RFC。MCP／A2A／ANP 也
一樣，規格活在 GitHub。**我們讀的七篇沒有一篇是協定，它們是對協定的評論**
——這正是它們讀起來薄的原因。

所以工作切成兩半：

| | 去哪裡 |
|---|---|
| **規格形狀**：`Elicitation` 缺型別欄位、`RESOLVED` ≠ 已生效 | **A2A 的 issue／PR**。不需要論文，而且被採納比一篇 workshop paper 有份量 |
| **研究形狀**：多跳跨 provider 的介入權機制 | **論文**（EMAS/COINE） |

論文的問題句：**多跳跨 provider 的委派中，介入權是未定義的；一個 per-edge
宣告決定了全部。**

---

## B. 換一個框架就合的路線---

## B. 換一個框架就合的路線

| 場域 | 守備範圍 | 什麼情況下走 |
|---|---|---|
| **ICSE / FSE / TSE** | 軟體工程。量測研究、框架缺陷、工具 | **B5 做完、而且做了量測之後。** Stop Means Stop 走的就是這條（cs.SE，TSE 格式） |
| **USENIX Security / CCS / NDSS / S&P** | 安全。委派、授權、身分 | 若把論文重寫成「跨組織委派的授權失效」。AIP 那一系的落點 |
| **FAccT / AIES** | AI 的問責、公平、社會影響 | 若主打 accountability。`2605.30169` 落在 FAccT 2026，Accountability Horizon 也是這個語域 |
| **The Web Conference (WWW)** | Web 基礎設施、協定 | 若走 agentic web／聯邦那條線 |

## C. 不要投

- **NeurIPS / ICLR / ICML / ACL / EMNLP / CoLM**——scope 不符，會桌拒
- **ICAART**——收 agent + AI 且提 LLM，但聲量與嚴謹度都不足以當目標

---

## 建議

**分兩段，不要綁成一個決定。**

**第一段（現在～10 月）：arXiv 預印本，LLM-agent 框架。**
成本接近零、卡優先權、聲量走這裡。而且 RAILS §12.1 已經把我們的題目寫成
open problem，A2A #2028 有 24 則討論——**優先權是真的有風險的**。

**第二段（視 B5 進度）：**

- **B5 來得及** → **AAMAS 2027 主會**（10/8）。有機制、有推導、有跑得動的
  存在性證明，那是主會的規格。
- **B5 來不及** → **AAMAS Blue Sky（11/12）**。晚一個月，而且該 track 明文
  不要求完整評估。落選也不傷。
- **兩個都想要** → Blue Sky 投想法、之後把實作與量測寫成 **EMAS** 或
  **JAAMAS**。那條 accountability 線就是這樣長出來的
  （workshop → AAMAS → JAAMAS）。

**不建議**：為了聲量硬投 ML 會議。那不是投不上的問題，是投錯地方。

---

## 待查

- EMAS@AAMAS 2027 的截止日
- FAccT 2027 / AIES 2027 的截止日
- AAMAS 2027 是否有 JAAMAS track（2026 有）
