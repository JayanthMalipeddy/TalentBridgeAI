"""Optional general technical web research for skills with no reviewed knowledge.

* Keenable first (POST https://api.keenable.ai/v1/search, ``X-API-Key``).
* Tavily (POST https://api.tavily.com/search, ``Authorization: Bearer``) only when
  Keenable is unavailable or returned nothing AND PLANNING_ENABLE_TAVILY_FALLBACK
  is set.
* Every network call reserves budget through the shared BudgetService (fails
  closed when no allowance is configured) and is reconciled.
* Queries are built only from the fixed skill catalogue; no candidate text is
  ever sent. A final PII guard rejects anything resembling personal data.
* At most ``max_searches`` lookups per planning run. Results are cached and
  stored under knowledge/unreviewed with review_status "unreviewed"; they are
  never indexed or used as scoring criteria.
* Failures return warnings and never block planning.
"""
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import httpx
from ...errors import AppError

KEENABLE_URL = "https://api.keenable.ai/v1/search"
TAVILY_URL = "https://api.tavily.com/search"
QUERY_TEMPLATE = "{name} interview questions and evaluation criteria for integration engineers"
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"\+?\d[\d\s().-]{6,}\d")
_URL = re.compile(r"https?://|www\.", re.I)


def build_query(skill_name: str) -> str:
    return QUERY_TEMPLATE.format(name=skill_name)


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def contains_pii(query: str, allowed_words: set[str]) -> bool:
    """Allow-list guard: every query word must come from the template or skill catalogue."""
    if _EMAIL.search(query) or _PHONE.search(query) or _URL.search(query):
        return True
    return not _words(query) <= allowed_words


@dataclass
class ResearchOutcome:
    skill: str
    query: str
    provider: str | None = None
    results: list[dict] = field(default_factory=list)
    stored_as: str | None = None
    warning: str | None = None
    cached: bool = False


class WebResearch:
    def __init__(self, ctx, store_dir: Path, catalogue_names: list[str], enable_tavily_fallback: bool = False, max_searches: int = 2, transport=None):
        self.ctx, self.store_dir, self.enable_tavily_fallback = ctx, Path(store_dir), enable_tavily_fallback
        self.max_searches, self.transport, self.searches = max_searches, transport, 0
        self.queries_sent: list[str] = []
        self.allowed_words = _words(QUERY_TEMPLATE)
        for name in catalogue_names:
            self.allowed_words |= _words(name)

    def _cache_file(self, query: str) -> Path:
        return self.store_dir / f"web-{hashlib.sha256(query.encode()).hexdigest()[:16]}.json"

    async def research(self, skill: str, skill_name: str) -> ResearchOutcome:
        """Search a general technical topic. Takes no candidate data by design."""
        query = build_query(skill_name)
        outcome = ResearchOutcome(skill=skill, query=query)
        if contains_pii(query, self.allowed_words):
            outcome.warning = "Web research skipped: query failed the personal-information guard."
            return outcome
        cache = self._cache_file(query)
        if cache.is_file():
            try:
                saved = json.loads(cache.read_text(encoding="utf-8"))
                outcome.provider, outcome.results, outcome.cached = saved["provider"], saved["results"], True
                outcome.stored_as = cache.name
                return outcome
            except (OSError, json.JSONDecodeError, KeyError):
                pass
        if self.searches >= self.max_searches:
            outcome.warning = f"Web research limit reached ({self.max_searches} per plan); no search for {skill_name}."
            return outcome
        self.searches += 1
        notes = []
        for provider in ("keenable", "tavily"):
            if provider == "tavily" and not self.enable_tavily_fallback:
                notes.append("Tavily fallback disabled")
                break
            try:
                results = await self._search(provider, query)
            except AppError as exc:
                notes.append(f"{provider}: {exc.code}")
                continue
            if results:
                outcome.provider, outcome.results = provider, results
                outcome.stored_as = self._store(cache, outcome)
                return outcome
            notes.append(f"{provider}: no results")
        outcome.warning = f"Web research unavailable for {skill_name} ({'; '.join(notes)}); approved knowledge only."
        return outcome

    async def _search(self, provider: str, query: str) -> list[dict]:
        settings = self.ctx.settings
        key = (settings.keenable_api_key if provider == "keenable" else settings.tavily_api_key).get_secret_value()
        if not key:
            raise AppError("PROVIDER_NOT_CONFIGURED", f"{provider} API key not set", 503)
        reservation = self.ctx.budget.reserve(provider, "requests", 1)
        error = None
        self.queries_sent.append(query)
        try:
            async with httpx.AsyncClient(timeout=20, transport=self.transport) as client:
                if provider == "keenable":
                    response = await client.post(KEENABLE_URL, headers={"X-API-Key": key}, json={"query": query, "max_results": 3})
                else:
                    response = await client.post(TAVILY_URL, headers={"Authorization": "Bearer " + key}, json={"query": query, "max_results": 3, "search_depth": "basic"})
                response.raise_for_status()
                items = response.json().get("results") or []
            return [
                {"title": str(i.get("title", ""))[:300], "url": str(i.get("url", "")),
                 "snippet": str(i.get("snippet") if provider == "keenable" else i.get("content") or "")[:1200]}
                for i in items[:3] if i.get("url")
            ]
        except (httpx.HTTPError, ValueError, TypeError, AttributeError) as exc:
            error = type(exc).__name__
            raise AppError("PROVIDER_ERROR", f"{provider} search failed", 502, True)
        finally:
            self.ctx.budget.reconcile(reservation, 1, {"error": error})

    def _store(self, path: Path, outcome: ResearchOutcome) -> str | None:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        document_id = "web-" + path.stem.removeprefix("web-")
        payload = {
            "document_id": document_id, "provider": outcome.provider, "query": outcome.query, "skill": outcome.skill,
            "review_status": "unreviewed", "retrieved_at": now,
            "note": "Unreviewed web research. Never used for scoring; review before promoting to knowledge/references.",
            "results": [
                {"document_id": document_id, "chunk_id": f"{document_id}--{n}", "title": r["title"], "source_url": r["url"],
                 "skill": outcome.skill, "version": "1", "review_status": "unreviewed", "retrieved_at": now, "snippet": r["snippet"]}
                for n, r in enumerate(outcome.results, 1)
            ],
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            return path.name
        except OSError:
            return None
