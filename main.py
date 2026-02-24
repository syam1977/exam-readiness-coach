"""
Exam Readiness Coach - デモランナー

reasoning_analyzer を使って誤答原因を診断するデモを実行する。
"""

import io
import os
import sys

from dotenv import load_dotenv

# Windows CP932 端末でも日本語・罫線文字を正しく出力する
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf-8-sig"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from agents.reasoning_analyzer import AnswerAttempt, DiagnosisResult, analyze

load_dotenv(encoding="utf-8-sig")

# ── デモシナリオ ─────────────────────────────────────────────────────────────

DEMO_SCENARIOS: list[AnswerAttempt] = [
    # シナリオ 1: Terminology Drift（Azure AD → Microsoft Entra ID）
    AnswerAttempt(
        question=(
            "あなたの組織では、外部パートナーがAzureリソースへアクセスできるよう "
            "B2Bコラボレーションを設定する必要があります。"
            "どのサービスを使用しますか？"
        ),
        correct_answer="Microsoft Entra ID の外部コラボレーション機能（B2B）",
        user_answer="Azure Active Directory の B2B 機能",
        confidence=4,
        background="AZ-104 受験準備中。約2年前に Azure を学習し始めた。",
    ),
    # シナリオ 2: Prior Knowledge Bias（AWS IAM との混乱）
    AnswerAttempt(
        question=(
            "Azure で特定のリソースグループ内のすべての VM を起動・停止できる権限を "
            "ユーザーに付与したい。最も適切なアプローチはどれですか？"
        ),
        correct_answer=(
            "仮想マシン共同作成者ロールをリソースグループスコープでユーザーに割り当てる"
        ),
        user_answer=(
            "IAM ポリシーを作成して StartInstances と StopInstances アクションを許可し、"
            "リソースARNでVMを指定する"
        ),
        confidence=3,
        background="AWS歴3年。Azureは今年から学習開始。",
    ),
    # シナリオ 3: Confidence Calibration（高自信度での誤答）
    AnswerAttempt(
        question=(
            "Azure Storage の BLOB に対してアクセス層を自動的に移行するには "
            "何を設定しますか？"
        ),
        correct_answer="ライフサイクル管理ポリシー",
        user_answer="BLOB インデックスタグ",
        confidence=5,
        background="Azure Storage の基礎学習済み。",
    ),
]


# ── 表示ヘルパー ──────────────────────────────────────────────────────────────

def _print_separator(char: str = "─", width: int = 60) -> None:
    print(char * width)


def _print_result(scenario_num: int, attempt: AnswerAttempt, result: DiagnosisResult) -> None:
    _print_separator("═")
    print(f"  シナリオ {scenario_num}")
    _print_separator("═")

    print(f"\n【問題】\n  {attempt.question}")
    print(f"\n【正解】  {attempt.correct_answer}")
    print(f"【回答】  {attempt.user_answer}")
    if attempt.confidence is not None:
        print(f"【自信度】 {attempt.confidence}/5")
    if attempt.background:
        print(f"【背景】  {attempt.background}")

    _print_separator()
    print("\n▶ 診断結果\n")
    print(f"  主カテゴリ  : {result.primary_category}")
    if result.secondary_categories:
        print(f"  副カテゴリ  : {', '.join(result.secondary_categories)}")
    print(f"\n  説明\n  {result.explanation}")
    print(f"\n  根拠\n  {result.evidence}")
    print(f"\n  改善策\n  {result.remediation}")
    print()


# ── エントリポイント ──────────────────────────────────────────────────────────

def main() -> None:
    _required = ["AZURE_AI_PROJECT_ENDPOINT", "AZURE_AI_MODEL_DEPLOYMENT"]
    missing = [k for k in _required if not os.environ.get(k)]
    if missing:
        raise EnvironmentError(
            f"必須の環境変数が設定されていません: {', '.join(missing)}\n"
            ".env ファイルを確認してください。"
        )

    print("\n╔══════════════════════════════════════════════╗")
    print("║     Exam Readiness Coach - Reasoning Analyzer  ║")
    print("╚══════════════════════════════════════════════╝\n")
    print(f"Endpoint : {os.environ['AZURE_AI_PROJECT_ENDPOINT']}")
    print(f"Model    : {os.environ['AZURE_AI_MODEL_DEPLOYMENT']}")
    print(f"Scenarios: {len(DEMO_SCENARIOS)} 件\n")

    for i, attempt in enumerate(DEMO_SCENARIOS, start=1):
        print(f"\n[{i}/{len(DEMO_SCENARIOS)}] 診断中...")
        try:
            result = analyze(attempt)
            _print_result(i, attempt, result)
        except Exception as exc:  # pylint: disable=broad-except
            print(f"  [ERROR] シナリオ {i} の診断中にエラーが発生しました: {exc}\n")


if __name__ == "__main__":
    main()
