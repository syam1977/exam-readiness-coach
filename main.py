"""
Exam Readiness Coach — Sequential Workflow

使い方:
  python main.py --mode demo                  # デモモード（シミュレート回答で自動実行）
  python main.py --mode interactive           # インタラクティブモード（3問）
  python main.py --mode interactive --questions 5  # インタラクティブモード（5問）
"""

import argparse
import io
import os
import sys
from dataclasses import dataclass, field

from dotenv import load_dotenv

# Windows CP932 端末でも日本語・罫線文字を正しく出力する
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf-8-sig"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

load_dotenv(encoding="utf-8-sig")

from rich import box
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.text import Text

from agents.adaptive_coach import CoachFeedback, CoachInput, coach
from agents.reasoning_analyzer import AnswerAttempt, DiagnosisResult, analyze
from agents.scenario_challenge import ChallengeRequest, ChallengeScenario, generate_challenge
from agents.study_planner import PlanningInput, StudyPlan, create_study_plan
from agents.syllabus_analyst import ExamRequest, SyllabusResult, analyze_syllabus

# ── 定数 ──────────────────────────────────────────────────────────────────────

DEMO_EXAM_CODE = "AZ-104"
DEMO_LEARNER_BACKGROUND = (
    "AWS歴3年のクラウドエンジニア。Azureは今年から学習開始。オンプレミスAD管理経験あり。"
)
SIMULATED_WRONG_ANSWER = (
    "IAMポリシーを作成してStartInstances / StopInstances アクションを許可し、"
    "リソースARNでVMを指定する（AWSの手法を適用）"
)
SIMULATED_CONFIDENCE = 3

# カテゴリ→表示色マッピング
CATEGORY_COLORS: dict[str, str] = {
    "Terminology Drift": "yellow",
    "Prior Knowledge Bias": "red",
    "Confidence Calibration": "cyan",
    "Unknown": "white",
}

console = Console()

# ── セッション記録 ─────────────────────────────────────────────────────────────

@dataclass
class SessionRecord:
    """1問分のセッション記録。"""
    question_num: int
    domain: str
    is_correct: bool
    user_answer: str
    correct_answer: str
    confidence: int
    diagnosis_category: str | None = None  # 不正解時のみ設定

# ── ユーティリティ ────────────────────────────────────────────────────────────

def _category_markup(cat: str) -> str:
    color = CATEGORY_COLORS.get(cat, "white")
    return f"[{color}]{escape(cat)}[/{color}]"


def _run_with_spinner(label: str, func, *args, **kwargs):
    """rich スピナーを表示しながらブロッキング関数を実行する。"""
    with Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        transient=True,
        console=console,
    ) as progress:
        progress.add_task(f"[cyan]{label}", total=None)
        return func(*args, **kwargs)

# ── 表示関数（rich） ──────────────────────────────────────────────────────────

def _print_syllabus(result: SyllabusResult) -> None:
    content = Text()
    content.append(f"試験名    : {result.exam_title}\n", style="bold")
    content.append(f"総トピック数: {result.total_topics_count}\n\n")

    content.append("ドメイン構成:\n", style="bold underline")
    for d in result.domains:
        content.append(f"  [{d.weight_percent:2d}%] {d.name}\n", style="cyan")
        for t in d.key_topics[:2]:
            content.append(f"         • {t}\n", style="dim")

    if result.terminology_watch:
        content.append("\nTerminology Watch:\n", style="bold underline yellow")
        for t in result.terminology_watch[:4]:
            content.append(f"  ⚠  {t}\n", style="yellow")

    console.print(Panel(content, title=f"[bold]STEP 1: Syllabus Analyst — {result.exam_code}[/bold]", border_style="blue"))


