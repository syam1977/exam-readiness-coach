"""
Syllabus Analyst Agent
Microsoft認定試験のシラバスを解析し、学習ドメイン・キーサービス・優先トピックを抽出する。
"""

import os
from dataclasses import dataclass, field
from typing import Optional

from agents.base import extract_json, run_agent

_SYSTEM_INSTRUCTIONS = """\
You are a Syllabus Analyst specializing in Microsoft certification exams.

Your job is to analyze the given exam code and extract structured information about:
- The main skill domains and their percentage weights
- Key Azure services and technologies covered
- Critical topics that frequently appear in exam questions
- Recommended study focus areas

## Output Format
Respond ONLY with valid JSON in this exact structure:
```json
{
  "exam_code": "<exam code, e.g. AZ-104>",
  "exam_title": "<full exam title>",
  "domains": [
    {
      "name": "<domain name>",
      "weight_percent": <integer 0-100>,
      "key_topics": ["<topic1>", "<topic2>", "..."]
    }
  ],
  "key_services": ["<service1>", "<service2>", "..."],
  "high_frequency_topics": ["<topic1>", "<topic2>", "..."],
  "terminology_watch": ["<old_name> → <new_name>", "..."],
  "total_topics_count": <integer>
}
```

Focus on the most current version of the exam (as of 2025-2026).
Include terminology_watch entries for services that have been renamed recently
(e.g., Azure AD → Microsoft Entra ID).
Do not include any text outside the JSON block.
"""


@dataclass
class ExamRequest:
    """シラバス解析のリクエスト。"""
    exam_code: str  # e.g. "AZ-104", "AZ-900", "SC-900"
    learner_background: Optional[str] = None


@dataclass
class Domain:
    """試験ドメイン情報。"""
    name: str
    weight_percent: int
    key_topics: list[str]


@dataclass
class SyllabusResult:
    """シラバス解析結果。"""
    exam_code: str
    exam_title: str
    domains: list[Domain]
    key_services: list[str]
    high_frequency_topics: list[str]
    terminology_watch: list[str]
    total_topics_count: int
    raw_response: str = field(repr=False, default="")


def _build_user_message(req: ExamRequest) -> str:
    parts = [f"Exam Code: {req.exam_code}"]
    if req.learner_background:
        parts.append(f"Learner Background: {req.learner_background}")
    parts.append(
        "Please analyze this exam's syllabus and provide the structured breakdown."
    )
    return "\n".join(parts)


def analyze_syllabus(req: ExamRequest) -> SyllabusResult:
    """
    試験シラバスを解析し、ドメイン・キーサービス・重要トピックを返す。

    Args:
        req: 試験コードと学習者の背景情報

    Returns:
        SyllabusResult: ドメイン構成・重要サービス・用語注意点を含む解析結果
    """
    raw_text = run_agent(
        endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"],
        model=os.environ["AZURE_AI_MODEL_DEPLOYMENT"],
        agent_name="syllabus-analyst",
        instructions=_SYSTEM_INSTRUCTIONS,
        user_message=_build_user_message(req),
    )
    parsed = extract_json(raw_text)
    domains = [
        Domain(
            name=d.get("name", ""),
            weight_percent=d.get("weight_percent", 0),
            key_topics=d.get("key_topics", []),
        )
        for d in parsed.get("domains", [])
    ]
    return SyllabusResult(
        exam_code=parsed.get("exam_code", req.exam_code),
        exam_title=parsed.get("exam_title", ""),
        domains=domains,
        key_services=parsed.get("key_services", []),
        high_frequency_topics=parsed.get("high_frequency_topics", []),
        terminology_watch=parsed.get("terminology_watch", []),
        total_topics_count=parsed.get("total_topics_count", 0),
        raw_response=raw_text,
    )
