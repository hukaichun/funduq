# 草稿 v0 — AAMAS 2027 主會(EMAS subject area)

> **狀態:第一版草稿。** 結構完整;論證已定的地方寫成成稿,未定的標
> `[STUB]`。2026-08-25 寫,材料來自當天對話裡的設計理念陳述,加上
> `strengths-and-gaps.md`、`downstream-review-2026-08.md`、`retractions.md`。
> 這裡沒有一句是定稿——目的是**早一點看到形狀,錯得便宜**。
>
> **語言**:中文是工作語言,英文是投稿語言。專有名詞保留英文,因為它們在
> 論文裡會是 term of art。定稿前整篇翻譯,不是逐句轉寫。
>
> **投稿硬約束**(2026-08-25 讀 AAMAS 2027 instructions):正文 **8 頁**、
> 參考文獻不計、**LaTeX 強制**、**double-blind**、補充材料 ≤25MB 而且
> **審稿人沒有義務看**——所以任何承重的東西必須寫在正文裡。
> 摘要 2026-10-01、正文 2026-10-08;OpenReview 帳號要在摘要前兩週建好,
> 也就是 **~2026-09-17**。
>
> **匿名化**:系統名、repo、probe 三個都會破匿名,而它們正好是證據。
> 本草稿一律稱系統為 **the broker**;送出前專案名、repo URL、作者 handle
> 全部要清掉,artifact 換成匿名鏡像。probe **用它做了什麼來稱呼**,不用
> 路徑。

---

## 標題候選

1. **Responsibility Chains: A Broker That Records Delegation Without Governing It**
2. Every Node Is a Supplier: Delegation Boundaries for Agents That Represent Businesses
3. What a Chain Proves: Origin, Possession, and the Limits of Delegation Provenance

> (1) 一行講完位置和拒絕,對掃標題的審稿人最安全。(3) 最誠實地反映本文
> 最強的證據,但讀起來像負面結果。**晚點再決定**,等摘要寫出來。

---

## 摘要 `[STUB — 最後寫]`

要依序包含:agent 代表的是業務不是人;委派讓每個供應方變成使用方,兩個
角色是遞迴的;回答「他能做什麼」的系統把一種場景寫進了協定,於是別的場景
不可表達;一個只記錄責任、不裁決責任的 broker 能同時保住兩邊的立足點;
以及**兩個我們對著跑得起來的實作證偽掉的性質**。

---

## 1. Introduction

**¶1 —— 今天回答不了的那個問題。** 一個請求交給 agent,agent 交給下一個,
轉了三四手之後出了事。要回答「這件事是誰批准的」,現在的做法是從各方的
日誌往回推論。這不是我們的觀察:一份 2026 年 8 月的立場論文把
auditability 拆成五個維度——其中第四個就叫 responsibility attribution,
定義為「full delegation chains recoverable from immediate executor to
originating principal」——並指出**沒有任何現有工作同時滿足這五個維度**,
且把「capturing full responsibility chains across multi-agent delegation」
列為開放問題。〔arXiv:2604.05485v2,USC/ASU/JHU,2026-08-13,OP3〕
同一時期,高風險系統的自動事件記錄義務開始生效。〔EU AI Act Art. 12(1)〕

**¶2 —— 這個領域正在做的事,以及它需要什麼。** 2026 年上半年至少五個設計
同時出現,做法一致:**把授權沿著委派往下傳,每一跳只准收窄**。
〔`draft-liu-oauth-chain-delegation-00`;`draft-niyikiza-oauth-attenuating-
agent-tokens-01`;`draft-sato-soos-mjwt-00`;HDP;IPP〕它們彼此不同,
但要能運作,每一個都需要三樣東西裡的至少一樣:一個**中央發證方**、一套
**共同的權限詞彙**、或一個**裁決者**。這三樣在單一組織內都拿得到。跨組織
一樣也拿不到。

