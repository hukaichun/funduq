# 被漏掉的那條線：古典 MAS 的 accountability / responsibility（2026-08-21）

> **起點是使用者的推論**：user→agent→agent 的委派鏈是實作新手就會遇到的問題，
> AutoGen 時代就知道了，只是當時假設整個 agent team 在自己的部署範圍內。
> 那麼**跨 provider 的版本不可能沒人做過**——社群沒反應出來太奇怪。
>
> **查證結果：推論正確。有一條十年的線，發表在該領域的旗艦期刊與主會，
> 而且我們精讀的七篇 LLM-agent 論文，零篇引用它。**
>
> 檢索工具：DBLP（2026-08-21）。標示「未讀全文」的請以原文為準。

---

## 1. 三個群，都在真的地方

### 1.1 杜林＋里昂：computational accountability（主線）

**Matteo Baldoni、Cristina Baroglio、Roberto Micalizio**（Università di
Torino）＋ **Olivier Boissier**（Mines Saint-Étienne / Lyon）。

| 年 | 場合 | 標題 |
|---|---|---|
| 2016 | URANIA@AI*IA | Computational Accountability |
| 2017 | **CARe-MAS@PRIMA** | The AThOS Project: First Steps towards Computational Accountability |
| 2017 | PRIMA | ADOPT JaCaMo: Accountability-Driven Organization Programming Technique |
| 2018 | **CARe-MAS@PRIMA** | *Proceedings of the First Workshop on Computational Accountability and Responsibility in MAS* |
| 2018 | PRIMA | Accountability and Responsibility in Agent Organizations |
| 2019 | **AAMAS** | Engineering Business Processes through Accountability and Agents |
| 2019 | **AAMAS** | Implementing Business Processes in JaCaMo+ by Exploiting Accountability and Responsibility |
| 2019 | **EMAS@AAMAS** | Accountability and Responsibility in Multiagent Organizations for Engineering Business Processes |
| 2021 | **AAMAS** | Robustness Based on Accountability in Multiagent Organizations |
| 2023 | **AAMAS** | Robust JaCaMo Applications via Exceptions and Accountability |
| 2023 | **JAAMAS**（該領域旗艦期刊） | **Accountability in multi-agent organizations: from conceptual design to agent programming** |
| 2025 | EUMAS | Supporting Accountability in Business Processes |
| 2025 | JURIX | **Accountability as a Software Engineering Tool for Multi-Agent Systems** |

**這條線還活著**（2025 兩篇），而且有自己的 workshop 系列。
JaCaMo 是它的實作載體——**他們是有東西在跑的**。

### 1.2 南安普頓：human-agent collectives / responsibility

**Sarvapali Ramchurn、Enrico Gerding、Sebastian Stein、Vahid Yazdanpanah、
Dhaminda Abeywickrama**。

- **JAIR 2016** / **AAMAS 2015**：HAC-ER, A Disaster Response System based on
  **Human-Agent Collectives**
- **IEEE Internet Computing 2021**：**Different Forms of Responsibility in
  Multiagent Systems: Sociotechnical Characteristics and …**
- AISafety@IJCAI 2021：Applying Strategic Reasoning for **Accountability
  Ascription** in Multiagent Teams
- EUMAS/AT 2020：Multiagent Task Coordination as Task Allocation **plus Task
  Responsibility**
- RO-MAN 2019：Model Checking Human-Agent Collectives for Responsible AI
- Appl. Artif. Intell. 2024：Engineering Responsible And Explainable Models
  In Human-Agent Collectives

### 1.3 圖盧茲：邏輯側

- **ECAI 2023**：Parker, Grandi, Lorini — *Anticipating Responsibility in
  Multiagent Planning*

### 1.4 而且 2003 年就有人用了同一個詞組

- **AAMAS 2003**：John K. Debenham — ***Delegating responsibility** in a
  multiagent process management system*
- 2001：Selection of Tasks and **Delegation of Responsibility** in a
  Multiagent System for Emergent Processes

### 1.5 跨組織那一面：interorganizational workflow

**van der Aalst & Weske** 有整整十年的線：

- *Loosely coupled interorganizational workflows: modeling and analyzing
  workflows crossing organizational boundaries*（Inf. Manag. 2000）
- *The P2P Approach to Interorganizational Workflows*
- ***Reflections on a Decade of Interorganizational Workflow Research***（2013）
- **view-based interorganizational workflows**（public / private view）——
  這是 funduq 不透明性與 break 的直系祖先概念

---

## 2. 關鍵發現：七篇全文，零篇引用這條線

對六份下載回來的全文（Governance Gaps、RAILS、MasDrift、Governance at the
Boundary、AIP、Chain Verifiability、Stop Means Stop）grep：

```
baldoni | baroglio | micalizio | yazdanpanah | JaCaMo | computational accountability
```

**七篇全部是 0。**

唯一碰到古典 MAS 的是 Governance Gaps（Ostrom、Sierra 的 electronic
institutions、FIPA）——**而它正是那篇沒有實作、沒有評估的**。

**所以「社群居然沒反應」的正解不是沒人想過，是兩個社群不通話：**
AAMAS/EMAS/JAAMAS 那一側做了十年 accountability，
arXiv 上的 agent-protocol 那一側從零開始造分類法。

這也解釋了為什麼那七篇看起來薄——**它們不是站在十年的肩膀上，是從頭來過。**

---

## 3. The Accountability Horizon：讀完全文後，它是資產不是威脅

**`arXiv:2604.07778v2`**（2026-04-09，Haileleol Tibebu）**已讀全文 2026-08-21。**

### 3.1 定理說什麼

