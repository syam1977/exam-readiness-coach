"""
agents/base.py
共通ユーティリティ — Azure AI Foundry エージェントの起動・レスポンス取得・JSONパース。

全エージェントが共有する `run_agent` と `extract_json` を提供する。
タイムアウト・リトライ・エラー表示はすべてここに集約する。
"""

import concurrent.futures
import json
import os
import re
import time

from azure.ai.agents.models import (
    AgentThreadCreationOptions,
    MessageRole,
    ThreadMessageOptions,
)
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential


def extract_json(text: str) -> dict:
    """レスポンスからJSONを抽出してパースする。マークダウンのコードフェンスも処理する。"""
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    json_text = match.group(1) if match else text
    return json.loads(json_text.strip())


def _call_agent_api(
    endpoint: str,
    model: str,
    agent_name: str,
    instructions: str,
    user_message: str,
) -> str:
    """APIコール本体。AIProjectClient を使ってエージェントを起動しレスポンスを返す。"""
    with AIProjectClient(
        endpoint=endpoint,
        credential=DefaultAzureCredential(),
    ) as client:
        agent = client.agents.create_agent(
            model=model,
            name=agent_name,
            instructions=instructions,
        )
        try:
            run = client.agents.create_thread_and_process_run(
                agent_id=agent.id,
                thread=AgentThreadCreationOptions(
                    messages=[
                        ThreadMessageOptions(
                            role=MessageRole.USER,
                            content=user_message,
                        )
                    ]
                ),
            )
            messages = list(client.agents.messages.list(thread_id=run.thread_id))
            assistant_message = next(
                (m for m in messages if m.role == MessageRole.AGENT),
                None,
            )
            if assistant_message is None:
                raise RuntimeError(
                    f"エージェントからの応答が見つかりません。Run status: {run.status}"
                )
            return "\n".join(tc.text.value for tc in assistant_message.text_messages)
        finally:
            client.agents.delete_agent(agent.id)


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

    Args:
        endpoint: Azure AI Foundry Project エンドポイント
        model: モデルデプロイメント名
        agent_name: エージェント名（Azure AI Studio 上での識別用）
        instructions: システム命令テキスト
        user_message: ユーザーメッセージテキスト
        timeout_seconds: 1回の試行のタイムアウト秒数（デフォルト30秒）
        max_retries: 失敗時のリトライ回数（デフォルト2回 = 最大3試行）

    Returns:
        エージェントのレスポンステキスト

    Raises:
        RuntimeError: 全リトライ失敗時
    """
    last_exc: Exception | None = None

    for attempt in range(max_retries + 1):
        if attempt > 0:
            time.sleep(1)

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(
                _call_agent_api,
                endpoint,
                model,
                agent_name,
                instructions,
                user_message,
            )
            return future.result(timeout=timeout_seconds)

        except concurrent.futures.TimeoutError:
            last_exc = TimeoutError(
                f"Agent '{agent_name}' が {timeout_seconds}秒でタイムアウトしました "
                f"（試行 {attempt + 1}/{max_retries + 1}）"
            )
        except Exception as exc:  # noqa: BLE001
            last_exc = exc

        finally:
            # タイムアウト時も含め、スレッドプールを解放する（スレッドは継続する場合あり）
            executor.shutdown(wait=False)

    raise RuntimeError(
        f"Agent '{agent_name}' が {max_retries + 1}回の試行後に失敗しました: {last_exc}"
    ) from last_exc
