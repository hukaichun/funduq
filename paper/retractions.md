# 撤回紀錄（2026-08-21 那一輪）

> 這一天做了兩件事：六篇文獻精讀，以及一次關於 deferred call 路由的長討論。
> 期間寫下又被推翻的說法有十三條，**分成五種形態**。
>
> （這個數字本身一開始也寫錯了——初版和好幾則 commit message 都寫「九條」，
> 是憑印象數的，實際是十二條，之後 §F 再加一條成為十三。錯在一份專門記錄
> 「壓縮時出錯」的檔案標題上，剛好是第 E 類的另一個實例：
> **數字要數過，不要憑感覺。**）
>
> 留這份檔案不是為了自責，是因為那十三條錯誤**不是隨機的**——每一種形態都會
> 再犯，而且都會落在論文最貴的位置（related work 的承重段、intro 的第一段
> 數字、機制的推導）。
>
> 每條都標明：**寫了什麼 → 為什麼錯 → 判準**。

---

## A. 把摘要壓成口號時，「有但很弱」變成「沒有」

三次，全部發生在對近鄰的差異化上。

### A1. 「AIP 只管往下流，我們管往上流」

- **寫了什麼**：`bibliography-notes.md` 的 AIP 那格標成 *Settled
  differentiation*。
- **為什麼錯**：AIP §3.2 的 Completion block 把 result hash、verification
  status、資源消耗與成本**附回同一個 token**，§3.3 還定義三級信任升級。
  **AIP 有 up-flow。**
- **諷刺的是**：同一格下一句就寫著 `self-report`——寫筆記時是看過的，只是
  總結成標語時把它二分掉了。細節全對，標語錯。
- **正確版本**：不是「AIP 沒有 up-flow」，是「**AIP 的 up-flow 是一個沒有
  觀察者的自我宣稱**」，而且這是 AIP 自己 §7 承認的。

### A2. 「RAILS 沒有 escalation path」

- **寫了什麼**：補篇初版 §1.4。
- **為什麼錯**：RAILS §6.3 有兩個 escalation 側迴圈（human arbiter、
  appeal window）。
- **正確版本**：它的 escalation 是**裁決內部的**（判不出來找誰判），
  責任鏈的是**責任路徑的**（誰出事找誰）。

### A3. 「Governance Gaps 做的正是我們要做的事」

- **寫了什麼**：補篇初版把它列為最高威脅（只讀 abstract）。
- **為什麼錯**：讀全文後，它的 G5 escalation 是**合議體把投票結果按 trigger
  路由給人類主管**，整篇框架是議事規則與集體決策。我們的是委派樹裡的責任
  路徑。**同名不同物。**

**判準**：對最近鄰的差異化，**逐項（lane by lane）寫，不要一句二分**。
每一句「他們沒有 X」都要能從對方的 limitations 找到出處；找不到就假設他們
有一部分的 X，回去讀機制章節。

---

## B. 把 in-box 論文的**問題**連同它的發現一起搬過來

三次。共同根源：那些論文的問題來自它們**掌控 effect** 的處境，而我們沒有。

### B1. 「provider 把 subagent 藏在 funduq 之外，我們看不到」是漏洞

- **為什麼錯**：他的資源是他的，藏起來就代表責任全在他身上，鏈根本沒有延伸
  出去。設計記錄自己寫著 *suppliers are trade secrets and their failures are
  your failures*。**那是最無歧義的情況，不是盲點。**
- **根源**：稽核直覺——「應該看得到誰真的在做事」。那正是
  `funduq-capability-out-of-scope` 要排除的反射。

### B2. 「決定的投遞必須帶冪等鍵」是我們的實作要求

- **為什麼錯**：replay double-execution 是 Stop Means Stop 在**框架內部**
  量到的——provider 自己的 harness 重跑自己的 tool call。送達之後怎麼記帳
  完全在他的盒子裡，而且 run id 與該 deferred call 自身的 id 都已經在了。

### B3. 「stale authorization 我們解不了」

- **寫了什麼**：批准五百塊、動手時漲到七百，我們無法在 T3 重新驗證。
- **為什麼錯**：**問題本身是假的。合約成立在 resolve 那一刻**，被授權的是
  **那一個具體的呼叫**，不是「某個世界狀態下的結果」。執行的若是同一個呼叫
  就是已授權（世界變了導致結果不同，跟人簽採購單一樣）；執行的若是別的呼叫
  就根本不是被批准的東西，必須重提一個 deferred call。
- **附帶**：時間差不是變數。即使做到 real time 也一樣，而 funduq 從未主張
  real time。

