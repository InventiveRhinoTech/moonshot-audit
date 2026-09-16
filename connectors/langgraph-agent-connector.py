"""Moonshot Model Connector for the LangGraph regulatory agent.

The agent exposes four endpoints; only `POST /answer` is usable as a Moonshot
target. `/chat/stream` carries an interactive approval interrupt, and a batch
cookbook has no human to approve — `/answer` forces `auto_approve=True`
server-side, which is the same path the `rag-reliability-harness` graded over
HTTP. Pointing Moonshot at the same endpoint is what makes the two instruments
comparable at all; a connector aimed anywhere else would be measuring a
different system.

`auto_approve=True` is therefore disclosed in the report, not hidden here.

The agent abstains with an exact string rather than answering when the grader
calls the evidence weak. That string is returned verbatim for the same reason
RegRAG's refusal is: an abstention is the behaviour under test.

Endpoint config: `connectors-endpoints/langgraph-agent-local.json`. `uri` is the
base URL; the `/answer` suffix belongs to this connector.
"""

from __future__ import annotations

from typing import Any

import httpx
from moonshot.src.connectors.connector import Connector, perform_retry
from moonshot.src.connectors.connector_response import ConnectorResponse
from moonshot.src.connectors_endpoints.connector_endpoint_arguments import (
    ConnectorEndpointArguments,
)


class LangGraphAgentConnector(Connector):
    def __init__(self, ep_arguments: ConnectorEndpointArguments):
        super().__init__(ep_arguments)

        self._base_url = (self.endpoint or "http://localhost:8001").rstrip("/")

        # One thread per prompt by default. A shared thread would let earlier
        # prompts in a cookbook steer later ones through checkpointed state,
        # which is a contamination the scores would not show.
        self._thread_prefix = self.optional_params.get("thread_prefix", "moonshot")
        self._prompt_index = 0

    @Connector.rate_limited
    @perform_retry
    async def get_response(self, prompt: str) -> ConnectorResponse:
        """Send one prompt to `POST /answer` and return the answer text.

        Args:
            prompt: the test prompt, used as the agent's `question`.

        Returns:
            ConnectorResponse with `answer_text` in `response` and the retrieved
            chunks plus the retry depth in `context`.
        """
        connector_prompt = f"{self.pre_prompt}{prompt}{self.post_prompt}"

        self._prompt_index += 1
        body: dict[str, Any] = {
            "question": connector_prompt,
            "thread_id": f"{self._thread_prefix}-{self._prompt_index}",
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            http_response = await client.post(f"{self._base_url}/answer", json=body)
            http_response.raise_for_status()
            payload = http_response.json()

        return ConnectorResponse(
            response=payload.get("answer_text") or "[no answer_text returned]",
            context=self._context(payload),
        )

    def _context(self, payload: dict) -> list:
        """Retrieved chunks and the retry depth that produced them.

        `retry_depth` rides along because the agent can rewrite its query twice
        before answering, and an answer reached on the second rewrite is a
        different evidential claim from one reached first try.
        """
        context = [
            {
                "chunk_id": chunk.get("chunk_id"),
                "document_id": chunk.get("document_id"),
                "section_id": chunk.get("section_id"),
            }
            for chunk in payload.get("chunks", [])
        ]
        context.append({"retry_depth": payload.get("retry_depth")})
        return context
