"""
Adaptive Coach Agent
診断結果・問題シナリオ・学習計画を統合し、個別最適化されたフィードバックと次のステップを提示する。
"""

import json
import os
import re
from dataclasses import dataclass, field

from azure.ai.agents.models import (
    AgentThreadCreationOptions,
    MessageRole,
    ThreadMessageOptions,
)
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

from agents.reasoning_analyzer import DiagnosisResult
from agents.scenario_challenge import ChallengeScenario
from agents.study_planner import StudyPlan

_SYSTEM_INSTRUCTIONS = """\
You are an Adaptive Coach for Microsoft certification exam preparation.

Your job is to synthesize a learner's error diagnosis, the question they got wrong,
and their overall study plan to provide highly personalized coaching feedback.

## Coaching Philosophy
1. Be encouraging but honest — acknowledge the mistake without being harsh
2. Connect the error to the root cause category (Terminology Drift, Prior Knowledge Bias,
   or Confidence Calibration)
3. Give concrete, immediately actionable next steps (not vague advice)
4. Adjust tone based on confidence level: boost underconfident learners,
   reality-check overconfident ones
5. Reference specific Microsoft Learn resources or documentation when possible

## Output Format
Respond ONLY with valid JSON in this exact structure:
```json
{
  "encouragement": "<1-2 sentences of supportive, personalized message>",
  "root_cause_summary": "<plain-language explanation of WHY this error happened>",
  "immediate_action": "<the single most important thing to do in the next 30 minutes>",
  "next_actions": [
    {
      "priority": <integer 1-3>,
      "action": "<specific study action>",
      "resource": "<Microsoft Learn URL or doc title if known, else null>",
      "time_estimate": "<e.g. '20 min', '1 hour'>"
    }
  ],
  "review_topics": ["<topic1>", "<topic2>", "..."],
  "confidence_tip": "<specific advice about managing confidence for this type of question>",
  "progress_note": "<how this fits into their overall study plan>"
}
```

Be specific, reference the actual question and error. Do not include any text outside the JSON block.
"""


@dataclass
class CoachInput:
    """Adaptive Coachへのインプット。"""
    diagnosis: DiagnosisResult
    scenario: ChallengeScenario
    study_plan: StudyPlan
    user_answer: str
    confidence: int  # 1-5


@dataclass
class NextAction:
    """次に行うべき具体的アクション。"""
    priority: int
    action: str
    resource: str | None
    time_estimate: str


@dataclass
class CoachFeedback:
    """Adaptive Coachのフィードバック結果。"""
    encouragement: str
    root_cause_summary: str
    immediate_action: str
    next_actions: list[NextAction]
    review_topics: list[str]
    confidence_tip: str
    progress_note: str
    raw_response: str = field(repr=False, default="")


def _build_user_message(inp: CoachInput) -> str:
    options_text = "\n".join(
        f"  {k}: {v}" for k, v in inp.scenario.options.items()
    )
    top_priorities = inp.study_plan.study_priorities[:3]
    priority_text = "\n".join(
        f"  {p.rank}. {p.domain} (bias risk: {p.bias_risk})"
        for p in top_priorities
    )

    return f"""## Question That Was Answered Incorrectly
Domain: {inp.scenario.domain}
Topic: {inp.scenario.topic}
Difficulty: {inp.scenario.difficulty}

Scenario: {inp.scenario.scenario}
Question: {inp.scenario.question}

Options:
{options_text}

Correct Answer: {inp.scenario.correct_answer} — {inp.scenario.correct_answer_text}
Learner's Answer: {inp.user_answer}
Learner's Confidence: {inp.confidence}/5

## Error Diagnosis
Primary Category: {inp.diagnosis.primary_category}
Secondary Categories: {', '.join(inp.diagnosis.secondary_categories) if inp.diagnosis.secondary_categories else 'None'}
Explanation: {inp.diagnosis.explanation}
Evidence: {inp.diagnosis.evidence}
Suggested Remediation: {inp.diagnosis.remediation}

## Study Plan Context
Top Study Priorities:
{priority_text}

Weak Areas: {', '.join(inp.study_plan.weak_areas[:3])}
Daily Focus: {inp.study_plan.daily_focus}

Provide personalized adaptive coaching feedback."""


def _extract_json(text: str) -> dict:
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    json_text = match.group(1) if match else text
    return json.loads(json_text.strip())


def coach(inp: CoachInput) -> CoachFeedback:
    """
    診断結果・問題シナリオ・学習計画を統合し、個別最適化フィードバックを返す。

    Args:
        inp: 診断結果・シナリオ・学習計画・学習者回答・自信度

    Returns:
        CoachFeedback: 励まし・即時アクション・次のステップ・自信度アドバイス
    """
    endpoint = os.environ["AZURE_AI_PROJECT_ENDPOINT"]
    model = os.environ["AZURE_AI_MODEL_DEPLOYMENT"]

    with AIProjectClient(
        endpoint=endpoint,
        credential=DefaultAzureCredential(),
    ) as project_client:
        agent = project_client.agents.create_agent(
            model=model,
            name="adaptive-coach",
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
            next_actions = [
                NextAction(
                    priority=a.get("priority", i + 1),
                    action=a.get("action", ""),
                    resource=a.get("resource"),
                    time_estimate=a.get("time_estimate", ""),
                )
                for i, a in enumerate(parsed.get("next_actions", []))
            ]
            return CoachFeedback(
                encouragement=parsed.get("encouragement", ""),
                root_cause_summary=parsed.get("root_cause_summary", ""),
                immediate_action=parsed.get("immediate_action", ""),
                next_actions=next_actions,
                review_topics=parsed.get("review_topics", []),
                confidence_tip=parsed.get("confidence_tip", ""),
                progress_note=parsed.get("progress_note", ""),
                raw_response=raw_text,
            )
        finally:
            project_client.agents.delete_agent(agent.id)
