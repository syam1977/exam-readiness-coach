# Exam Readiness Coach

## 概要
Microsoft認定試験対策のマルチエージェントシステム。
正誤だけでなく、なぜ間違えたかを診断することが差別化ポイント。

## エージェント構成（Sequential Workflow）
1. Syllabus Analyst - 試験シラバス解析
2. Study Planner - 学習計画立案
3. Scenario Challenge - 問題出題
4. Reasoning Analyzer - 誤答原因分析（コア機能）
5. Adaptive Coach - フィードバック・次のステップ提示

## 診断カテゴリ
- Terminology Drift: Azure AD → Microsoft Entra ID などの名称変更混乱
- Prior Knowledge Bias: AWS/オンプレミス知識との干渉
- Confidence Calibration: 自信度と正解率のずれ

## 技術スタック
- Azure AI Foundry (Project Endpoint)
- azure-ai-projects SDK
- Python 3.11
- Sequential orchestration pattern

## 開発方針
- コアロジックはagents/以下に各エージェントとして分割
- テストはtests/以下にpytest
- シークレットは.envで管理（.gitignoreに含める）
