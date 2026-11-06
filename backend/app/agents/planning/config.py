"""Planning-module options.

These are read from environment variables because ``app/settings.py`` is shared
and owned by Jayanth. An integration request (docs/priya-handoff.md) asks for
them to be added to ``Settings``; until then they are read here with safe
defaults. Values are never secrets.
"""
import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]


def _flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(os.environ.get(name, default))
    except ValueError:
        return default
    return max(low, min(high, value))


@dataclass(frozen=True)
class PlanningConfig:
    knowledge_dir: Path
    max_cv_pages: int
    allow_pending_review: bool
    enable_tavily_fallback: bool
    llamaparse_tier: str
    max_searches: int = 2
    retrieval_top_k: int = 3
    max_context_chars: int = 2400

    @property
    def unreviewed_dir(self) -> Path:
        return self.knowledge_dir / "unreviewed"


def load_config(settings=None) -> PlanningConfig:
    return PlanningConfig(
        knowledge_dir=Path(os.environ.get("PLANNING_KNOWLEDGE_DIR") or REPO_ROOT / "knowledge"),
        max_cv_pages=getattr(settings, "planning_max_cv_pages", _int("PLANNING_MAX_CV_PAGES", 10, 1, 50)),
        # Default off: only teammate-approved records are used unless a developer
        # explicitly opts in; plans then carry a "pending review" warning.
        allow_pending_review=getattr(settings, "planning_allow_pending_review", _flag("PLANNING_ALLOW_PENDING_REVIEW")),
        enable_tavily_fallback=getattr(settings, "planning_enable_tavily_fallback", _flag("PLANNING_ENABLE_TAVILY_FALLBACK")),
        # No default tier: LlamaParse costs credits, so it must be chosen explicitly.
        llamaparse_tier=getattr(settings, "planning_llamaparse_tier", os.environ.get("PLANNING_LLAMAPARSE_TIER", "").strip()),
    )
