---
tags: [note, git]
date: 2026-10-17
---
# .gitignore 用法筆記

## 1. 它是做什麼的
- `.gitignore` 告訴 Git「哪些**未追蹤**的檔案不要納入版本控制」
- 檔名固定為 `.gitignore`，放在專案根目錄即可（子資料夾也可以再放一份，只管該資料夾以下）
- 一行一個規則；`#` 開頭是註解；空行會被忽略
- 修改後**不需要重啟**，直接生效

## 2. 常用語法

| 寫法 | 意思 | 範例 |
|---|---|---|
| `name.txt` | 任何位置、名稱相符的檔案或資料夾 | `secret.txt` |
| `*.pyc` | `*` 代表任意字元（不含 `/`） | 所有 `.pyc` |
| `?` | 任意單一字元 | `file?.log` |
| `[abc]` | 括號內任一字元 | `file[0-9].log` |
| `dir/` | 結尾加 `/`，只比對資料夾 | `__pycache__/` |
| `/build` | 開頭加 `/`，只比對根目錄那一層 | 只擋 `./build` |
| `**/logs` | `**` 比對任意層資料夾 | 任何位置的 `logs` |
| `logs/**` | 資料夾內的全部內容 | |
| `!keep.txt` | `!` 反向規則，把前面擋掉的重新放行 | `!data/.gitkeep` |

### 重點
- 規則**由上往下**判斷，後面的覆蓋前面的
- **父資料夾被忽略時，裡面的檔案無法用 `!` 放行**
  - 錯誤：`data/` 然後 `!data/.gitkeep`（無效）
  - 正確：`data/*` 然後 `!data/.gitkeep`（本專案的寫法）
- 路徑分隔一律用 `/`，Windows 也是

## 3. 最重要的陷阱：已被追蹤的檔案不會被忽略
`.gitignore` **只對未追蹤的檔案有效**。若檔案已經 commit 過，之後才加進 `.gitignore`，Git 仍會繼續追蹤。

解法：把它從索引移除（**保留**本機檔案）：

```bash
git rm --cached 檔名            # 單一檔案
git rm -r --cached 資料夾/      # 整個資料夾
git commit -m "stop tracking ..."
```

> 注意：`--cached` 不能漏，否則會連本機檔案一起刪掉。

## 4. 空資料夾
Git 不追蹤空資料夾。要保留資料夾結構，放一個 `.gitkeep`（名稱只是慣例），並用 `!` 放行。

## 5. 除錯指令

```bash
git status --ignored            # 列出被忽略的檔案
git check-ignore -v 路徑        # 顯示該路徑是被哪一行規則擋掉的
git ls-files                    # 目前被追蹤的檔案清單
git clean -ndX                  # 預覽「只刪除被忽略的檔案」（-n 為預演，不會真的刪）
```

`git check-ignore -v` 是最好用的：規則沒作用時，先用它確認是哪一行造成的。

## 6. 其他位置的忽略規則

| 位置 | 範圍 | 是否 commit |
|---|---|---|
| 專案內 `.gitignore` | 整個團隊共用 | 會 |
| `.git/info/exclude` | 只有自己的這個 repo | 不會 |
| 全域 `core.excludesFile` | 自己電腦上所有 repo | 不會 |

適合放全域的：編輯器與系統產生的檔案（`.DS_Store`、`Thumbs.db`、`.vscode/`）。

```bash
git config --global core.excludesFile ~/.gitignore_global
```

## 7. Python 專案常用範本

```gitignore
# Python
__pycache__/
*.py[cod]
.pytest_cache/
.venv/
*.egg-info/
dist/
build/

# 編輯器 / 系統
.vscode/
.idea/
.DS_Store
Thumbs.db

# 環境與機密
.env
*.key
```

> 機密（密碼、API key）一旦 commit 過，即使之後刪除，歷史紀錄仍然看得到。應視為已外洩並更換金鑰，不能只靠 `.gitignore` 補救。

## 8. 本專案（LCT DataHub）現況

目前 `.gitignore` 內容：

```gitignore
# 工作資料與輸出
data/*
!data/.gitkeep
```

觀察：
- `data/` 內容已忽略、`.gitkeep` 放行，寫法正確
- `git status` 目前出現 `__pycache__` 的 `.pyc`（`src/lct_datahub/core/__pycache__/`、`tests/__pycache__/`）為未追蹤狀態，**建議補上 `__pycache__/`**（10/16 待處理第 6 項）
- `.venv/`、`.pytest_cache/` 目前沒有出現在 `git status`，推測因各自資料夾內已有自己的 `.gitignore`；建議仍在根目錄明列，較保險
- 建議補上的內容：

```gitignore
__pycache__/
*.py[cod]
.pytest_cache/
.venv/
```

> 本筆記僅列建議，尚未修改 `.gitignore`；要加入時再告訴我。