def _print_study_plan(plan: StudyPlan) -> None:
    content = Text()
    content.append(f"期間: {plan.total_weeks} 週間 × {plan.weekly_hours} 時間/週\n\n")

    content.append("優先学習ドメイン（上位3件）:\n", style="bold underline")
    for p in plan.study_priorities[:3]:
        bias_color = {"High": "red", "Medium": "yellow", "Low": "green"}.get(p.bias_risk, "dim")
        content.append(f"  {p.rank}. {p.domain}", style="bold")
        if p.bias_risk != "None":
            content.append(f" [バイアスリスク: {p.bias_risk}]", style=bias_color)
        content.append(f"\n     {p.reason}\n", style="dim")
        if p.bias_detail:
            content.append(f"     ⚡ {p.bias_detail}\n", style=bias_color)

    if plan.weak_areas:
        content.append(f"\n弱点エリア: {', '.join(plan.weak_areas[:3])}\n", style="red")
    if plan.quick_wins:
        content.append(f"クイックウィン: {', '.join(plan.quick_wins[:2])}\n", style="green")
    content.append(f"\n日々のフォーカス:\n  {plan.daily_focus}\n", style="italic")

    console.print(Panel(content, title="[bold]STEP 2: Study Planner — 学習計画[/bold]", border_style="blue"))


def _print_scenario_panel(scenario: ChallengeScenario, question_num: int, total: int) -> None:
    content = Text()
    content.append(f"ドメイン: {scenario.domain}  ", style="dim")
    content.append(f"トピック: {scenario.topic}  ", style="dim")
    content.append(f"難易度: {scenario.difficulty}\n\n", style="dim")
    content.append(f"{scenario.scenario}\n\n", style="italic")
    content.append(f"問: {scenario.question}\n\n", style="bold")
    for key, val in scenario.options.items():
        content.append(f"  {key}) ", style="bold cyan")
        content.append(f"{val}\n")

    console.print(Panel(
        content,
        title=f"[bold]問題 {question_num}/{total}[/bold]",
        border_style="cyan",
    ))


def _print_correct_answer(scenario: ChallengeScenario) -> None:
    content = Text()
    content.append(f"✓ 正解: {scenario.correct_answer}) {scenario.correct_answer_text}\n\n", style="bold green")
    content.append(f"解説: {scenario.explanation}\n", style="dim")
    console.print(Panel(content, title="[green bold]正解！[/green bold]", border_style="green"))


def _print_wrong_answer(scenario: ChallengeScenario, user_answer: str) -> None:
    content = Text()
    content.append(f"✗ あなたの回答: {user_answer}\n", style="bold red")
    content.append(f"✓ 正解: {scenario.correct_answer}) {scenario.correct_answer_text}\n\n", style="bold green")
    if scenario.trap:
        content.append(f"⚠ 落とし穴: {scenario.trap}\n", style="yellow")
    console.print(Panel(content, title="[red bold]不正解[/red bold]", border_style="red"))


def _print_diagnosis(result: DiagnosisResult) -> None:
    cat_color = CATEGORY_COLORS.get(result.primary_category, "white")
    content = Text()
    content.append(f"主カテゴリ : ", style="bold")
    content.append(f"{result.primary_category}\n", style=f"bold {cat_color}")
    if result.secondary_categories:
        content.append(f"副カテゴリ : ", style="bold")
        content.append(f"{', '.join(result.secondary_categories)}\n", style="dim")
    content.append(f"\n説明:\n  {result.explanation}\n", style="")
    content.append(f"\n根拠:\n  {result.evidence}\n", style="dim italic")
    content.append(f"\n改善策:\n  {result.remediation}\n", style="bold")

    console.print(Panel(
        content,
        title=f"[bold]STEP 4: Reasoning Analyzer — {_category_markup(result.primary_category)}[/bold]",
        border_style=cat_color,
    ))


