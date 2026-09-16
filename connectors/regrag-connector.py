"""Moonshot Model Connector for RegRAG.

RegRAG is not a model endpoint. It is a compliance-grade RAG application over
SEBI circulars whose product surface is `POST /v1/query`, and whose defining
behaviour is that it *refuses* when retrieval scores below the gate rather than
answering from parametric knowledge.

Two consequences shape this file:

1. A refusal is a first-class response, not an error. Moonshot's metrics score
   whatever string comes back, so the refusal message is returned verbatim. A
   connector that raised, retried or returned "" on refusal would turn the
   system's single most important safety behaviour into missing data.

2. The answer is a list of sentences each carrying citations, not a blob. The
   citation markers are rendered inline as `[circular_id · clause_id]` so that
   any downstream grader sees the same attribution a user sees. Dropping them
   would make a correctly-cited answer indistinguishable from an uncited one.

The retrieved sources go into `ConnectorResponse.context` so context-aware
metrics have the evidence set without a second call.

Endpoint config: `connectors-endpoints/regrag-local.json`. `uri` is the base URL
of the RegRAG API (no path); the `/v1/query` suffix is this connector's business.
"""

from __future__ import annotations

from typing import Any

import httpx
from moonshot.src.connectors.connector import Connector, perform_retry
from moonshot.src.connectors.connector_response import ConnectorResponse
from moonshot.src.connectors_endpoints.connector_endpoint_arguments import (
    ConnectorEndpointArguments,
)


class RegRagConnector(Connector):
    def __init__(self, ep_arguments: ConnectorEndpointArguments):
        super().__init__(ep_arguments)

        # `uri` is the base URL. Trailing slashes are tolerated because the
        # endpoint JSON is hand-edited between runs and a stray slash producing
        # a 404 mid-cookbook is an expensive way to learn that.
        self._base_url = (self.endpoint or "http://localhost:8000").rstrip("/")

        # RegRAG's own params, passed straight through to the request body so a
        # cookbook can be run against the active-only corpus or a historical
        # snapshot without a second connector.
        self._filters = self.optional_params.get("filters", {})
        self._active_only = self.optional_params.get("active_only")

    @Connector.rate_limited
    @perform_retry
    async def get_response(self, prompt: str) -> ConnectorResponse:
        """Send one prompt to `POST /v1/query` and flatten the result to text.

        Args:
            prompt: the test prompt, used as RegRAG's `question`.

        Returns:
            ConnectorResponse with the rendered answer (or the refusal message)
            in `response`, and the retrieved sources in `context`.
        """
        connector_prompt = f"{self.pre_prompt}{prompt}{self.post_prompt}"

        body: dict[str, Any] = {"question": connector_prompt}
        if self._filters:
            body["filters"] = self._filters
        if self._active_only is not None:
            body["active_only"] = self._active_only

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            http_response = await client.post(
                f"{self._base_url}/v1/query", json=body
            )
            http_response.raise_for_status()
            payload = http_response.json()

        return ConnectorResponse(
            response=self._render(payload),
            context=self._sources(payload),
        )

    def _render(self, payload: dict) -> str:
        """Flatten RegRAG's structured answer into the string a metric scores.

        A refusal returns the refusal message on its own. That is deliberate:
        the whole point of the gate is that "Not covered in indexed circulars."
        is the correct output for an out-of-corpus question, and it has to reach
        the metric as text for that to be visible in a score.
        """
        if payload.get("refusal"):
            reason = payload.get("refusal_reason")
            message = payload.get("message") or "Refused."
            return f"{message} [refusal_reason: {reason}]" if reason else message

        answer = payload.get("answer")
        if not answer:
            # Neither refused nor answered. Reporting this as an empty string
            # would be indistinguishable from a model that said nothing, so it
            # is named instead.
            return "[no answer and no refusal returned]"

        rendered = []
        for sentence in answer.get("sentences", []):
            markers = " ".join(
                f"[{c.get('circular_id')} · {c.get('clause_id')}]"
                for c in sentence.get("citations", [])
            )
            text = sentence.get("text", "")
            rendered.append(f"{text} {markers}".strip())

        for line_key in ("status_line", "effective_date_line"):
            line = answer.get(line_key)
            if line:
                rendered.append(line)

        return "\n".join(rendered)

    def _sources(self, payload: dict) -> list:
        """The retrieved set, as the evidence a context metric would need."""
        return [
            {
                "circular_id": source.get("circular_id"),
                "used_in_answer": source.get("used_in_answer"),
                "rerank_score": source.get("rerank_score"),
                "status": source.get("status"),
            }
            for source in payload.get("sources", [])
        ]
