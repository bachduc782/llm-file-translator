# LLM File Translator

LLM（AI）を使って Google Sheets・Google Docs・ローカルファイル（.xlsx / .docx / .txt）を自動翻訳するツールです。

---

## 機能

- **Google Sheets** の翻訳 — 全シートまたは特定シートのみ
- **Google Docs** の翻訳
- **ローカルファイル** の翻訳 — `.xlsx`、`.docx`、`.txt`
- 翻訳前にファイルを**自動複製**（元ファイルは変更なし）
- チャンクごとに**即時書き込み**（途中終了してもデータ損失なし）
- レート制限（429）時は**無制限自動リトライ**
- 対応 LLM プロバイダー：**NVIDIA NIM**、**OpenRouter**

---

## 動作要件

- Python **3.11** 以上（3.11 または 3.12 推奨。3.14 beta は不可）
- Google アカウント（Google Drive ファイルを翻訳する場合）
- LLM プロバイダーの API キー

---

## インストール

### 1. 仮想環境の作成

```powershell
C:\Users\<username>\AppData\Local\Programs\Python\Python311\python.exe -m venv C:\venv\llm-file-translator
```

### 2. 依存パッケージのインストール

```powershell
C:\venv\llm-file-translator\Scripts\pip.exe install -r requirements.txt
```

### 3. 起動

`run.bat` をダブルクリック、または：

```powershell
C:\venv\llm-file-translator\Scripts\python.exe ui.py
```

---

## 初回セットアップ

初回起動時にウィザードが自動表示されます。

### ステップ 1 — LLM プロバイダーを選択

| プロバイダー | 特徴 |
|---|---|
| **NVIDIA NIM** | 高速、レート上限 40 req/min |
| **OpenRouter** | 多数のモデル対応、無料枠あり（20 req/min） |

### ステップ 2 — API キーを入力

- **NVIDIA NIM**：[build.nvidia.com](https://build.nvidia.com) → Get API Key
- **OpenRouter**：[openrouter.ai/keys](https://openrouter.ai/keys)

### ステップ 3 — モデルを選択

一覧から選択するか、モデル ID を直接入力。

> 設定は `.env` ファイルに保存され、次回以降も引き継がれます。

---

## Google OAuth 設定（Google Drive を使う場合）

**初回のみ**実施が必要です。

1. メニュー **[1] Google認証 (Auth Setup)** を選択
2. ブラウザが開くので Google アカウントでログイン → アクセスを許可
3. トークンが `config/google_token.json` に保存されます

> 事前に Google Cloud Console で発行した OAuth 2.0 認証情報ファイル `config/google_credentials.json` が必要です。

---

## 使い方

### Google Sheets / Docs を翻訳する

1. **[2] Googleファイルを翻訳** を選択
2. Google ファイルの URL または File ID を1行ずつ入力し、空行で確定
3. 翻訳先言語を入力（デフォルト：`Japanese`）
4. シート名を入力（空白 = 全シート翻訳）

**使用可能な URL の例：**
```
https://docs.google.com/spreadsheets/d/1ABC.../edit
https://docs.google.com/document/d/1XYZ.../edit
```

翻訳結果は元ファイルと同じフォルダに言語サフィックス付きで複製されます：
```
MyFile  →  MyFile-jp
```

### ローカルファイル（.xlsx / .docx / .txt）を翻訳する

1. **[3] ローカルファイルを翻訳** を選択
2. ファイル選択ダイアログ、またはパスを手動入力
3. 翻訳先言語とシート名（.xlsx の場合）を入力

---

## 対応言語

言語名は英語で入力します。主な例：

| 入力名 | ファイルサフィックス |
|---|---|
| `Japanese` | `-jp` |
| `Vietnamese` | `-vn` |
| `English` | `-en` |
| `Korean` | `-ko` |
| `Chinese` | `-zh` |
| `Thai` | `-th` |
| `Indonesian` | `-id` |
| `French` | `-fr` |

---

## 翻訳スキップの対象

以下の内容は LLM に送信せず、翻訳をスキップします：

| 種別 | 例 |
|---|---|
| 2文字以下 | `OK`、`No`、`ID` |
| 数字・記号のみ | `123`、`36-11`、`100%` |
| Sheets の数式 | `=SUM(A1:A10)` |
| URL | `https://example.com` |
| メールアドレス | `user@example.com` |
| ISO 日付形式 | `2024-01-01` |

---

## ログ

実行のたびに `logs/` フォルダにログファイルが生成されます：

```
logs/
  translate_20260525_211323.log      ← Google ファイル翻訳ログ
  translate_local_20260526_....log   ← ローカルファイル翻訳ログ
  crash.log                          ← 予期しないクラッシュログ（発生時のみ）
```

ログにはタイムスタンプ、チャンクごとの進捗、エラー発生時のトレースバックが記録されます。

---

## LLM 設定の変更

プロバイダー・API キー・モデルはいつでも **[5] LLMプロバイダー設定** メニューから変更できます。

---

## よくあるエラーと対処法

| エラー | 原因 | 対処 |
|---|---|---|
| `429 Too Many Requests` | LLM レート制限超過 | 自動リトライのため操作不要 |
| `Googleトークンが見つかりません` | Google 認証未実施 | メニュー [1] Auth Setup を実行 |
| `ファイルにアクセスできません` | Google Drive の権限不足 | ファイルの共有設定を確認 |
| プロセスが突然終了する | Python 3.14 のヒープ破損 | Python 3.11 + `run.bat` を使用 |
