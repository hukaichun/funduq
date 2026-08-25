# `paper/` — 責任鏈論文的工作檔

**都是工作筆記，不是 document of record。** 五個檔各有明確分工，**不要
互相複製內容**——重複的東西會在其中一份被改掉時變成謊言。

| 檔案 | 放什麼 | 不放什麼 |
|---|---|---|
| **`bibliography-notes.md`** | 條目索引：每一條引用附「它支持哪個主張」，按論文的規劃章節排 | 論證、判斷、進度 |
| **`downstream-review-2026-08.md`** | 2026-08-21 那一輪掃查的產出：六篇全文導讀、應讀清單、分節補充、**這次掃查的覆蓋率與偏差** | 論文層級的定位與待決事項 |
| **`strengths-and-gaps.md`** | **結算**：已知優勢（每條附原句出處）、已知缺口（每條附誰該決定）、待使用者決定的清單 | 導讀、掃查方法 |
| **`input-required-routing.md`** | deferred call 的路由與決定權——**只放結論**：三分類、一個宣告推導出的五條、文獻空白、兩個給 A2A 的建議 | 推導過程中被推翻的說法 |
| **`classical-mas-line.md`** | 古典 MAS 的 accountability/responsibility 線（AAMAS/JAAMAS，十年，七篇 LLM 論文零引用）＋ Accountability Horizon 的讀後 | LLM-agent 那一層的文獻 |
| **`venues.md`** | 投稿場域的守備範圍、AAMAS 的 subject area 分工、四種貨幣 | 論文內容 |
| **`draft-v0.md`** | 論文本身的第一版草稿：定稿的段落、`[STUB]` 標記的未定處、投稿硬約束（8 頁、LaTeX、double-blind）、送出前的檢查表 | 文獻導讀、掃查方法 |
| **`retractions.md`** | 寫下又被推翻的說法，**按產生它們的形態分組**，每條記「寫了什麼 → 為什麼錯 → 判準」 | 還成立的結論 |

## 讀的順序

- **想知道現在站在哪** → `strengths-and-gaps.md`
- **想知道某篇文獻說什麼** → `downstream-review-2026-08.md` §1
- **想引用什麼** → `bibliography-notes.md`
- **要開始寫某一節之前** → 先讀 `retractions.md`。那十三條錯誤沒有一條是
  讀不夠多造成的，全部是**壓縮**的時候出的事，而寫論文就是一連串壓縮。
  2026-08-25 加了第十四條，形態不同：**相信一份沒跟上程式碼的文件**，
  而且方向是把自己講得太扁。所以還有第二條規矩——關於「我們有沒有實作 X」，
  出處只能是程式碼或測試。

## 三條硬規則

1. **任何百分比要嘛附 n，要嘛不引。**（`retractions.md` §E）
2. **對近鄰的差異化逐項寫，不要一句二分**；每句「他們沒有 X」都要能從對方的
   limitations 找到出處。（`retractions.md` §A）
3. **判斷場域先讀它宣告的 scope，再看收錄名單**；收錄名單讀得出口味，讀不出
   需求。（`retractions.md` §F）