**¶3 —— 共同詞彙拿不到,而且提出者自己已經放棄了。** 這一點不必由我們
論證。做這件事最完整的那份規格,把政策欄位定為**預設不存在**
(「This field is typically absent」),把政策語言留給**委派方與授權伺服器
雙方自行協議**(「any other policy representation agreed upon by the
delegator and the Authorization Server」),並在自動比對「算不動或不可判定」
時,允許驗證方**退回去相信授權伺服器的簽名**(「the RS MAY rely on the AS's
attestation… that the AS already performed policy narrowing validation」)。
三個讓步依序把共同詞彙換成了雙邊協議,再換成對中央的信任。
〔`draft-liu-oauth-chain-delegation-00` §4.4, §9.x〕

底下的原因是結構性的:**agent 在推論當下才決定呼叫哪些工具**,委派發生時
還不知道下游會需要什麼。事前寫下的約束只能用猜的——猜寬了等於沒收窄,
猜窄了下游做不完事。後者量得到:把約束交給每一手自己收窄,會擋掉最多
54.5% 本來該做的呼叫。〔arXiv:2608.07556〕

**¶4 —— 授權沒有消失,它退回各方自己的邊界內。** 說委派**互動**上不存在
授權,不是說授權不存在。B 手上那把資料庫連線是 B 的擁有者給 B 的;呼叫方
從來沒有授權過 B 去用它。授權確實發生,但發生在每一方自己的邊界內、對
自己的資源。跨過委派邊界的東西裡,剩下的不是「你可以做什麼」,而是
**「誰為這件事負責」**。

**¶5 —— 該回頭問人的機制存在,它缺的是收件人。** 危險的操作本來就應該
設計成停下來等人按按鈕。這在單一 agent loop 裡運作良好,因為要按的人就在
旁邊。跨過一次交接之後,那個按鈕**沒有地址**——系統知道該停,不知道該問
誰。這是量得到的失效:一份控制了工具、政策與提示、只變動架構拓撲的研究
指出「**違規的那個元件不是失敗的那個元件**」,而政策相關的事實在交接處
被丟掉 81%〔arXiv:2608.16055〕;另一份的約束流失有 92% 落在**第一次**
交接〔arXiv:2608.07556〕。

**¶6 —— 責任本來就在,只是沒有被記下來。** 一個共用帳號也有擁有者,真的
出事就是那個擁有者負責。責任從來不是缺席的,缺席的是**紀錄**。本文提出的
中介只做這一件事:記下責任在哪裡結束、在哪裡開始,而**不判定**任何一方
是什麼、也不代任何一方決定。它不提供談判機制;它**把需要談判的雙方接起
來**。

有了地址之後,權利就可以沿同一條路走——走到**能回答的那一方**為止,而且
是在 runtime 才走:因為只有呼叫真的發生之後,才知道這一步需要什麼權限。
同一個事實同時做兩件事——它讓事前寫死的 scope 不可能,也讓持有權利的那
一方成為唯一能在對的時刻決定的人。

> **給審稿人的一句話,要寫在正文裡**:本文不回答「一個 agent 能替使用者
> 做什麼」。那是供應方與使用方之間的事,既預測不了,也不該為某一種場景
> 把一種互動模式寫進協定。本文回答的是**在他們之間,什麼跨得過邊界**。

**¶7 —— 貢獻。**
1. 把委派問題陳述成**角色遞迴**的問題:供應方一旦轉包就成為使用方,所以
   任何把角色固定分配給參與方的寫法都寫不進協定(§3)。
2. **責任鏈**:跨越邊界的是金鑰與結構,從不是權限;「延伸或不延伸」本身
   就是宣告,段落邊界從簽名實際到達的位置推導,不在任何地方登記(§4)。
3. 示範一項**權利**可以搭著那個結構走,而中介從未定義那項權利——由持有
   者在 runtime 決定,到段落邊界為止。兩個實例:一個暫停的問題只有該段
   的 head 能回答;以及一份使用方憑證沿段落而不跨段落(§5)。
4. **兩個我們對著跑得起來的系統證偽掉的性質**(§6):一條簽好的鏈證明
   來源而不證明持有;鏈的完整性無法證明。兩者都由可執行的 probe 展示,
   其中一個至今未關。

---

## 2. 三個支撐點,以及提出者自己怎麼寫