def _print_coach_feedback(feedback: CoachFeedback) -> None:
    content = Text()
    content.append(f"{feedback.encouragement}\n\n", style="bold green")
    content.append(f"根本原因:\n  {feedback.root_cause_summary}\n\n")
    content.append(f"今すぐやること（30分以内）:\n  {feedback.immediate_action}\n\n", style="bold yellow")

    content.append("次のアクション:\n", style="bold underline")
    for action in feedback.next_actions:
        content.append(f"  {action.priority}. [{action.time_estimate}] {action.action}\n")
        if action.resource:
            content.append(f"     → {action.resource}\n", style="cyan underline")

    if feedback.review_topics:
        content.append(f"\n復習トピック: {', '.join(feedback.review_topics)}\n", style="dim")
    content.append(f"\n自信度アドバイス:\n  {feedback.confidence_tip}\n", style="italic")
    content.append(f"\n学習計画との関係:\n  {feedback.progress_note}\n", style="dim")

    console.print(Panel(content, title="[bold]STEP 5: Adaptive Coach — フィードバック[/bold]", border_style="blue"))


def _print_session_summary(records: list[SessionRecord]) -> None:
    if not records:
        return

    total = len(records)
    correct = sum(1 for r in records if r.is_correct)
    accuracy = int(correct / total * 100) if total > 0 else 0

    # エラーパターン集計
    cats = {"Terminology Drift": 0, "Prior Knowledge Bias": 0, "Confidence Calibration": 0}
    for r in records:
        if r.diagnosis_category and r.diagnosis_category in cats:
            cats[r.diagnosis_category] += 1

    # サマリーパネル
    acc_color = "green" if accuracy >= 70 else ("yellow" if accuracy >= 40 else "red")
    summary_lines = (
        f"出題数: [bold]{total}[/bold]問  "
        f"正解数: [bold green]{correct}[/bold green]問  "
        f"正答率: [bold {acc_color}]{accuracy}%[/bold {acc_color}]"
    )

    wrong_records = [r for r in records if not r.is_correct]
    dominant_cat = max(cats, key=lambda k: cats[k]) if wrong_records and any(cats.values()) else None
    top_domain = wrong_records[0].domain if wrong_records else None

    if dominant_cat and cats[dominant_cat] > 0:
        cat_color = CATEGORY_COLORS.get(dominant_cat, "white")
        summary_lines += (
            f"\n\n最優先改善エリア: [bold]{escape(top_domain or '')}[/bold]\n"
            f"（[{cat_color}]{escape(dominant_cat)}[/{cat_color}] が集中しています）"
        )

    console.print()
    console.print(Panel(summary_lines, title="[bold]セッションサマリー[/bold]", border_style="bold green"))

    # エラーパターン表
    table = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan", min_width=44)
    table.add_column("カテゴリ", no_wrap=True)
    table.add_column("件数", justify="center", width=6)

    for cat, count in cats.items():
        color = CATEGORY_COLORS.get(cat, "white")
        table.add_row(f"[{color}]{escape(cat)}[/{color}]", str(count))

    console.print(table)
    console.print()

# ── ワークフロー共通ヘルパー ──────────────────────────────────────────────────

def _prepare_session(exam_code: str, background: str) -> tuple[SyllabusResult, StudyPlan]:
    """Syllabus Analyst + Study Planner を実行（セッション開始時1回のみ）。"""
    console.print(f"\n[bold]Endpoint : {os.environ['AZURE_AI_PROJECT_ENDPOINT']}[/bold]")
    console.print(f"[bold]Model    : {os.environ['AZURE_AI_MODEL_DEPLOYMENT']}[/bold]\n")

    syllabus = _run_with_spinner(
        "Syllabus Analyst が解析中...",
        analyze_syllabus,
        ExamRequest(exam_code=exam_code, learner_background=background),
    )
    _print_syllabus(syllabus)

    study_plan = _run_with_spinner(
        "Study Planner が学習計画を立案中...",
        create_study_plan,
        PlanningInput(
            syllabus=syllabus,
            learner_background=background,
            available_weeks=8,
            hours_per_week=10,
        ),
    )
    _print_study_plan(study_plan)
    return syllabus, study_plan


