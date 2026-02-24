"""
Exam Readiness Coach - Sequential Workflow デモ

5つのエージェントが順番に連携して動作する：
  1. Syllabus Analyst  → 試験シラバス解析
  2. Study Planner     → 学習計画立案
  3. Scenario Challenge→ 問題出題
  4. Reasoning Analyzer→ 誤答原因分析
  5. Adaptive Coach    → フィードバック・次のステップ提示
"""

import io
import os
import sys

from dotenv import load_dotenv

# Windows CP932 端末でも日本語・罫線文字を正しく出力する
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf-8-sig"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

load_dotenv(encoding="utf-8-sig")

from agents.adaptive_coach import CoachFeedback, CoachInput, coach
from agents.reasoning_analyzer import AnswerAttempt, DiagnosisResult, analyze
from agents.scenario_challenge import ChallengeRequest, ChallengeScenario, generate_challenge
from agents.study_planner import PlanningInput, StudyPlan, create_study_plan
from agents.syllabus_analyst import ExamRequest, SyllabusResult, analyze_syllabus

# ── デモ設定 ──────────────────────────────────────────────────────────────────

DEMO_EXAM_CODE = "AZ-104"
DEMO_LEARNER_BACKGROUND = "AWS歴3年のクラウドエンジニア。Azureは今年から学習開始。オンプレミスAD管理経験あり。"

# シミュレート回答（ScenarioChallengeが生成した問題に対してAWSユーザーが間違えやすい回答）
SIMULATED_WRONG_ANSWER = (
    "IAMポリシーを作成してStartInstances / StopInstances アクションを許可し、"
    "リソースARNでVMを指定する（AWSの手法を適用）"
)
SIMULATED_CONFIDENCE = 3  # 1–5スケール

# ── 表示ヘルパー ──────────────────────────────────────────────────────────────

def _sep(char: str = "─", width: int = 62) -> None:
    print(char * width)


def _header(title: str, char: str = "═") -> None:
    _sep(char)
    print(f"  {title}")
    _sep(char)


def _step(num: int, total: int, label: str) -> None:
    print(f"\n[{num}/{total}] {label}...")


# ── ステップ表示関数 ───────────────────────────────────────────────────────────

def _print_syllabus(result: SyllabusResult) -> None:
    _header(f"STEP 1: Syllabus Analyst — {result.exam_code}")
    print(f"\n試験名  : {result.exam_title}")
    print(f"総トピック数: {result.total_topics_count}")
    print("\n▶ ドメイン構成")
    for d in result.domains:
        print(f"  [{d.weight_percent:2d}%] {d.name}")
        for t in d.key_topics[:2]:
            print(f"         • {t}")
    if result.terminology_watch:
        print("\n▶ 用語注意（Terminology Watch）")
        for t in result.terminology_watch[:4]:
            print(f"  ⚠  {t}")
    print()


def _print_study_plan(plan: StudyPlan) -> None:
    _header("STEP 2: Study Planner — 学習計画")
    print(f"\n期間: {plan.total_weeks} 週間 × {plan.weekly_hours} 時間/週")
    print("\n▶ 優先学習ドメイン（上位3件）")
    for p in plan.study_priorities[:3]:
        bias_str = f" [バイアスリスク: {p.bias_risk}]" if p.bias_risk != "None" else ""
        print(f"  {p.rank}. {p.domain}{bias_str}")
        print(f"     理由: {p.reason}")
        if p.bias_detail:
            print(f"     バイアス詳細: {p.bias_detail}")
    if plan.weak_areas:
        print(f"\n▶ 弱点エリア: {', '.join(plan.weak_areas[:3])}")
    if plan.quick_wins:
        print(f"▶ 既存知識で解ける: {', '.join(plan.quick_wins[:2])}")
    print(f"\n▶ 日々のフォーカス\n  {plan.daily_focus}")
    print()


def _print_scenario(scenario: ChallengeScenario) -> None:
    _header("STEP 3: Scenario Challenge — 問題出題")
    print(f"\nドメイン: {scenario.domain}")
    print(f"トピック: {scenario.topic}")
    print(f"難易度  : {scenario.difficulty}")
    print(f"\n【シナリオ】\n{scenario.scenario}")
    print(f"\n【問題】\n{scenario.question}")
    print("\n【選択肢】")
    for key, val in scenario.options.items():
        print(f"  {key}) {val}")
    print(f"\n  ★ 正解: {scenario.correct_answer}) {scenario.correct_answer_text}")
    if scenario.trap:
        print(f"\n  ⚠ 落とし穴: {scenario.trap}")
    print()


def _print_diagnosis(attempt: AnswerAttempt, result: DiagnosisResult) -> None:
    _header("STEP 4: Reasoning Analyzer — 誤答診断")
    print(f"\n学習者の回答: {attempt.user_answer}")
    print(f"自信度      : {attempt.confidence}/5")
    _sep()
    print(f"\n▶ 主カテゴリ : {result.primary_category}")
    if result.secondary_categories:
        print(f"▶ 副カテゴリ : {', '.join(result.secondary_categories)}")
    print(f"\n▶ 説明\n  {result.explanation}")
    print(f"\n▶ 根拠\n  {result.evidence}")
    print(f"\n▶ 改善策\n  {result.remediation}")
    print()


