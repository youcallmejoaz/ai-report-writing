"""Model access behind a narrow interface.

Every call is structured-output only (JSON Schema enforced by the service), at temperature 0, against a
pinned deployment. The returned ``GenerationRecord`` is attached to the report for audit.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from app.audit import canonical_json, sha256_hex
from app.domain.schemas import GenerationRecord


@dataclass(frozen=True)
class LLMResponse:
    data: dict[str, Any]
    record: GenerationRecord


class LLMClient(Protocol):
    model: str

    def complete_structured(
        self,
        *,
        stage: Literal["extract", "draft", "verify"],
        prompt_version: str,
        system: str,
        user: str,
        schema_name: str,
        json_schema: dict[str, Any],
    ) -> LLMResponse: ...


def _record(stage, model, prompt_version, system, user, output, usage) -> GenerationRecord:
    return GenerationRecord(
        stage=stage,
        model=model,
        prompt_version=prompt_version,
        input_sha256=sha256_hex(canonical_json({"system": system, "user": user})),
        output_sha256=sha256_hex(canonical_json(output)),
        usage=usage,
    )


class AzureOpenAIClient:
    """Azure OpenAI via a Standard *regional* deployment in UK South, authenticated by managed identity.

    Configuration (environment):
      AZURE_OPENAI_ENDPOINT     https://<resource>.openai.azure.com (resolves to a private endpoint)
      AZURE_OPENAI_DEPLOYMENT   deployment name pinned to a specific model version
      AZURE_OPENAI_API_VERSION  API version supporting structured outputs
    No API keys: local auth is disabled on the resource.
    """

    def __init__(self, *, endpoint: str, deployment: str, api_version: str) -> None:
        from azure.identity import DefaultAzureCredential, get_bearer_token_provider
        from openai import AzureOpenAI

        token_provider = get_bearer_token_provider(
            DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
        )
        self._client = AzureOpenAI(
            azure_endpoint=endpoint,
            azure_ad_token_provider=token_provider,
            api_version=api_version,
        )
        self.model = deployment

    @classmethod
    def from_env(cls) -> AzureOpenAIClient:
        return cls(
            endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            deployment=os.environ["AZURE_OPENAI_DEPLOYMENT"],
            api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21"),
        )

    def complete_structured(self, *, stage, prompt_version, system, user, schema_name, json_schema):
        response = self._client.chat.completions.create(
            model=self.model,
            temperature=0,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": True, "schema": json_schema},
            },
        )
        choice = response.choices[0]
        if choice.finish_reason != "stop":
            raise RuntimeError(f"model did not complete: finish_reason={choice.finish_reason}")
        data = json.loads(choice.message.content)
        usage = response.usage.model_dump() if response.usage else {}
        model = response.model or self.model
        return LLMResponse(data=data, record=_record(stage, model, prompt_version, system, user, data, usage))


class ScriptedLLMClient:
    """Deterministic stand-in for tests: returns queued responses and records what was asked."""

    def __init__(self, responses: list[dict[str, Any]], model: str = "scripted-test-model") -> None:
        self._responses = list(responses)
        self.model = model
        self.calls: list[dict[str, Any]] = []

    def complete_structured(self, *, stage, prompt_version, system, user, schema_name, json_schema):
        self.calls.append({"stage": stage, "system": system, "user": user, "schema_name": schema_name})
        data = self._responses.pop(0)
        return LLMResponse(data=data, record=_record(stage, self.model, prompt_version, system, user, data, {}))
