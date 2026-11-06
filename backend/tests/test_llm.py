import httpx
import pytest
from app.errors import AppError
from app.services.llm import LLMClient
from app.services.budget import BudgetService
from app.services.telemetry import Telemetry
from app.settings import Settings


async def test_one_repair_and_usage(client, contracts):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}" if len(calls) == 1 else contracts["plan"].model_dump_json()}}], "usage": {"total_tokens": 10}})
    budget = BudgetService(client.app.state.ctx.repository, {"groq": {"requests": 2}})
    llm = LLMClient(Settings(_env_file=None, groq_api_key="test", groq_model="test-only"), budget, Telemetry(), httpx.MockTransport(handler))
    result = await llm.generate_structured("plan", "test", {}, type(contracts["plan"]))
    assert result == contracts["plan"]
    assert len(calls) == 2
    assert len(client.app.state.ctx.repository.usage_records()) == 2


async def test_repair_limit_and_missing_config(client, contracts):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})
    budget = BudgetService(client.app.state.ctx.repository, {"groq": {"requests": 10}})
    llm = LLMClient(Settings(_env_file=None, groq_api_key="test", groq_model="test-only"), budget, Telemetry(), httpx.MockTransport(handler))
    with pytest.raises(AppError) as exc: await llm.generate_structured("plan", "test", {}, type(contracts["plan"]))
    assert exc.value.code == "SCHEMA_INVALID"
    assert len(calls) == 2
    llm.settings.groq_model = ""
    with pytest.raises(AppError) as exc: await llm.generate_structured("plan", "test", {}, type(contracts["plan"]))
    assert exc.value.code == "PROVIDER_NOT_CONFIGURED"
    assert len(calls) == 2


async def test_budget_blocks_before_network(client, contracts):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(500)
    settings = Settings(_env_file=None, groq_api_key="test", groq_model="test-only")
    for limits, code in [({}, "QUOTA_UNKNOWN"), ({"groq": {"requests": 2, "tokens": 1}}, "BUDGET_EXCEEDED"), ({"groq": {"requests": 2, "money": 1}}, "QUOTA_UNSUPPORTED")]:
        llm = LLMClient(settings, BudgetService(client.app.state.ctx.repository, limits), Telemetry(), httpx.MockTransport(handler))
        with pytest.raises(AppError) as exc:
            await llm.generate_structured("plan", "test", {}, type(contracts["plan"]))
        assert exc.value.code == code
    assert calls == []