> **Theorem 1 (Accountability Incompleteness).** Let ℋ be a HAC satisfying
> Assumptions 1–3, **whose interaction graph G contains at least one directed
> cycle C\* involving both human and artificial agents.** … Let `C_min` be the
> smallest mixed cycle. There exists a computable threshold, the
> **Accountability Horizon** Λ̂\* = 1 − 1/|C_min|, such that
> Λ̂(ℋ) > Λ̂\* ⇒ ℒ(ℋ) = ∅.

四條公理：**Attributability**（有責任必有因果貢獻）、**Foreseeability Bound**
（責任不得超過預見能力）、**Non-Vacuity**（至少有人的份額 ≥ τ）、
**Completeness**（份額總和 = 1）。

證明機制：環上會出現一種 **cycle-emergent outcome**，環外所有 agent 對它的
因果效應為 0（Axiom 1 逼他們歸零）；環內每個 agent 的預見能力被互相自主性
稀釋到 ≤ 1−Λ̂（Axiom 2 的上限）；於是 Axiom 4 要求總和為 1 時矛盾。

### 3.2 為什麼它打不到責任鏈——三層，由強到弱

**（一）它不是這種函數。** §5.4 第一句自己講：

> The impossibility arises from the requirement that ρ([o]) be
> **a probability distribution over individual agents** (Axiom 4).

責任鏈不分配總和為 1 的份額，它**宣告一條路徑**。這一層最穩，因為它不依賴
任何關於我們拓撲的判斷。

**（二）Foreseeability Bound 正是擔保所否定的東西。** Axiom 2 的出處全是道德
責任傳統——Kant 的「ought implies can」、tort 的比例因果、Fischer & Ravizza
的 epistemic condition。**擔保人要為他預見不到的債務負全責，那正是擔保的
定義。** 保證、代理、契約是另一套制度，而法律發明它們的理由，正是因為
因果－道德分配在複雜鏈上會失效。

**它自己的框架裡有一個支持這點的張力**：它引 **joint-and-several liability**
來論證 γ=1（拒絕部分分配），但連帶責任是**每個被告各負全責**（份額各為 1、
總和為 n），這恰恰違反它的 Axiom 4。

**（三）定理的前件是明寫且可檢查的**：需要一個混合有向環。**委派樹本身無環。**

### 3.3 一個必須用畫圖回答、不能用推的問題

**escalation 迴圈算不算它說的混合環？** C 卡住 → 問題浮到 root → root 回答
→ C 繼續，畫在互動圖上像是一個環。

傾向認為不算——它的機器（Assumption 3 contraction、Lemma 1「**Equilibrium**
Epistemic Dilution」、唯一不動點）預設的是**反覆互相影響直到均衡**，不是
一次性的問答。**但這要把圖畫出來確認。**

而這正好是論文該做的一件事：**把 funduq 的互動圖畫出來，證明它落在定理前件
之外。** 那是可檢驗的主張，不是修辭。

### 3.4 怎麼引用它

**引成動機，不是引成對手。** 它形式化證明了「以預見能力為界、以份額分配為
形式」的問責在高自主性下不可能。**那正是責任必須被宣告而非被推導的理由。**

它 §5.5 自己也證明了逃逸路線存在：把 Axiom 1 換成關係式變體（Ubuntu、儒家
關係倫理），「**the impossibility dissolves entirely**」。

### 3.5 一個要盯的競爭者

§5.4 結尾：「We leave the construction of a **Distributed Accountability
Calculus** to a companion paper」——用 Choquet capacity / Shapley 的
coalition-valued accountability。**同作者的後續論文正在形成，方向相鄰。**

## 4. 對投稿策略的含意

1. **EMAS@AAMAS 從「合理的選擇」變成「有對話對象的地方」**——Baldoni 那組
   2019 就在 EMAS@AAMAS 發過同主題。那裡的 reviewer 讀得懂 break/extend 是
   commitment 與 organizational role 的親戚。
2. **JAAMAS 是可能的目標**，不只是 workshop。那條線的旗艦論文在那裡。
3. **related work 的骨架要改**：現在的 §2.2「古典 MAS」只列了 Contract Net、
   KQML/FIPA、Singh commitment、Esteva electronic institutions、Hewitt。
   **少了整條 accountability / responsibility 線**，而那是離我們最近的古典
   血脈，比 Contract Net 近得多。
4. **一個可以主張的貢獻浮現了**：那條線做的是**組織內部**的
   accountability（organizational role、business process、JaCaMo 部署）。
   funduq 做的是**跨 provider、無共同組織**的版本。
   **「把 organizational accountability 帶到沒有組織的地方」**是一句
   AAMAS 社群聽得懂、而且沒有人做過的話。
   （待驗證：需要讀 JAAMAS 2023 那篇，確認它是否假設共同組織。）

---

## 5. 待辦

1. ~~讀 `2604.07778` 全文~~ **已讀，見 §3。結論：資產不是威脅。**
   衍生待辦：**把 funduq 的互動圖畫出來**，確認 escalation 迴圈是否構成它
   定理前件所要求的混合環（§3.3）。
2. **讀 JAAMAS 2023**（Baldoni et al., *Accountability in multi-agent
   organizations: from conceptual design to agent programming*）——確認
   §4.4 那個「他們假設共同組織」的假設。
3. **讀 IEEE Internet Computing 2021**（Yazdanpanah et al., *Different Forms
   of Responsibility in MAS*）——如果它已經有一套責任型態分類，我們的
   break/extend 必須對照它，不能另起爐灶。
4. 掃 AAMAS 2025/2026 與 EMAS 近兩年的 proceedings，看這條線有沒有人開始
   碰 LLM agent。
5. van der Aalst 的 view-based interorganizational workflow——確認
   public/private view 與我們的不透明性是不是同一個東西。
