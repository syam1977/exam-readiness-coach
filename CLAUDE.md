# Exam Readiness Coach

## 概要
Microsoft認定試験対策のマルチエージェントシステム。
正誤だけでなく、なぜ間違えたかを診断することが差別化ポイント。
Microsoft Agents League Contest（Reasoning Agents トラック）提出用。

## エージェント構成（Sequential Workflow）
1. Syllabus Analyst - 試験シラバス解析
2. Study Planner - 学習計画立案
3. Scenario Challenge - 問題出題
4. Reasoning Analyzer - 誤答原因分析（コア機能）
5. Adaptive Coach - フィードバック・次のステップ提示

## 診断カテゴリ（コンテスト差別化の核心）
- Terminology Drift: Azure AD → Microsoft Entra ID などの名称変更混乱
- Prior Knowledge Bias: AWS/オンプレミス知識との干渉
- Confidence Calibration: 自信度と正解率のずれ

これら3カテゴリによる多次元エラー診断は、Microsoft Practice Assessment等の
既存ツールにない独自の差別化ポイントである。いかなる変更でもこの診断ロジックを
弱めたり省略したりしてはならない。

## 技術スタック
- Azure AI Foundry (Project Endpoint方式 ※接続文字列は使わない)
- azure-ai-projects SDK
- Python 3.11
- Sequential orchestration pattern
- rich（CLIの視覚的強化）

## ディレクトリ構成
```
exam-readiness-coach/
├── agents/
│   ├── __init__.py
│   ├── base.py              # 共通ユーティリティ（新規）
│   ├── syllabus_analyst.py
│   ├── study_planner.py
│   ├── scenario_challenge.py
│   ├── reasoning_analyzer.py
│   └── adaptive_coach.py
├── main.py
├── requirements.txt
├── .env.example
├── .gitignore
└── CLAUDE.md
```

## 実行方法
```bash
# デモモード（シミュレート回答で自動実行）
python main.py --mode demo

# インタラクティブモード（ユーザーが実際に回答・自信度を入力）
python main.py --mode interactive

# インタラクティブモード（出題数を指定）
python main.py --mode interactive --questions 5
```

## 開発方針
- コアロジックはagents/以下に各エージェントとして分割
- agents/base.py に共通処理を集約（重複排除）
- テストはtests/以下にpytest
- シークレットは.envで管理（.gitignoreに含める）

---

## ブラッシュアップ指示（Claude Code 実装タスク）

以下の改善を順番に実装すること。

---

### タスク1: 共通ユーティリティの抽出（agents/base.py 新規作成）

5つのエージェントファイルに重複している以下のコードを `agents/base.py` に集約する：

```python
# agents/base.py に実装すること

def extract_json(text: str) -> dict:
    """レスポンスからJSONを抽出してパースする。マークダウンのコードフェンスも処理する。"""
    ...

def run_agent(
    endpoint: str,
    model: str,
    agent_name: str,
    instructions: str,
    user_message: str,
    timeout_seconds: int = 30,
    max_retries: int = 2,
) -> str:
    """
    Azure AI Foundry エージェントを起動し、レスポンステキストを返す。
    create_agent → create_thread_and_process_run → messages.list → delete_agent
    の一連を内包する。タイムアウト・リトライ込み。
    """
    ...
```

各エージェントファイル（syllabus_analyst.py, study_planner.py, scenario_challenge.py,
reasoning_analyzer.py, adaptive_coach.py）は `from agents.base import run_agent, extract_json`
を使うようリファクタリングし、重複コードを削除すること。

---

### タスク2: rich によるCLI出力の強化

requirements.txt に `rich>=13.0` を追加。

main.py の表示関数を rich を使って改善する：

- 各エージェント起動時：`rich.progress` の Spinner アニメーション（"Syllabus Analyst が解析中..."）
- エラーカテゴリの色分け（Markup）：
  - Terminology Drift → `[yellow]`
  - Prior Knowledge Bias → `[red]`
  - Confidence Calibration → `[cyan]`
  - 正解 → `[green]`、不正解 → `[red]`
- 問題・選択肢は `rich.panel.Panel` で囲む
- セッションサマリーは `rich.table.Table` を使う

---

### タスク3: インタラクティブモードの追加

main.py に argparse で `--mode` フラグを追加：
- `--mode demo`（デフォルト）: 現在の動作（SIMULATED_WRONG_ANSWER でフルオート）
- `--mode interactive`: ユーザーが実際に回答・自信度を入力
- `--questions N`（オプション, デフォルト=3）: 出題数

interactive モードの流れ：
1. Syllabus Analyst → Study Planner を実行（1回のみ）
2. ループ（N問分）:
   a. Scenario Challenge が問題生成・表示
   b. ユーザーが A/B/C/D で回答入力
   c. ユーザーが自信度 1-5 を入力
   d. 正解判定を表示
   e. 不正解の場合のみ Reasoning Analyzer + Adaptive Coach を実行
   f. 正解の場合は簡単な確認メッセージのみ表示
3. セッションサマリーを表示

---

### タスク4: セッションサマリーの追加

demo・interactive 両モードで、全ステップ完了後に以下の形式でサマリーを表示：

```
╔══════════════════════════════════════════╗
║           セッションサマリー              ║
╠══════════════════════════════════════════╣
  出題数: 3問  正解数: 1問  正答率: 33%

  エラーパターン分析:
  ┌──────────────────────────┬──────┐
  │ カテゴリ                 │ 件数 │
  ├──────────────────────────┼──────┤
  │ Prior Knowledge Bias     │  2   │
  │ Terminology Drift        │  0   │
  │ Confidence Calibration   │  1   │
  └──────────────────────────┴──────┘

  最優先改善エリア: Azure RBAC
  （Prior Knowledge Bias が集中しています）
╚══════════════════════════════════════════╝
```

rich の Table を使って実装すること。

---

### タスク5: エラーハンドリングの強化

agents/base.py の `run_agent` 関数に以下を組み込む：

- Azure API 呼び出しのタイムアウト（30秒）
- JSON パース失敗時のリトライ（最大2回、間隔1秒）
- エラー時は rich の `[red]` でわかりやすいメッセージを表示して続行

---

### 実装上の絶対ルール
1. Azure AI Foundry は Project Endpoint 方式のみ（`AZURE_AI_PROJECT_ENDPOINT` 環境変数）
2. 接続文字列（connection string）は使わない
3. Sequential orchestration パターンを維持する
4. Reasoning Analyzer の3カテゴリ診断ロジックは削除・簡略化しない
5. secrets は .env で管理（ハードコード禁止）
6. UIは作らない（CLIのみ）
