import logging


class Telemetry:
    def record(self, *, provider, model, tokens, elapsed_seconds, error=None):
        # Only allowlisted metadata: never prompt, exception text, CV, headers, or tokens.
        logging.getLogger("talentbridge.usage").info("llm", extra={"provider": provider, "model": model, "tokens": tokens, "elapsed_seconds": elapsed_seconds, "error_code": error})