> **這一節的規矩**(`retractions.md`):每一句「他們沒有做 X」都必須有對方
> 文本的出處,最好是對方自己的 limitations 或讓步。凡標
> `[待逐字查證]` 的,目前出處是二手摘要,**進正文前必須讀原文**。
>
> 排列方式刻意不按系統排,按 §1 那三個支撐點排。這是論證的形狀:五個設計
> 彼此不同,共同點是每一個都需要三樣裡的至少一樣。
>
> **篇幅衝突,要決定**:§1 ¶3 和 §2.2 引的是同樣那三句讓步。8 頁裝不下
> 兩次。要嘛 §1 只留一句、其餘下放 §2,要嘛 §2.2 只留表格。**承重的那邊
> 要引全文,另一邊只准指過去。**

### 2.1 中央發證方

鏈由誰簽,決定了鏈能離開誰而存在。

- **`delegation_chain` claim**(Alibaba×2、Cisco、Okta,2026-06-06)每一筆
  紀錄的 `as_signature` 是 **REQUIRED**,而委派方自己的 `delegator_signature`
  是 **RECOMMENDED**。驗證方也不准相信手上那條鏈:
  > 「For opaque (non-JWT) access tokens, the Resource Server **MUST** use
  > token introspection ([RFC7662]) to retrieve **the authoritative
  > `delegation_chain` from the AS**, rather than trusting any
  > client-supplied chain data.」

- **HDP**(2026-03)整條鏈只有一把金鑰,而它自己把後果寫出來了:
  > 「HDP v0.1 uses the issuer's key for all hop signatures, meaning agents
  > do not sign with their own keys… hop signatures attest that **a hop was
  > recorded at the issuer**, not that the specific agent produced it.」(§7.1)

  per-agent key 是 v0.2 的計畫。

- **SentinelAgent** 由一個中央 Delegation Authority Service 發證、攔截、
  阻擋。`[待逐字查證]`

**弄成不可表達的**:沒有共同發證方的兩方之間的委派。跨組織正是這種情況。

### 2.2 共同權限詞彙

**這一格不需要我們論證,因為提出者自己在三個地方讓步了,而且是同一份規格。**

1. 這個欄位預設不存在:
   > 「**This field is typically absent.** The delegation is governed solely
   > by the OAuth `scope` parameter… When this field is absent, the Resource
   > Server MUST apply scope-based authorization only.」
2. 語言不由規格定,由雙方私下講好:
   > 「…Rego…, ALFA…, XACML, or **any other policy representation agreed
   > upon by the delegator and the Authorization Server**.」
3. 算不動的時候,退回去信中央:
   > 「For expressive policy languages where automated subset checking is
   > computationally expensive or **undecidable**, the RS **MAY rely on the
   > AS's attestation** (`as_signature`) as evidence that the AS already
   > performed policy narrowing validation at issuance time.」

三步依序把「共同詞彙」換成「雙邊協議」,再換成「對中央的信任」。

而現存的詞彙彼此不通:`authorization_details`(AAT)、`cedar_actions`
(MJWT)、`scope` + Rego(`delegation_chain`)、自然語言 `intent`(HDP)。
四份規格四套詞彙。`[AAT / MJWT 待逐字查證]`

HDP 記了 scope 之後,把檢查推回應用層:
> 「Semantic validation of agent actions against declared scope is an
> application-layer concern; **HDP provides the record, not the
> enforcement.**」(§4.2.3)

> **這句話要小心引。** 它跟本文的立場字面上相同,而立場其實不同:HDP 記
> scope 然後不檢查,本文**不記 scope**。差別必須在正文裡講死,否則審稿人
> 會說已經有人講過。

**根本原因是時序,不是政治。** agent 在**推論當下**才決定呼叫哪些工具;
委派發生時,委派方還不知道下游需要什麼,寫下的約束只能用猜的。猜窄了的
代價量得到:把約束交給每一手自己收窄,擋掉最多 **54.5%** 本來該做的呼叫,
完成度掉 36.3 分,理由是「delegators cannot anticipate downstream needs」。
〔arXiv:2608.07556〕

**弄成不可表達的**:任何雙方沒有共同權限詞彙的部署——也就是幾乎所有跨組織
部署。

### 2.3 裁決者

- **RAILS** 自稱中性,但中性的是**裁決者**不是**棄權者**:「RAILS
  adjudicates on evidence」(§5.5),而 §9.8 主張清算所的決定權。
