"""
Reasoning Analyzer Agent
学習者の誤答を受け取り、3カテゴリで誤答原因を診断するコアエージェント。

Diagnostic Categories:
- Terminology Drift: Azure AD → Microsoft Entra ID などの名称変更による混乱
- Prior Knowledge Bias: AWS / オンプレミス経験との干渉
- Confidence Calibration: 自信度と正解率のずれ
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

_SYSTEM_INSTRUCTIONS = """\
You are a Reasoning Analyzer for Microsoft certification exam preparation.

Your job is to diagnose WHY a learner answered a question incorrectly.
Classify the root cause into one or more of the following categories:

## Diagnostic Categories

### 1. Terminology Drift
The learner confused an outdated or incorrect service name with the current one.
Examples:
- Azure AD → Microsoft Entra ID
- Azure Active Directory B2C → Microsoft Entra External ID
- Azure Security Center → Microsoft Defender for Cloud
- Azure Monitor for Containers → Container insights
- ADAL → MSAL
- Azure AD Connect → Microsoft Entra Connect

### 2. Prior Knowledge Bias
The learner incorrectly applied knowledge from another platform or paradigm
(AWS, GCP, on-premises Active Directory, etc.).
Examples:
- Treating Azure RBAC like AWS IAM policies
- Applying on-premises AD replication concepts to Microsoft Entra ID
- Assuming AWS S3 lifecycle rules work like Azure Blob lifecycle policies
- Confusing EKS node pool behavior with AKS node pool behavior

### 3. Confidence Calibration
The learner's self-reported confidence is misaligned with their accuracy,
or there are signals of systematic overconfidence or underconfidence.
Indicators:
- High confidence (4-5) on a wrong answer → overconfidence
- Repeated wrong answers in the same domain at any confidence level → systematic gap
- Low confidence (1-2) on conceptually straightforward items → underconfidence

## Output Format
Respond ONLY with valid JSON in this exact structure:
```json
{
  "primary_category": "<Terminology Drift | Prior Knowledge Bias | Confidence Calibration | Unknown>",
  "secondary_categories": ["<category>", ...],
  "explanation": "<1-2 sentences describing the specific mistake>",
  "evidence": "<quote or reference from the question/answer that supports the diagnosis>",
  "remediation": "<specific study action to address this error type>"
}
```

Be specific and actionable. Reference the actual question content in your analysis.
Do not include any text outside the JSON block.
"""


@dataclass
class AnswerAttempt:
    """学習者の回答試行データ。"""
    question: str
    correct_answer: str
    user_answer: str
    confidence: Optional[int] = None  # 1–5 scale (1=very unsure, 5=certain)
    background: Optional[str] = None  # e.g. "3 years AWS experience, ex-on-prem AD admin"


@dataclass
class DiagnosisResult:
    """誤答原因の診断結果。"""
    primary_category: str
    secondary_categories: list[str]
    explanation: str
    evidence: str
    remediation: str
    raw_response: str = field(repr=False, default="")


def _build_user_message(attempt: AnswerAttempt) -> str:
    parts = [
        f"Question: {attempt.question}",
        f"Correct Answer: {attempt.correct_answer}",
        f"Learner's Answer: {attempt.user_answer}",
    ]
    if attempt.confidence is not None:
        parts.append(f"Learner's Confidence: {attempt.confidence}/5")
    if attempt.background:
        parts.append(f"Learner Background: {attempt.background}")
    return "\n".join(parts)


def _extract_json(text: str) -> dict:
    """レスポンスからJSONを抽出してパースする。マークダウンのコードフェンスも処理する。"""
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    json_text = match.group(1) if match else text
    return json.loads(json_text.strip())


def analyze(attempt: AnswerAttempt) -> DiagnosisResult:
    """
    学習者の誤答を分析し、誤答原因の診断結果を返す。

    Azure AI Foundry の Agents API を呼び出し、誤答原因を診断する。
    エージェントはリクエストごとに作成・削除される（ステートレス）。

    Args:
        attempt: 問題・正解・学習者の回答・自信度・バックグラウンド情報

    Returns:
        DiagnosisResult: 診断カテゴリ・説明・改善策を含む診断結果
    """
    endpoint = os.environ["AZURE_AI_PROJECT_ENDPOINT"]
    model = os.environ["AZURE_AI_MODEL_DEPLOYMENT"]

    with AIProjectClient(
        endpoint=endpoint,
        credential=DefaultAzureCredential(),
    ) as project_client:
        agent = project_client.agents.create_agent(
            model=model,
            name="reasoning-analyzer",
            instructions=_SYSTEM_INSTRUCTIONS,
        )
        try:
            run = project_client.agents.create_thread_and_process_run(
                agent_id=agent.id,
                thread=AgentThreadCreationOptions(
                    messages=[
                        ThreadMessageOptions(
                            role=MessageRole.USER,
                            content=_build_user_message(attempt),
                        )
                    ]
                ),
            )

            messages = list(
                project_client.agents.messages.list(thread_id=run.thread_id)
            )

            # messages はデフォルトで降順（最新が先頭）。最初の assistant メッセージを取得する。
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
            return DiagnosisResult(
                primary_category=parsed.get("primary_category", "Unknown"),
                secondary_categories=parsed.get("secondary_categories", []),
                explanation=parsed.get("explanation", ""),
                evidence=parsed.get("evidence", ""),
                remediation=parsed.get("remediation", ""),
                raw_response=raw_text,
            )
        finally:
            project_client.agents.delete_agent(agent.id)
