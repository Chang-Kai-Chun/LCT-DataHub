---
tags: [auto-control, 舊程式, LCT_Combined, 數據整合]
---
# older_app：LCT_Combined.py 內容整理

> [!note] 說明
> - 來源：`D:\SynologyDrive\114級\Gino\LCT_Combined.py`（3555 行、約 669 KB）。我完整閱讀了邏輯程式碼，**沒有執行**，也沒有修改原檔。
> - 依你的要求，這份內容**沒有**整理進 `6. 每日筆記` 的筆記。
> - 行號為原檔行號。標「待確認」的是我讀程式碼的推論，沒有實測。
> - 原檔裡有些註解在讀取時是亂碼（例如第 157、184、255 行），只影響註解，不影響程式。

## 一、整體
- **是什麼**：桌面軟體「LCT 數據整合軟體」，版本徽章 **V5.4**，視窗 1100×760
- **框架**：Tkinter（GUI）、pandas（資料處理）、openpyxl（Excel 格式）、matplotlib（預覽）、`win32com`（控制 Origin）
- **只能在 Windows 執行**，且需要安裝 Origin（用 COM 介面 `Origin.ApplicationSI`）
- **工作方式**：選檔案 → pandas 整理成多個 sheet 的 Excel → 預覽視窗勾選曲線 → 送進 Origin 用模板繪圖
- **單一檔案**：所有邏輯與介面都在同一個 `.py`，類別 `SolarApp` 是主視窗

## 二、檔案結構
| 行號 | 內容 |
| --- | --- |
| 1–17 | import；`matplotlib.use('TkAgg')` |
| 19–93 | 字體、顏色、淺色與深色主題、中英文字串、全域 widget 登記表 |
| 96–153 | `_apply_ct`、`_retheme`、`_update_premium_btn_theme`：主題切換 |
| 156–177 | **內嵌 Origin 模板**（Base64 字串，見下） |
| 186–338 | 兩個對話框：`DataFilterDialog`、`ConditionSetupDialog` |
| 343–1433 | 資料處理函式（JD、MingChi、Noise、EQE、JV 批次） |
| 701–772、960–1088、1931–2005、2187–2335 | 畫圖到 Origin 的函式 |
| 1439–1583 | 介面輔助工具（背景、按鈕、可捲動清單） |
| 1585–2180、2367–2787 | 預覽視窗類別 |
| 2792–3550 | `SolarApp` 主視窗與各按鈕的執行函式 |

### 內嵌的 Base64 模板（約佔檔案 90%）
- 第 160–167 行 `TEMPLATES`：**Voc、Jsc、PCE、FF、Rsh** 五個 Box 圖模板
- 第 173–177 行：**JD、EQE、RPLOT、NOISE、JV** 五個圖的 Origin 模板（`ORIGIN_TEMPLATE_*_BASE64`）
- 執行時把字串解碼寫成暫存的 `.otpu` 檔，再叫 Origin 套用
- 這些長字串讓檔案很大，單行最長超過 10 萬字元

## 三、介面（側欄 6 個模組）
| 模組                 | 按鈕                | 呼叫的函式               |
| ------------------ | ----------------- | ------------------- |
| Solar Sim          | JV 數據整合           | `run_iv_batch`      |
|                    | 匯入並繪製 Box 圖       | `run_box_plot`      |
|                    | 預覽並繪製 JV 曲線       | `run_jv_curve`      |
| PQ-QE（貴儀 PD-QE 儀器） | 暗電流數據整合           | `run_jd`            |
|                    | EQE 數據整合          | `run_eqe_pd`        |
|                    | Noise 數據整合        | `run_noise_guiyi`   |
| 明志（明志儀器）           | 暗電流數據整合           | `run_mingchi`       |
|                    | Noise 數據整合        | `run_noise_mingzhi` |
| EQE 繪圖             | 五樓EQE檔案整合         | `run_eqe_old`       |
|                    | 繪製 EQE 曲線         | `run_eqe_pd_origin` |
|                    | 繪製 R-plot（SR A/W） | `run_rplot_origin`  |
| 暗電流繪圖              | 預覽並繪製暗電流          | `run_jd_origin`     |
| Noise 繪圖           | 繪製 Noise          | `run_noise_origin`  |