- **SentinelAgent** 在執行前攔截並阻擋。`[待逐字查證]`
- **AIP** 是遞減式能力權杖那一系;它有 up-flow,但那是自報,而且是**被評價
  的那一方自己簽的**——它自己的 Limitations 引用 Provenance Paradox 說
  自評品質「systematically selects the worst delegates」。

**弄成不可表達的**:兩造都有正當利益、而**沒有人有資格判定**的爭議。

### 2.4 一張表(正文若擠得下)

| 需要的支撐點 | 誰需要 | 出處 |
|---|---|---|
| 中央發證方 | `delegation_chain`、HDP、SentinelAgent | 「the authoritative `delegation_chain` from the AS」;HDP §7.1 |
| 共同權限詞彙 | AAT、MJWT、`delegation_chain`、HDP | 「any other policy representation agreed upon by the delegator and the AS」 |
| 裁決者 | RAILS、SentinelAgent | 「RAILS adjudicates on evidence」 |

### 2.5 他們看見了同一個洞,然後把它列為選配

`delegation_chain` 草案自己列的第二個缺口,就是本文的機制:

> 「The `act` claim is **constructed unilaterally by the Authorization
> Server**. The delegating agent leaves **no independent cryptographic
> evidence** that it authorized a specific delegation. This limits
> non-repudiation and post-hoc audit capabilities.」

然後 `as_signature` 是 REQUIRED,`delegator_signature` 是 RECOMMENDED。

**這是全節最有力的一段**:不是我們指出他們漏了什麼,是他們指出了同一件事,
而在把它做成必要條件、還是做成選配之間,選了選配。本文選的是另一邊——鏈上
除了各方自己的簽名之外**沒有別的東西**,所以沒有一把中央金鑰可以退回去信。

順帶,那份規格對自己的邊界也很誠實:「This version of the specification
**focuses on linear delegation chains**; other complex topologies such as
diamond-shaped delegation… may be addressed by future extensions」,以及
「A RECOMMENDED default maximum depth is **5 hops**」。**沒有任何一份處理
「某一手不再延伸」** —— 那不是被拒絕,是沒有被想成一種行為。

### 2.6 刻意不放進這一節的

本文所承接的古典脈絡——contract net 的任務分配、agent 通訊語言、
electronic institutions——屬於 §3,是**祖先**不是競爭者。
`classical-mas-line.md` 記著一件值得寫一句的事:近期七篇 agent 協定論文
對那條線**零引用**。

已採納且最成熟的那份跨域規格(`draft-ietf-oauth-identity-chaining`,已送
IESG)做的是 token 換發,不是責任。`[待逐字查證:它是否明文把 audit /
accountability 列在範圍外,還是只是沒提。這兩件事在論文裡不能混為一談。]`

---

## 3. 場景設定

**3.1 是業務,不是人格。** 一棵委派樹**根在一項業務需求**,而**每個節點都
是某項業務的供應方**。根部有沒有坐著一個人不是另一個問題:一個不為任何事
負責的單位不是業務,而業務是由會為事情負責的人組成的。

這**取消**而不是解決了文獻裡的一個問題:有人主張子委派鏈讓過失無從歸屬,
**因為沒有人類 principal 去吸收它**。如果真的沒有東西吸收,那就不是一項
業務,也就沒有什麼好清算的。

**3.2 中介是幹嘛的。** `[STUB]` broker 持有 run,記錄誰提出、經過誰的手,
並把工作交給正在服務的那一方。它不實作 transport,也不說自己發明的協定;
互動的詞彙是標準的。

**3.3 紀律:不替場景發明互動模式。** `[STUB]` broker 發明的任何東西必須
opt-in,而且必須讓標準客戶端的行為**完全不變**——這是可以測的性質,不是
宣稱。把那個測試寫出來。

---

## 4. 責任鏈

`[STUB —— 機制章,最長,而且是 EMAS 審稿人讀最兇的一節。]`

必須依序涵蓋:

1. **鏈只帶金鑰,不帶別的。** 沒有 subject、沒有時間、沒有 scope。每一跳
   由它所指名的金鑰簽署,並以雜湊連到前一跳。