def _run_diagnosis_and_coach(
    scenario: ChallengeScenario,
    user_answer_text: str,
    confidence: int,
    background: str,
    study_plan: StudyPlan,
) -> DiagnosisResult:
    """Reasoning Analyzer + Adaptive Coach を実行し、DiagnosisResult を返す。"""
    attempt = AnswerAttempt(
        question=f"{scenario.scenario}\n{scenario.question}",
        correct_answer=f"{scenario.correct_answer}) {scenario.correct_answer_text}",
        user_answer=user_answer_text,
        confidence=confidence,
        background=background,
    )
    diagnosis = _run_with_spinner(
        "Reasoning Analyzer が誤答原因を診断中...",
        analyze,
        attempt,
    )
    _print_diagnosis(diagnosis)

    feedback = _run_with_spinner(
        "Adaptive Coach がフィードバックを生成中...",
        coach,
        CoachInput(
            diagnosis=diagnosis,
            scenario=scenario,
            study_plan=study_plan,
            user_answer=user_answer_text,
            confidence=confidence,
        ),
    )
    _print_coach_feedback(feedback)
    return diagnosis

# ── デモモード ────────────────────────────────────────────────────────────────

def run_demo_mode() -> None:
    """デモモード: シミュレート回答で5エージェントのSequential Workflowをフル実行。"""
    console.rule("[bold blue]Exam Readiness Coach — Demo Mode[/bold blue]")

    syllabus, study_plan = _prepare_session(DEMO_EXAM_CODE, DEMO_LEARNER_BACKGROUND)

    # Step 3: Scenario Challenge
    top_domain = study_plan.study_priorities[0] if study_plan.study_priorities else None
    scenario = _run_with_spinner(
        "Scenario Challenge が問題を生成中...",
        generate_challenge,
        ChallengeRequest(
            domain=top_domain.domain if top_domain else "Azure Identity and Governance",
            exam_code=DEMO_EXAM_CODE,
            difficulty="Intermediate",
            bias_risk=top_domain.bias_risk if top_domain else "Medium",
        ),
    )
    _print_scenario_panel(scenario, 1, 1)

    # 不正解をシミュレート（正解でない最初の選択肢を選ぶ）
    wrong_key = next(
        (k for k in scenario.options if k != scenario.correct_answer), "B"
    )
    wrong_answer_text = f"{wrong_key}) {scenario.options.get(wrong_key, SIMULATED_WRONG_ANSWER)}"
    _print_wrong_answer(scenario, wrong_answer_text)

    # Step 4 + 5: Reasoning Analyzer + Adaptive Coach
    diagnosis = _run_diagnosis_and_coach(
        scenario=scenario,
        user_answer_text=wrong_answer_text,
        confidence=SIMULATED_CONFIDENCE,
        background=DEMO_LEARNER_BACKGROUND,
        study_plan=study_plan,
    )

    records = [
        SessionRecord(
            question_num=1,
            domain=scenario.domain,
            is_correct=False,
            user_answer=wrong_answer_text,
            correct_answer=scenario.correct_answer_text,
            confidence=SIMULATED_CONFIDENCE,
            diagnosis_category=diagnosis.primary_category,
        )
    ]
    _print_session_summary(records)
    console.rule("[bold blue]Sequential Workflow 完了[/bold blue]")

# ── インタラクティブモード ─────────────────────────────────────────────────────