**判準**：`strengths-and-gaps.md` A8b 說「所有 in-box 解法都假設掌控
effect，所以不適用於我們」——**那條線是雙向的：in-box 的解法不轉移，in-box
的缺陷也不轉移。** 讀 in-box 論文時問「它的**發現**對我們成立嗎」，
不要問「它的**問題**我們怎麼解」。

---

## C. 單位／粒度弄錯

### C1. 「問太多會很煩，所以 provider 會系統性地少問」

- **寫了什麼**：一整段關於 under-asking 均衡、回饋迴路不對稱、損失沒有上限
  的分析。
- **為什麼錯**：**單位錯了。** 問一個事實是正常的 tool call／對話往返，不貴，
  也不牽涉權限。deferred call 是「我要動手了」的那一瞬間。整段建立在把兩者
  混為一談之上。
- **連帶**：洋裝尺寸是個壞例子。真正的例子是「裁縫要下訂五百塊的布」。

### C2. 「break 對授權型問題不可用」

- **為什麼錯**：break **永遠可用**。掐斷的 provider 碰到答不出的問題時，
  用**自己的名義、在自己的 run 上**去問上游即可，鏈始終是斷的。他承諾的是
  「答案掛我名下」，不是「我什麼都答得出來」。

**判準**：談 deferred call 之前先確認講的是不是同一個東西——
①要事實／②要憑證／③要動手的批准，只有③是 deferred call。

---

## E'. 相信一份沒跟上程式碼的表，而不是程式碼本身（新形態，2026-08-25）

前面十三條都是**壓縮**造成的：讀對了、總結錯了。這一條不是。它是讀了一份
document of record，而那份文件落後於它描述的東西——**沒有任何壓縮發生，
來源本身就是舊的。**

### E'1. 「責任鏈完全沒有實作，是那張表上唯一空白的一列」

- **寫了什麼**：`strengths-and-gaps.md` B5，並據此準備在「先實作 / 降級成
  design contribution / 縮小主張」三者間選一個。依據是
  `docs/core-components/extensions.md` 的 **not implemented — design record
  only**。
- **為什麼錯**：對照程式碼後，機制頁上的東西幾乎都在——thread 出生綁 head
  （`repo.py` `ThreadMembershipRequired`）、回答與取消都要授權集合裡的簽名
  （`verify_resolution` / `verify_cancel`）、delegation certificate
  （`verify_delegation`；〔2026-09-03 註〕這一項其後於 funduq#238 被**刻意
  移除**——授權是 policy——所以它今天不在不是這條退回去，是設計又走了一步）、
  extend/break 是動作不是欄位。**37 個測試在測那個
  「沒有實作」的機制。** 真正缺的只有 voucher，而機制頁本來就寫它是
  deployment 自己的 IdP 才做得到的揭露。
- **方向值得注意**：前十三條都是把自己講得太滿，這一條是**把自己講得太扁**。
  漂移不挑方向，而低估自己的那一種更難被發現——因為它讀起來像謙虛。
- **判準**：**論文裡任何一句關於「funduq 有沒有實作 X」的話，出處必須是
  程式碼或測試，不能是任何一頁文件。** 文件是待驗證的宣稱，不是證據；這個
  repo 的 CLAUDE.md 對 `design/` 已經有同樣的規矩，只是沒有延伸到
  `docs/`。`extensions.md` 已於同日更正。

## D. 製造不存在的開放問題

### D1. 決定權的四個「開放問題」

列了「可以再委派嗎」「run 中途換 segment head」「逾時怎麼辦」「多個合法
決定者」。

- **為什麼錯**：前兩題是**鑰匙管理**——funduq 驗的是 segment head 的簽章，
  那把鑰匙背後站著誰是 head 自己的事。第三題答案是 **funduq 不決定**
  （不預防、只歸屬）。第四題被 §2.1 的推導排除（恰好一個決定者）。

### D2. 「兩模式是兩個值還是兩個獨立位元？」

- **為什麼錯**：**不是位元問題，是方向問題。** break/extend 管上行（問題浮到
  誰那裡），揭露開關管下行（答案回去時提問者知不知道是誰答的），兩者正交。
  `extend + 不揭露` 就是代理法的 undisclosed agency，現行設計已經表達得出來。

### D3. 「路由與 failure 歸屬會衝突」

- **寫了什麼**：一張表，說故障容忍測試會逼 resource owner 掀開子處理者。
- **為什麼錯**：那條記錄不只問一個問題，它同時**定了價**——離不開子處理者的
  供應商仍然可以宣告 break、保持不透明，他只是押注自己扛得住，押錯自己付。
  **沒有人被逼著掀開任何東西。**

