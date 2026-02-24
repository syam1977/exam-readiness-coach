"""
Scenario Challenge Agent
学習計画のドメイン・トピックに基づき、実務シナリオ型の問題を生成する。
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

_SYSTEM_INSTRUCTIONS = """\
You are a Scenario Challenge Generator for Microsoft certification exam preparation.

Your job is to create a realistic, scenario-based exam question for a given Azure domain.
The question should:
- Simulate a real-world IT decision or problem
- Have exactly 4 answer options (A, B, C, D)
- Test understanding, not just memorization
- Include a subtle distractor that traps learners with prior AWS/on-prem experience
  OR uses old Azure terminology (if relevant)

## Question Design Guidelines
- Set the scene with a specific business context (company size, requirement, constraint)
- Make the correct answer non-obvious at first glance
- Ensure only ONE clearly correct answer
- Distractors should be plausible but incorrect for a specific reason

## Output Format
Respond ONLY with valid JSON in this exact structure:
```json
{
  "domain": "<the domain this question covers>",
  "topic": "<specific topic within the domain>",
  "difficulty": "<Beginner | Intermediate | Advanced>",
  "scenario": "<2-3 sentence business scenario setup>",
  "question": "<the actual question text>",
  "options": {
    "A": "<option A text>",
    "B": "<option B text>",
    "C": "<option C text>",
    "D": "<option D text>"
  },
  "correct_answer": "<A | B | C | D>",
  "correct_answer_text": "<full text of the correct answer>",
  "explanation": "<why the correct answer is right, and why the distractors are wrong>",
  "trap": "<which distractor is the main trap and why it catches AWS/on-prem users or those with terminology confusion>"
}
```

Make questions exam-realistic. Use current Microsoft service names (e.g., Microsoft Entra ID, not Azure AD).
Do not include any text outside the JSON block.
"""


@dataclass
class ChallengeRequest:
    """問題生成リクエスト。"""
    domain: str
    exam_code: str
    topic: str = ""
    difficulty: str = "Intermediate"
    bias_risk: str = "None"  # "None" | "Low" | "Medium" | "High"


@dataclass
class ChallengeScenario:
    """生成されたシナリオ問題。"""
    domain: str
    topic: str
    difficulty: str
    scenario: str
    question: str
    options: dict[str, str]
    correct_answer: str
    correct_answer_text: str
    explanation: str
    trap: str
    raw_response: str = field(repr=False, default="")


def _build_user_message(req: ChallengeRequest) -> str:
    parts = [
        f"Exam: {req.exam_code}",
        f"Domain: {req.domain}",
    ]
    if req.topic:
        parts.append(f"Specific Topic: {req.topic}")
    parts.append(f"Difficulty: {req.difficulty}")
    if req.bias_risk not in ("None", ""):
        parts.append(
            f"Bias Risk Level: {req.bias_risk} "
            "(include a distractor targeting prior AWS/on-prem knowledge or old Azure terminology)"
        )
    parts.append("\nGenerate a scenario-based exam question for this domain.")
    return "\n".join(parts)


def _extract_json(text: str) -> dict:
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    json_text = match.group(1) if match else text
    return json.loads(json_text.strip())


def generate_challenge(req: ChallengeRequest) -> ChallengeScenario:
    """
    指定ドメインのシナリオ型試験問題を生成する。

    Args:
        req: 対象ドメイン・試験コード・難易度・バイアスリスク

    Returns:
        ChallengeScenario: 問題文・選択肢・正解・解説を含むシナリオ問題
    """
    endpoint = os.environ["AZURE_AI_PROJECT_ENDPOINT"]
    model = os.environ["AZURE_AI_MODEL_DEPLOYMENT"]

    with AIProjectClient(
        endpoint=endpoint,
        credential=DefaultAzureCredential(),
    ) as project_client:
        agent = project_client.agents.create_agent(
            model=model,
            name="scenario-challenge",
            instructions=_SYSTEM_INSTRUCTIONS,
        )
        try:
            run = project_client.agents.create_thread_and_process_run(
                agent_id=agent.id,
                thread=AgentThreadCreationOptions(
                    messages=[
                        ThreadMessageOptions(
                            role=MessageRole.USER,
                            content=_build_user_message(req),
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
            return ChallengeScenario(
                domain=parsed.get("domain", req.domain),
                topic=parsed.get("topic", req.topic),
                difficulty=parsed.get("difficulty", req.difficulty),
                scenario=parsed.get("scenario", ""),
                question=parsed.get("question", ""),
                options=parsed.get("options", {}),
                correct_answer=parsed.get("correct_answer", ""),
                correct_answer_text=parsed.get("correct_answer_text", ""),
                explanation=parsed.get("explanation", ""),
                trap=parsed.get("trap", ""),
                raw_response=raw_text,
            )
        finally:
            project_client.agents.delete_agent(agent.id)
