import json
import time
import httpx
from pydantic import ValidationError
from ..errors import AppError


class LLMClient:
    def __init__(self, settings, budget, telemetry, transport=None):
        self.settings, self.budget, self.telemetry, self.transport = settings, budget, telemetry, transport

    def capabilities(self):
        s = self.settings
        return {
            "groq": {"configured": bool(s.groq_api_key.get_secret_value() and s.groq_model), "implemented": True},
            "gemini": {"configured": bool(s.gemini_api_key.get_secret_value() and s.gemini_model), "implemented": False, "reason": "Adapter pending; no calls made"},
            "ollama": {"configured": bool(s.ollama_base_url and s.ollama_model), "implemented": False, "reason": "Adapter pending; no calls made"},
        }

    async def generate_structured(self, task: str, system_prompt: str, user_payload: dict, response_model: type, provider: str | None = None):
        provider = provider or self.settings.llm_provider
        capability = self.capabilities().get(provider)
        if not capability or not capability["implemented"]:
            raise AppError("PROVIDER_UNAVAILABLE", f"Provider {provider} adapter is unavailable; use groq", 503)
        if not capability["configured"]:
            raise AppError("PROVIDER_NOT_CONFIGURED", "Set GROQ_API_KEY and GROQ_MODEL to an available JSON-mode model", 503)
        model = self.settings.groq_model
        unsupported = set(self.budget.limits.get(provider, {})) - {"requests", "tokens"}
        if unsupported:
            raise AppError("QUOTA_UNSUPPORTED", "Groq adapter cannot estimate credits, minutes or money; calls disabled for these limits", 503)
        messages = [{"role": "system", "content": system_prompt + "\nReturn only JSON matching this schema: " + json.dumps(response_model.model_json_schema())}, {"role": "user", "content": json.dumps(user_payload)}]
        for attempt in range(2):
            reservation = self.budget.reserve(provider, "requests", 1)
            token_reservation = None
            # UTF-8 bytes conservatively bound input tokens, plus protocol overhead/output.
            token_bound = len(json.dumps(messages).encode("utf-8")) + self.settings.llm_max_completion_tokens + 3072
            try:
                if "tokens" in self.budget.limits.get(provider, {}):
                    token_reservation = self.budget.reserve(provider, "tokens", token_bound)
            except AppError:
                self.budget.reconcile(reservation, 0)
                raise
            started, tokens, error = time.monotonic(), None, None
            try:
                async with httpx.AsyncClient(timeout=60, transport=self.transport) as client:
                    result = await client.post("https://api.groq.com/openai/v1/chat/completions", headers={"Authorization": "Bearer " + self.settings.groq_api_key.get_secret_value()}, json={"model": model, "messages": messages, "max_completion_tokens": self.settings.llm_max_completion_tokens, "response_format": {"type": "json_object"}})
                result.raise_for_status()
                data = result.json()
                tokens = data.get("usage", {}).get("total_tokens")
                content = data["choices"][0]["message"]["content"]
                try:
                    return response_model.model_validate_json(content)
                except ValidationError:
                    error = "SCHEMA_INVALID"
                    if attempt == 1:
                        raise AppError("SCHEMA_INVALID", "Provider output failed schema validation after one repair", 502)
                    messages.append({"role": "assistant", "content": content})
                    messages.append({"role": "user", "content": "Repair your JSON to match every required type and field in the schema. Return JSON only."})
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                error = "PROVIDER_RATE_LIMITED" if status == 429 else "PROVIDER_ERROR"
                raise AppError(error, f"Groq returned HTTP {status}; check model access or quota. No automatic provider fallback was attempted.", 503 if status == 429 else 502, status == 429 or status >= 500)
            except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
                error = "PROVIDER_ERROR"
                raise AppError("PROVIDER_ERROR", "Groq request failed; check credentials, model access and provider status", 502, True)
            finally:
                elapsed = time.monotonic() - started
                if token_reservation:
                    self.budget.reconcile(token_reservation, tokens if isinstance(tokens, int) and tokens >= 0 else token_bound)
                self.budget.reconcile(reservation, 1, {"model": model, "tokens": tokens, "elapsed_seconds": elapsed, "error": error})
                self.telemetry.record(provider=provider, model=model, tokens=tokens, elapsed_seconds=elapsed, error=error)
