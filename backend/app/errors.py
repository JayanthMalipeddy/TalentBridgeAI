class AppError(Exception):
    def __init__(self, code: str, message: str, status: int = 400, retryable: bool = False):
        self.code, self.message, self.status, self.retryable = code, message, status, retryable


def unavailable(agent: str):
    raise AppError("NOT_IMPLEMENTED", f"{agent} is not implemented in this foundation.", 501)