def _print_coach_feedback(feedback: CoachFeedback) -> None:
    _header("STEP 5: Adaptive Coach — フィードバック")
    print(f"\n▶ メッセージ\n  {feedback.encouragement}")
    print(f"\n▶ 誤答の根本原因\n  {feedback.root_cause_summary}")
    print(f"\n▶ 今すぐやること（30分以内）\n  {feedback.immediate_action}")
    print("\n▶ 次のアクション")
    for action in feedback.next_actions:
        print(f"  {action.priority}. [{action.time_estimate}] {action.action}")
        if action.resource:
            print(f"     → {action.resource}")
    if feedback.review_topics:
        print(f"\n▶ 復習トピック: {', '.join(feedback.review_topics)}")
    print(f"\n▶ 自信度アドバイス\n  {feedback.confidence_tip}")
    print(f"\n▶ 学習計画との関係\n  {feedback.progress_note}")
    print()


# ── Sequential Workflow ───────────────────────────────────────────────────────

def run_sequential_workflow() -> None:
    total_steps = 5
    print("\n╔══════════════════════════════════════════════════════════╗")
    print("║         Exam Readiness Coach — Sequential Workflow          ║")
    print("╠══════════════════════════════════════════════════════════╣")
    print(f"║  Exam    : {DEMO_EXAM_CODE:<48}║")
    print(f"║  Model   : {os.environ['AZURE_AI_MODEL_DEPLOYMENT']:<48}║")
    print("╚══════════════════════════════════════════════════════════╝\n")

    # ── Step 1: Syllabus Analyst ──────────────────────────────────────────────
    _step(1, total_steps, "Syllabus Analyst — 試験シラバスを解析中")
    syllabus = analyze_syllabus(
        ExamRequest(
            exam_code=DEMO_EXAM_CODE,
            learner_background=DEMO_LEARNER_BACKGROUND,
        )
    )
    _print_syllabus(syllabus)

    # ── Step 2: Study Planner ─────────────────────────────────────────────────
    _step(2, total_steps, "Study Planner — 学習計画を立案中")
    study_plan = create_study_plan(
        PlanningInput(
            syllabus=syllabus,
            learner_background=DEMO_LEARNER_BACKGROUND,
            available_weeks=8,
            hours_per_week=10,
        )
    )
    _print_study_plan(study_plan)

    # ── Step 3: Scenario Challenge ────────────────────────────────────────────
    _step(3, total_steps, "Scenario Challenge — 問題を生成中")
    # 優先度1位のドメインから問題を生成
    top_domain = study_plan.study_priorities[0] if study_plan.study_priorities else None
    challenge_req = ChallengeRequest(
        domain=top_domain.domain if top_domain else "Azure Identity and Governance",
        exam_code=DEMO_EXAM_CODE,
        difficulty="Intermediate",
        bias_risk=top_domain.bias_risk if top_domain else "Medium",
    )
    scenario = generate_challenge(challenge_req)
    _print_scenario(scenario)

    # ── Step 4: Reasoning Analyzer ───────────────────────────────────────────
    _step(4, total_steps, "Reasoning Analyzer — 誤答原因を診断中")
    # シナリオ問題に対してシミュレート回答を作成
    attempt = AnswerAttempt(
        question=f"{scenario.scenario}\n{scenario.question}",
        correct_answer=f"{scenario.correct_answer}) {scenario.correct_answer_text}",
        user_answer=SIMULATED_WRONG_ANSWER,
        confidence=SIMULATED_CONFIDENCE,
        background=DEMO_LEARNER_BACKGROUND,
    )
    diagnosis = analyze(attempt)
    _print_diagnosis(attempt, diagnosis)

    # ── Step 5: Adaptive Coach ────────────────────────────────────────────────
    _step(5, total_steps, "Adaptive Coach — フィードバックを生成中")
    feedback = coach(
        CoachInput(
            diagnosis=diagnosis,
            scenario=scenario,
            study_plan=study_plan,
            user_answer=SIMULATED_WRONG_ANSWER,
            confidence=SIMULATED_CONFIDENCE,
        )
    )
    _print_coach_feedback(feedback)

    _sep("═")
    print("  Sequential Workflow 完了")
    _sep("═")
    print()


# ── エントリポイント ──────────────────────────────────────────────────────────

def main() -> None:
    required = ["AZURE_AI_PROJECT_ENDPOINT", "AZURE_AI_MODEL_DEPLOYMENT"]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        raise EnvironmentError(
            f"必須の環境変数が設定されていません: {', '.join(missing)}\n"
            ".env ファイルを確認してください。"
        )

    print(f"\nEndpoint : {os.environ['AZURE_AI_PROJECT_ENDPOINT']}")
    run_sequential_workflow()


if __name__ == "__main__":
    main()
