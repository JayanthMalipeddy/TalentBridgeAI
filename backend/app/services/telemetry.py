"""Optional Langfuse tracing with allowlisted operational metadata only."""
import logging
from contextlib import contextmanager

log = logging.getLogger("talentbridge.usage")

class SafeObservation:
    def __init__(self, span=None):
        self.span = span
    def update(self, **kwargs):
        if self.span:
            try:
                self.span.update(**kwargs)
            except Exception:
                log.warning("langfuse_update_failed")

class Telemetry:
    def __init__(self, settings=None, client=None):
        self.client = client
        self.configured = bool(settings and settings.langfuse_public_key and settings.langfuse_secret_key.get_secret_value() and settings.langfuse_base_url)
        if self.configured and client is None:
            try:
                from langfuse import Langfuse
                self.client = Langfuse(public_key=settings.langfuse_public_key,
                    secret_key=settings.langfuse_secret_key.get_secret_value(),
                    base_url=settings.langfuse_base_url, environment=settings.app_env,
                    timeout=5, flush_interval=2,
                    should_export_span=lambda span: span.name.startswith("talentbridge."))
            except Exception:
                log.warning("langfuse_initialization_failed")

    def capability(self):
        return {"configured": self.configured, "available": self.client is not None,
                "reason": "Metadata tracing enabled; delivery depends on Langfuse connectivity" if self.client else "Set Langfuse keys and base URL; local logs remain enabled"}

    @contextmanager
    def observation(self, name, *, metadata=None, as_type="span", model=None):
        manager = None
        span = None
        if self.client:
            try:
                manager = self.client.start_as_current_observation(name="talentbridge." + name,
                    as_type=as_type, metadata=metadata or {}, model=model)
                span = manager.__enter__()
            except Exception:
                manager = None
                log.warning("langfuse_start_failed")
        safe = SafeObservation(span)
        try:
            yield safe
        except Exception as exc:
            # Never hand SDK the exception object: messages may contain candidate content.
            safe.update(level="ERROR", status_message=getattr(exc, "code", "INTERNAL_ERROR"))
            raise
        finally:
            if manager:
                try:
                    manager.__exit__(None, None, None)
                except Exception:
                    log.warning("langfuse_end_failed")

    def flush(self):
        if self.client:
            try:
                self.client.flush()
            except Exception:
                log.warning("langfuse_flush_failed")

    def record(self, *, provider, model, tokens, elapsed_seconds, error=None):
        log.info("llm", extra={"provider": provider, "model": model, "tokens": tokens,
                 "elapsed_seconds": elapsed_seconds, "error_code": error})