2. **延伸就是宣告,沉默就是 break。** 沒有 per-edge 的旗標。延伸買到的
   東西——升級路徑、回答權、可見性——正好是 break 拒絕的東西,所以旗標
   沒有東西可以表示。段落邊界是**從簽名實際到達的位置推導出來的**,不在
   任何地方登記。
3. **三綁。** 介入權、成本歸屬、可見性沿著同一條邊界走,而那正是宣告
   不可腐化的原因:「**使用方付錢但不准看**」和「**供應方能看但不付錢**」
   兩句話結構上都說不出來。註記:三綁是**宣告的語義**,不是任何一種成本
   實作的功能。
4. **中介對宣告不做任何決定**,也不判定任何一方**是什麼**。agency /
   resource owner 這組詞彙,是那兩種宣告各自意味著什麼的名字——是自由而
   被定價的宣告會塌縮成的兩個穩定型態——不是任何人拿來判定的測試。

---

## 5. 疊在上面的授權鏈

責任鏈說的是誰負責。它對任何人可以做什麼**隻字未提**——而一項權利仍然
可以沿著它走,不需要中介去定義那項權利。

**規則。** 一項屬於段落 head 的權利,段落內的任何一方都可以行使,**到邊界
為止**。

**具體實例。** `[STUB]` 使用方自己的模型憑證,可以被服務該 run 的 agent
使用,也可以被段落延伸到的任何一方使用,並在段落結束處截斷:斷開的子樹
自己出錢。中介從不判斷那份憑證可以花在什麼上。它只決定段落在哪裡結束。

**為什麼這是對 §2 的回答。** 那張表裡的系統把權利定義在**鏈之內**,因此
需要一套所有人都同意的詞彙。這裡鏈只定義結構、權利依附結構,所以**不需要
任何人事先同意「權限」是什麼意思**。

**第二個實例,而且它才是主證。** 一個暫停的 run 被回答時,簽名要對上
`{ask.head_key, agent.provider_key}`——**只有該段的 head(或正在服務的
供應方)能回答那個暫停**;取消走同一條路。〔`doors.py:294-301, 341-346`;
`test_pause_resume.py`、`test_responsibility_chains.py`〕這是同一條規則的
實作,而且不帶任何實驗性標註。

> **論文裡要誠實寫的**:KYOK 那個實例是實驗性的,作為「疊加可行」的示範
> 完整,但不作為生產機制提出——它是第二個例子,不是唯一的。承重的是暫停
> 那一個。`[待決]` 本節是一節、§4 的一段,還是 future work。

---

## 6. 我們證偽掉的東西

> 全文最有辨識度的一節,也是這篇值得寫的理由:在一個機制性質靠散文宣稱的
> 文獻裡,這兩條是**被執行**的。兩支 probe 都是**先寫成紅的**、在修法之前,
> 而且其中一支至今仍紅。

**6.1 簽好的鏈證明來源,不證明持有。** 一條鏈證明 head 的金鑰簽了第一跳。
它不證明**現在呈交它的人**持有那把金鑰——而鏈不是秘密,因為 broker 會把它
原樣轉給正在服務的供應方,好讓 agent 自己驗證而不是相信一份摘要。一支
probe 讓供應方拿使用方自己的鏈,在門口為使用方從未要求過的工作開一個 run:
它被接受、記在使用方的 head 底下,而兩筆紀錄在**所有帶權威的欄位上完全
相同**。

*修法及其形狀*:broker 無法認證呈交者,因為門收到的是 bytes 不是連線。
前面的 seat 可以,並把它認證出的金鑰傳進來;broker 拿它去比對鏈的
**最後一跳**——絕不是 head,而比對 head 正是讓上述重放通過的那個錯誤。
認證留在外面;比對放在裡面,因為那樣只需要測一次,而不是每個部署各自
重寫一遍。

**6.2 完整性無法證明。** 簽名與雜湊連結證明沒有人被**插入**、**重排**、
或從別條鏈**接枝**進來。它們從不證明沒有人被**移除**。一支 probe 用第一跳
自己的 token 把 `caller → A → B` 重建成 `caller → B`:沒有偽造任何東西,
驗證通過,head 不變。兩個確實抵抗得住的性質也一併釘住——head 抹不掉,
別條鏈的 hop 接不上來。

