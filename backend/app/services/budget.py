import json
import math
from uuid import uuid4
from sqlalchemy import select, func, update
from ..db import usage
from ..errors import AppError

UNITS = {"requests", "credits", "tokens", "minutes", "money"}


class BudgetService:
    """Lifetime prototype budgets; reservations survive restart, never auto-reset."""
    def __init__(self, repository, limits):
        self.repository, self.limits = repository, limits

    def reserve(self, provider, unit, amount):
        if unit not in UNITS or not math.isfinite(amount) or amount <= 0:
            raise AppError("INVALID_BUDGET", "Use a positive finite amount and supported unit")
        limit = self.limits.get(provider, {}).get(unit)
        if limit is None or not math.isfinite(limit) or limit < 0:
            raise AppError("QUOTA_UNKNOWN", f"Configure PROVIDER_BUDGET_LIMITS for {provider}/{unit}", 503)
        with self.repository.transaction() as conn:
            used = conn.execute(select(func.coalesce(func.sum(usage.c.amount), 0)).where(usage.c.provider == provider, usage.c.unit == unit)).scalar_one()
            if used + amount > limit:
                raise AppError("BUDGET_EXCEEDED", f"Budget exhausted for {provider}/{unit}: local limit {limit:g}, recorded usage {used:g}, next reservation {amount:g}. Review usage and configured limits; restart the backend after environment changes.", 429)
            id = str(uuid4())
            conn.execute(usage.insert().values(id=id, provider=provider, unit=unit, amount=amount, state="reserved", details="{}"))
            return id

    def reconcile(self, id, actual, details=None):
        if not math.isfinite(actual) or actual < 0:
            raise AppError("INVALID_BUDGET", "Actual usage must be finite and nonnegative")
        with self.repository.transaction() as conn:
            row = conn.execute(select(usage).where(usage.c.id == id)).mappings().one_or_none()
            if not row or row["state"] != "reserved":
                raise AppError("RESERVATION_CLOSED", "Reservation missing or already reconciled", 409)
            # Record reality even if provider exceeded reservation; future use stays blocked.
            conn.execute(update(usage).where(usage.c.id == id).values(amount=actual, state="reconciled", details=json.dumps(details or {})))