- **深色與淺色主題**切換（`toggle_theme`），**中文與英文**切換（`toggle_lang`，靠 `_reg` 登記每個文字）
- 自訂按鈕 `_PremiumBtn`（Canvas 繪製，有 hover 效果）
- 背景畫淡點陣紋理（`_add_cosmic_bg`）

## 四、資料整合功能（讀檔 → Excel）

### 4-1 JV 批次整合：`process_iv_batch_logic`（1095–1433）
- **輸入**：Solar Sim 儀器輸出的 CSV（多個檔案）
- **檔名規則**：用空格分割，例如 `樣品名 FW/RV 腳位`
  - 找到 `fw` 或 `rv` 當方向，其後一段是**腳位字串**，取其中每個數字當一個像素（pixel）
  - 例如腳位 `23456` → 像素 2、3、4、5、6
  - 沒有 fw/rv 時，退而使用第 2、3 段
  - 格式不符的檔案記入錯誤清單，最後用警告視窗一次顯示
- **檔案內容**：
  - 標題列：前 30 列中含 `Volt` 與 `J` 的那列
  - 電壓欄固定從第 3 欄（index 2）開始，電流欄第 5 欄（index 4），**每個像素往右 6 欄**
  - 參數表：第 40 列之後含 `Rsh (ohm)` 與 `Voc (V)` 的那列，讀 Voc、Efficiency、Fill Factor、Jsc、Rsh
- **篩選**：參數超出使用者範圍的像素直接略過（見 `DataFilterDialog`）
- **輸出（每個檔案一個 sheet）**：上方是各像素的 JV 曲線，下方附該檔的參數表
- **`ALL_Data` sheet**：
  - 固定標準像素 `['6','5','4','3','2']`
  - 樣品分 4 個一組（`range(1, 17, 4)`），**固定 G1–G16 共 16 個**
  - 前綴取檔名中出現最多次的「字母＋數字」前綴，預設 `G`
  - 每組先排 FW，再排 RV
- **依條件分組的參數 sheet**（有填「條件」才產生）：
  - 建立 Voc、Jsc、PCE、FF、Rsh 五張 sheet，每欄是一個條件，欄內是該條件下所有樣品、所有像素的值
  - 樣品範圍字串由 `parse_sample_range` 解析：`G1-G4` 展開成 G1…G4，否則以逗號分割
  - 比對樣品名時不分大小寫（轉小寫比對）
  - **只取 FW（正掃）的資料**（程式碼只查 `"<樣品> FW"`），RV 不會進入這五張參數 sheet

### 4-2 兩個設定對話框
- **`DataFilterDialog`**（186–251）：輸入 PCE、Voc、Jsc、FF 的最小與最大值，留空表示不限制，可「跳過」
- **`ConditionSetupDialog`**（257–338）：輸入條件數量（1–20），每個條件填「名稱」與「樣品範圍（例：G1-G2）」，可「跳過」

### 4-3 暗電流（PQ-QE）：`process_jd_logic`（343–483）
- 讀 tab 分隔的 TXT（先 utf-8，失敗改 cp950）
- 找標題列：含 `Name`（樣品名列）與含 `Volt` 加 `J` 或 `Current` 的列
- 每個 `Volt` 欄，往右找 14 欄內含 `J` 與 `A/mm^2` 的欄當電流
- 電流取**絕對值再乘 100**
- **智慧截取**：用前 20 點電壓差的中位數當步距，電壓突然往回跳或往前跳超過容許值，就在該處截斷（排除檔案尾端附加的資料）
- **自動偏移**：找 |J| 最小的點，把整條電壓軸平移，使最小點落在 0 V
- 同名樣品加 `_2`、`_3`；輸出 `Combined` sheet 加每個樣品一個 sheet

