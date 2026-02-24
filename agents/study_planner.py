"""
Study Planner Agent
シラバス解析結果と学習者プロファイルをもとに、優先度付きの学習計画を立案する。
"""

import json
import os
import re
from dataclasses import dataclass, field
from typing import Optional

from azure.ai.agents.models import (
    AgentThreadCreationOptions,
    MessageRole,
    ThreadMessageOptions,
)
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

from agents.syllabus_analyst import SyllabusResult

_SYSTEM_INSTRUCTIONS = """\
You are a Study Planner for Microsoft certification exam preparation.

Your job is to create a personalized, prioritized study plan based on:
- The exam syllabus structure (domains and their weights)
- The learner's background and experience
- Any known weak areas or biases (e.g., AWS background causing Azure RBAC confusion)

## Planning Principles
1. Prioritize high-weight domains first
2. Flag domains where prior knowledge bias is likely
3. Identify quick wins (topics the learner likely knows from background)
4. Allocate more study time to complex/unfamiliar areas
5. Include specific Microsoft Learn paths or documentation references

## Output Format
Respond ONLY with valid JSON in this exact structure:
```json
{
  "total_weeks": <integer>,
  "weekly_hours": <integer>,
  "study_priorities": [
    {
      "rank": <integer starting from 1>,
      "domain": "<domain name>",
      "reason": "<why this is prioritized>",
      "estimated_hours": <integer>,
      "bias_risk": "<None | Low | Medium | High>",
      "bias_detail": "<specific bias risk if any, else null>"
    }
  ],
  "weak_areas": ["<area1>", "<area2>", "..."],
  "quick_wins": ["<topic learner likely already knows>", "..."],
  "daily_focus": "<one key piece of advice for daily study>",
  "terminology_priorities": ["<term to master first>", "..."]
}
```

Be specific and actionable. Reference the learner's background in your reasoning.
Do not include any text outside the JSON block.
"""


@dataclass
class PlanningInput:
    """学習計画立案のインプット。"""
    syllabus: SyllabusResult
    learner_background: str
    available_weeks: int = 8
    hours_per_week: int = 10
    diagnosis_history: Optional[list[str]] = None  # 過去の診断カテゴリ履歴


@dataclass
class StudyPriority:
    """優先学習ドメイン情報。"""
    rank: int
    domain: str
    reason: str
    estimated_hours: int
    bias_risk: str
    bias_detail: Optional[str]


@dataclass
class StudyPlan:
    """学習計画。"""
    total_weeks: int
    weekly_hours: int
    study_priorities: list[StudyPriority]
    weak_areas: list[str]
    quick_wins: list[str]
    daily_focus: str
    terminology_priorities: list[str]
    raw_response: str = field(repr=False, default="")


def _build_user_message(inp: PlanningInput) -> str:
    domains_summary = "\n".join(
        f"  - {d.name} ({d.weight_percent}%): {', '.join(d.key_topics[:3])}"
        for d in inp.syllabus.domains
    )
    terminology = "\n".join(f"  - {t}" for t in inp.syllabus.terminology_watch[:5])

    parts = [
        f"Exam: {inp.syllabus.exam_code} - {inp.syllabus.exam_title}",
        f"Learner Background: {inp.learner_background}",
        f"Available Study Time: {inp.available_weeks} weeks, {inp.hours_per_week} hours/week",
        "",
        "Exam Domains:",
        domains_summary,
        "",
        "Terminology to Watch:",
        terminology,
    ]
    if inp.syllabus.high_frequency_topics:
        parts += [
            "",
            "High-Frequency Topics: " + ", ".join(inp.syllabus.high_frequency_topics[:5]),
        ]
    if inp.diagnosis_history:
        parts += [
            "",
            "Past Diagnosis Categories: " + ", ".join(inp.diagnosis_history),
        ]
    parts.append("\nPlease create a prioritized study plan.")
    return "\n".join(parts)


def _extract_json(text: str) -> dict:
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    json_text = match.group(1) if match else text
    return json.loads(json_text.strip())


def create_study_plan(inp: PlanningInput) -> StudyPlan:
    """
    シラバスと学習者情報をもとに優先度付き学習計画を作成する。

    Args:
        inp: シラバス・学習者背景・利用可能時間

    Returns:
        StudyPlan: 優先ドメイン・弱点エリア・日々のアドバイスを含む学習計画
    """
    endpoint = os.environ["AZURE_AI_PROJECT_ENDPOINT"]
    model = os.environ["AZURE_AI_MODEL_DEPLOYMENT"]

    with AIProjectClient(
        endpoint=endpoint,
        credential=DefaultAzureCredential(),
    ) as project_client:
        agent = project_client.agents.create_agent(
            model=model,
            name="study-planner",
            instructions=_SYSTEM_INSTRUCTIONS,
        )
        try:
            run = project_client.agents.create_thread_and_process_run(
                agent_id=agent.id,
                thread=AgentThreadCreationOptions(
                    messages=[
                        ThreadMessageOptions(
                            role=MessageRole.USER,
                            content=_build_user_message(inp),
                        )
                    ]
                ),
            )

            messages = list(
                project_client.agents.messages.list(thread_id=run.thread_id)
            )

            assistant_message = next(
                (m for m in messages if m.role == MessageRole.AGENT),
                None,
            )
            if assistant_message is None:
                raise RuntimeError(
                    f"エージェントからの応答が見つかりません。Run status: {run.status}"
                )

            raw_text = "\n".join(
                tc.text.value for tc in assistant_message.text_messages
            )

            parsed = _extract_json(raw_text)
            priorities = [
                StudyPriority(
                    rank=p.get("rank", i + 1),
                    domain=p.get("domain", ""),
                    reason=p.get("reason", ""),
                    estimated_hours=p.get("estimated_hours", 0),
                    bias_risk=p.get("bias_risk", "None"),
                    bias_detail=p.get("bias_detail"),
                )
                for i, p in enumerate(parsed.get("study_priorities", []))
            ]
            return StudyPlan(
                total_weeks=parsed.get("total_weeks", inp.available_weeks),
                weekly_hours=parsed.get("weekly_hours", inp.hours_per_week),
                study_priorities=priorities,
                weak_areas=parsed.get("weak_areas", []),
                quick_wins=parsed.get("quick_wins", []),
                daily_focus=parsed.get("daily_focus", ""),
                terminology_priorities=parsed.get("terminology_priorities", []),
                raw_response=raw_text,
            )
        finally:
            project_client.agents.delete_agent(agent.id)