*什麼構得到它*:broker 為它所做的每一次派工簽名,並寫明**派給哪個 agent**。
agent 的定址是 (provider key, name) 這一對,而那把 provider key 正是該
供應方老實延伸時要簽下一跳的金鑰——於是一跳與它的後繼互相對照,而分支
無法同時滿足兩邊。

**6.3 我們不主張什麼。** 近期一份綜述指出:沒有任何已部署的協定能以密碼學
證明「哪個人類 principal 授權了哪個 agent 去做哪個**具體動作**」到第三或
第四跳。**本工作同樣不滿足這句話**:把第一跳綁定到它所授權的動作是**刻意
延後**的,所以一個老實延伸之後、以使用方的 head 行動的一方,是**看得見、
追得到,但攔不住**的。我們主張位置與路徑,絕不主張那句話。

我們也不主張「只記錄不裁決」是**有效的**。沒有人量測過,包括我們自己;
看似支持它的那個相鄰結果,來自一個同時做 complete mediation **而且會裁決**
的設計,因此它裡面根本沒有 record-only 這個對照組。

---

## 7. 實作 `[STUB]`

簡短。機制已實作且有測試;唯一「已設計未實作」的部分是把金鑰翻譯成人的那
一次揭露,而它屬於部署自己的 identity provider,論文裡照這樣命名。
implemented-versus-designed 用一張小表交代就好。

**不要**宣稱機制沒有實作——曾經有一份內部對照表這樣寫,而同時有測試在測
它;那個錯誤已記在 `retractions.md`,而且是它自己的一種失敗形態:**相信一份
落後於程式碼的文件**。

---

## 8. 討論與限制

- **本工作從空間裡拿掉了什麼。** 每一個設計都會剝掉東西;§2 那張表只有在
  我們對自己問同一個問題時才公平。我們沒有**常駐意圖**的詞彙——監控或
  常駐守衛被建模成很多個 run 加一個 thread,而「常駐」這件事住在紀錄之外。
  由 timer 驅動的 run,責任追到的是一次**部署決定**而不是一次人的選擇,
  而鏈上沒有任何東西指向那個決定。
- **治理接在這裡,但不由這裡提供。** 兩份立場不同的論文陳述了需求:治理是
  一個**缺失的架構層**,必須能與既有互通標準**組合**;以及清算周邊的治理
  問題**明文未定**。`[兩句原文都要引]`
- `[STUB]` 聯邦,以及為什麼鏈跨越多個 broker 不需要額外設計。

---

## 9. Related work —— 擺放備註 `[STUB]`

視篇幅併入 §2 或獨立成節。古典脈絡(contract net → agent 通訊語言 →
electronic institutions → 本場域自家期刊上的 accountability 線)是與可能
審稿人握手的地方,`classical-mas-line.md` 已備妥含引用。

---

## 動筆前要決定的四件事

1. **標題** —— 摘要寫出來之後再定。
2. **§5 的位置** —— 一節、§4 的一段,還是 future work。
3. ~~**§1 的鉤子**~~ —— 已定:arXiv:2604.05485v2 的 OP3(把責任鏈列為
   開放問題)。CSA 那兩個百分比**不用了**,n 至今未查證。
4. **匿名化方案** —— 匿名 artifact 鏡像;以及 probe 要不要當補充材料
   (審稿人沒有義務看,所以承重的部分必須在 §6 正文裡講完)。

## 送出前的檢查

- 每個百分比附 n,否則刪掉。
- 每句「他們沒有做 X」都引對方文本,最好是 limitations。
- §2 裡每個 `[待逐字查證]` 都清掉:二手摘要不得當引文。目前逐字讀過原文的
  只有 `draft-liu-oauth-chain-delegation-00` 與 HDP;AAT、MJWT、
  SentinelAgent、`draft-ietf-oauth-identity-chaining`、agentgateway 都還沒。
- 「沒有明文寫」和「明文寫在範圍外」是兩件事,不得互相代用。
- 每個「本系統有沒有實作 X」的句子,出處是程式碼或測試,**不是任何一頁
  文件**。
- 送出那一週再掃一次該場域的最新 listing。