def run_interactive_mode(num_questions: int) -> None:
    """インタラクティブモード: ユーザーが実際に回答・自信度を入力する。"""
    console.rule("[bold magenta]Exam Readiness Coach — Interactive Mode[/bold magenta]")
    console.print(f"[dim]試験: {DEMO_EXAM_CODE}  出題数: {num_questions}問[/dim]\n")

    syllabus, study_plan = _prepare_session(DEMO_EXAM_CODE, DEMO_LEARNER_BACKGROUND)

    records: list[SessionRecord] = []
    priorities = study_plan.study_priorities or []

    for q_num in range(1, num_questions + 1):
        console.rule(f"[cyan]問題 {q_num}/{num_questions}[/cyan]")

        # ドメインをラウンドロビンで選択
        p = priorities[(q_num - 1) % len(priorities)] if priorities else None
        scenario = _run_with_spinner(
            "Scenario Challenge が問題を生成中...",
            generate_challenge,
            ChallengeRequest(
                domain=p.domain if p else "Azure Identity and Governance",
                exam_code=DEMO_EXAM_CODE,
                difficulty="Intermediate",
                bias_risk=p.bias_risk if p else "Medium",
            ),
        )
        _print_scenario_panel(scenario, q_num, num_questions)

        # ユーザー入力：回答
        while True:
            answer = console.input("[bold cyan]回答を入力してください (A/B/C/D): [/bold cyan]").strip().upper()
            if answer in ("A", "B", "C", "D"):
                break
            console.print("[red]A、B、C、D のいずれかを入力してください。[/red]")

        # ユーザー入力：自信度
        while True:
            try:
                conf_str = console.input("[bold cyan]自信度を入力してください (1=全く自信なし〜5=確信): [/bold cyan]").strip()
                confidence = int(conf_str)
                if 1 <= confidence <= 5:
                    break
            except ValueError:
                pass
            console.print("[red]1〜5 の整数を入力してください。[/red]")

        is_correct = answer == scenario.correct_answer

        if is_correct:
            _print_correct_answer(scenario)
            records.append(SessionRecord(
                question_num=q_num,
                domain=scenario.domain,
                is_correct=True,
                user_answer=answer,
                correct_answer=scenario.correct_answer_text,
                confidence=confidence,
            ))
        else:
            user_answer_text = f"{answer}) {scenario.options.get(answer, answer)}"
            _print_wrong_answer(scenario, user_answer_text)
            try:
                diagnosis = _run_diagnosis_and_coach(
                    scenario=scenario,
                    user_answer_text=user_answer_text,
                    confidence=confidence,
                    background=DEMO_LEARNER_BACKGROUND,
                    study_plan=study_plan,
                )
                records.append(SessionRecord(
                    question_num=q_num,
                    domain=scenario.domain,
                    is_correct=False,
                    user_answer=user_answer_text,
                    correct_answer=scenario.correct_answer_text,
                    confidence=confidence,
                    diagnosis_category=diagnosis.primary_category,
                ))
            except Exception as exc:  # noqa: BLE001
                console.print(f"[red bold]ERROR:[/red bold] [red]診断中にエラーが発生しました: {escape(str(exc))}[/red]")
                records.append(SessionRecord(
                    question_num=q_num,
                    domain=scenario.domain,
                    is_correct=False,
                    user_answer=user_answer_text,
                    correct_answer=scenario.correct_answer_text,
                    confidence=confidence,
                ))

    _print_session_summary(records)
    console.rule("[bold magenta]セッション終了[/bold magenta]")

# ── エントリポイント ──────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Exam Readiness Coach — Microsoft認定試験対策マルチエージェントシステム"
    )
    parser.add_argument(
        "--mode",
        choices=["demo", "interactive"],
        default="demo",
        help="実行モード: demo（自動）または interactive（手動入力）",
    )
    parser.add_argument(
        "--questions",
        type=int,
        default=3,
        metavar="N",
        help="インタラクティブモードの出題数（デフォルト: 3）",
    )
    args = parser.parse_args()

    required = ["AZURE_AI_PROJECT_ENDPOINT", "AZURE_AI_MODEL_DEPLOYMENT"]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        console.print(
            f"[red bold]ERROR:[/red bold] [red]必須の環境変数が設定されていません: "
            f"{', '.join(missing)}\n.env ファイルを確認してください。[/red]"
        )
        sys.exit(1)

    try:
        if args.mode == "demo":
            run_demo_mode()
        else:
            run_interactive_mode(args.questions)
    except KeyboardInterrupt:
        console.print("\n[yellow]中断されました。[/yellow]")
    except Exception as exc:  # noqa: BLE001
        console.print(f"\n[red bold]FATAL ERROR:[/red bold] [red]{escape(str(exc))}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