**判準**：把一個問題寫成「開放」之前，先確認它**不是**既有原則的直接後果。
funduq 的原則（rule zero、observed-outcomes-only、不裁決、mechanism/policy
分離）已經答掉的問題比看起來多。

---

## F. 用單年的收錄名單推導需求

### F1. 「AAMAS 的 GAAI 沒收過協定論文，所以協定論文不受歡迎」

- **寫了什麼**：清點 AAMAS 2026 的 338 篇 full paper，發現 LLM 相關 44 篇裡
  一篇協定／基礎設施都沒有，於是斷定「掛 GAAI 拿聲量」不成立、協定論文在
  AAMAS 沒有位置。
- **為什麼錯**：**沒人投跟投了被拒，在收錄名單上長一樣。** 去讀 AAMAS 自己
  宣告的 subject area topic，**EMAS 那一格字面列著 "Interoperability,
  business agreements & agent-to-agent protocols" 與 "Sociotechnical
  governance tools for norms, ethics & accountability"**。它要，只是在另一格
  ——而我從一個有噪音的訊號推出了「禁區」。
- **使用者的補充**：AI + HITL 本來就難開話題，大家還在自己 host 一堆 agent
  不知道要幹嘛，跨 provider 的題目根本還沒人投。**空缺是機會不是禁區。**

**判準**：判斷場域合不合，**先讀它宣告的 scope，再看收錄名單**。
收錄名單是滯後且有噪音的訊號，只能用來讀「口味」，不能用來讀「需求」。

---

## E. 數字缺分母

### E1. 「85% attenuation 是 introduction 第一段可以直接引的數字」

- **為什麼錯**：**分母是 26**（22/26）。56% 是 9/16。gpt-4.1-mini 那兩格是
  1/30 與 1/18。而且該 benchmark 的 governed success 只有 8/596 = 1.3%，
  作者自己說 headline chart 缺一個錨。
- **附帶**：在 §4.5 的範圍線之下，那篇對我們的價值本來就不是百分比，是
  「The component that violates is not the component that failed」這句邊界
  命題。**引百分比會把論文拖進能力戰場。**

**判準**：任何百分比要嘛附 n，要嘛不引。

---

## 一句話總結

十三條錯誤沒有一條是讀不夠多造成的——**AIP 那條的筆記還寫著「Read in full」**。
全部是**壓縮**的時候出的事：壓成口號、壓掉分母、壓掉單位、把別人的處境壓進
自己的處境。

CLAUDE.md 說「Verify by running something」。這一輪的對應版本是：
**每次要把一段理解壓成一句話之前，先回去看那段理解原本長什麼樣。**

---

## F. 重複一個關於自己程式碼的說法而沒有跑它(2026-08-26)

### F1 「那支 probe 至今仍紅」

**寫了什麼。** 草稿三處、以及好幾輪對話裡,都說 `probe_a_chain_can_be_
branched.py` 至今仍紅,並把它當成「我們誠實地留著一個未關的缺陷」的證據。

**為什麼錯。** 跑一次就知道:

```
[2] B rebuilds it as caller → B      LIMIT
[4] ...went out through funduq       HOLDS
[5] the head cannot be dropped       HOLDS
    a hop from another chain...      HOLDS
every property holds (4 checked)
```

它是綠的,帶一列標為 LIMIT 的限制——而那支 probe 的 docstring 早就寫著
「that row is marked LIMIT rather than counted as a failure」。**來源就在
手邊,而且是自己寫的。**

**這條跟前面十四條不同的地方。** 前面的錯誤來自壓縮、或來自相信一份落後
的文件。這一條兩者都不是:**它是一個關於自家程式碼的斷言,而驗證它的成本
是一道指令。** 沒有跑,只是因為它已經被說過一次,而重複比查證便宜。

**判準。** 任何一句「我們的 X 現在是紅的/綠的/會怎樣」,在寫進論文之前
要跑一次那個東西。這比「出處必須是程式碼或測試」更嚴:那條講的是**看**,
這條講的是**執行**——而 `CLAUDE.md` 開宗明義那一節說的就是這件事。

**順帶。** 這個更正讓論文變**強**不變弱:一支綠的 probe 加一列寫明範圍的
限制,比一支紅的 probe 更能支持「這是有理由的取捨」而不是「這是還沒補的
洞」。錯誤的方向是**把自己講得太扁**,跟 E'1 同一族。