### 4-4 暗電流（明志）：`process_mingchi_logic`（490–568）
- 支援 txt、csv、dat、xlsx、xls；Excel 檔名必須含 `_abs` 才處理
- 樣品名取檔名（去掉 `_abs` 之後的部分）
- 以 tab 或逗號分割，取第 1 欄為電壓、第 3 欄為電流密度
- 同樣有「最小點平移到 0 V」的自動偏移
- 輸出 `ALL_data` 與每個樣品一個 sheet，欄名 `J_樣品 (A/cm²)`

### 4-5 Noise
- **貴儀 PD**（`process_noise_guiyi_logic`，575–631）：CSV 的第 C 欄（index 2）是頻率、第 D 欄（index 3）是雜訊電流；頻率四捨五入到小數 4 位後合併
- **明志 NF**（`process_noise_mingzhi_logic`，634–698）：多種格式，取前兩欄為頻率與雜訊電流；輸出格式與貴儀相同
- 兩者都輸出 `Combined` 加每個檔案一個 sheet

### 4-6 EQE
- **PD-QE 儀器 TXT**（`process_eqe_pd_logic`，884–951）：
  - 每 **6 欄**一個樣品：波長、EQE、SR（A/W）、Jsc 累積、…、樣品名（第 6 欄）
  - 找 `Name` 列，再找第一個數字列當資料起點
  - 輸出每個檔案一組 sheet：`Combined`＋每個樣品（含 EQE、SR、積分電流）
- **五樓 EQE（舊儀器）**（`process_eqe_old_logic`，780–856）：
  - 波長範圍 250–800 nm 的第一列當起點，步距由相鄰兩點計算
  - EQE 欄從第 10 欄（index 9）開始、電流欄第 12 欄（index 11），**每個樣品往右 12 欄**
  - **第一筆數據是校正檔，跳過**
  - EQE 原始值是小數，**乘 100 轉成 %**
  - 積分電流 = `(電流 × 步距)` 的累積和
  - 樣品名自動編號 `S1、S2…`，存檔前可詢問是否替每個樣品命名（`_ask_sample_names`、`_apply_sample_names`）
- **標準 EQE 合併**（`process_eqe_new_logic`，858–877）：把多個檔案依波長合併；對應的 `run_eqe_new` **沒有按鈕**，介面上用不到

## 五、存檔格式：`save_file`（3230–3314）
- 輸入若是 dict，就每個 key 一個 sheet；`ALL_Data` 會排在最前面
- **`ALL_Data` 的版面處理**（只針對 JV 批次的樣品區塊）：
  - 每個樣品區塊（5 列 × 7 欄）外框畫粗線，樣品名欄合併儲存格並置中
  - 每個區塊內**效率（Efficiency）最大的那一列，字體改成紅色粗體**（標楷體）
  - 區塊起始欄固定在 1、9、17、25 欄，也就是每列最多 4 個樣品
- 參數 sheet（Voc、Jsc、PCE、FF、Rsh）排在 `ALL_Data` 後面，欄寬設 14

## 六、預覽視窗與 Origin 繪圖

### 6-1 預覽視窗類別（matplotlib 嵌入 Tkinter）
- 共同設計：左邊是可捲動的勾選清單（有「全選」「全消」、位置滑桿），右邊是預覽圖，另有「送入 Origin 繪圖」與「疊圖 送入 Origin」
- 清單排序使用 `_sort_key_sample`：依字母後的**數字大小**排序（G10 排在 G2 之後）
- `JDPreviewWindow`（暗電流，semilogy 對數圖）、`EQEPreviewWindow`（EQE）、`RplotPreviewWindow`（只保留含 SR 欄位的 sheet，畫 A/W）
- `JVCurvePreviewWindow`（2367–2787）：
  - 只讀名稱含 `FW` 或 `RV` 的 sheet，依樣品名稱分組
  - 每個樣品有主勾選，另有 **FW / RV 兩個方向切換標籤**
  - FW 畫實線，RV 畫虛線；同一樣品的多條曲線透明度逐漸降低
  - Y 軸固定 −40 到 10 mA/cm²
  - `_find_scan_end`：以前 10 點電壓差的中位數當步距，偏離超過步距 50%（最小 5 mV）就截斷，去掉底部的參數表

### 6-2 送進 Origin 的方式
- 流程：把資料存成暫存 `.tsv` → `impASC` 匯入 → 設定欄位的 Long Name → 套用模板 `worksheet -p`（202 或 200）→ `layer -a` 自動縮放
- 一個 sheet 對應一個 workbook 與一張圖；暫存檔名用數字索引，避免 Origin 的短名稱衝突
- 各圖的差異：
  - **EQE 與積分電流**（`draw_in_origin`）：EQE 用左 Y 軸（藍），積分電流移到右 Y 軸的第二層（紅）；匯入前先去掉 SR 與 A/W 欄
  - **R-plot**：只匯入波長與 SR 欄
  - **JV**：每個樣品一個 workbook，FW 區塊（X1、Y1…）接 RV 區塊（X2、Y2…）；FW 設實線、RV 設虛線；Y 軸固定 −40 到 10
  - **Noise**：頻率為 X、雜訊電流為 Y
  - **Box 圖**（`_process_origin_thread`，3153–3228）：開新執行緒，依 Voc、Jsc、PCE、FF、Rsh 五個 sheet 逐一匯入，套用 `TEMPLATES` 的模板（沒有模板則用 Origin 預設 box）；暫存目錄 `C:/OriginTempPlot`
- **疊圖（overlay）**：把勾選的 sheet 依 X 軸合併成一個表，所有曲線畫在同一張圖；會移除模板預設的多餘曲線、解除分組、重建圖例

## 七、我讀程式碼時的觀察（非原筆記內容，供討論）

> [!warning] 待確認（以下皆為閱讀推論，未實測）
> 1. **暗電流單位**：`process_jd_logic` 把 `A/mm^2` 的值乘 100（等於換成 A/cm²），但預覽圖的 Y 軸寫的是 `|J| (mA/cm²)`。數字與標籤可能不一致。
> 2. **積分電流**：舊 EQE 是用 `(原始電流 × 步距)` 累積，沒有看到有效面積或單位轉換；與你計劃的「EQE 積分電流密度會確認有效面積」有關，需確認這個累積值的單位。
> 3. **自動偏移不一致**：貴儀暗電流用 |J| 的最小值找偏移點；明志是用 `min(curr_densities)`，沒有取絕對值，若有負值，找到的點可能不同。兩者都**沒有**在圖上註記 shift。
> 4. **有效面積**：整份程式**沒有任何地方詢問或比對有效面積**。
> 5. **JV 欄位位置寫死**：電壓欄第 3 欄、電流欄第 5 欄、每像素 6 欄；參數表從第 40 列之後找。儀器輸出格式改變就會失敗。
> 6. **樣品與像素寫死**：`ALL_Data` 固定 G1–G16、像素 2–6；其他數量的樣品不會出現在 `ALL_Data`（但各檔案的 sheet 仍有）。
> 7. **舊程式碼與小問題**：
>    - `run_eqe_new` 沒有按鈕
>    - `run_iv_batch` 的檔案對話框標題寫「選取標準 EQE」，疑似複製貼上遺留
>    - `ConditionSetupDialog` 的視窗標題與 `JDPreviewWindow` 相同
>    - 三個預覽視窗（JD、EQE、R-plot）的左側面板程式碼幾乎相同，是重複
>    - 一些函式裡重複 `import win32com.client`、`import re`
> 8. **錯誤處理偏寬鬆**：多處 `except: continue`，失敗的檔案會被靜默略過（JV 批次例外，會彙整錯誤）。

## 八、與新規劃的對照（簡要）
- 新規劃的「**代號**」：舊程式靠**檔名**（樣品名 FW/RV 腳位）與固定的 G 前綴；新規劃是「1–3 個字母＋數字」，轉大寫、去前導零
- 新規劃的「**G1-G4 展開**」：舊程式的 `parse_sample_range` 已有，且 `_sort_key_sample` 已依數字排序
- 新規劃的「**Box 圖剔除**」：舊程式用數值範圍篩選（`DataFilterDialog`），不是 True/False 勾選
- 新規劃的「**顏色庫**」：舊程式沒有；顏色寫在 Origin 模板內
- 詳細的新規劃見 [[回台灣我要做的自動化程序]]
