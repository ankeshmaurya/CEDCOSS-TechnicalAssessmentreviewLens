import httpx

from app.config import settings

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


class GroqError(Exception):
    pass


class RateLimitError(GroqError):
    def __init__(self, retry_after: str | None = None) -> None:
        self.retry_after = retry_after
        message = "Groq rate limit exceeded"
        if retry_after:
            message += f"; Retry-After: {retry_after}"
        super().__init__(message)


class ServerError(GroqError):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"Groq server error: HTTP {status_code}")


class ApiError(GroqError):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"Groq API error: HTTP {status_code}")


async def call_groq(messages: list[dict]) -> dict:
    if not settings.groq_api_key:
        raise ApiError(401)

    headers = {
        "Authorization": f"Bearer {settings.groq_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.groq_model,
        "messages": messages,
        "response_format": {"type": "json_object"},
        "temperature": 0,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(GROQ_URL, headers=headers, json=payload)

    if response.status_code == 429:
        retry_after = response.headers.get("Retry-After")
        raise RateLimitError(retry_after)
    if 500 <= response.status_code <= 599:
        raise ServerError(response.status_code)
    if response.status_code < 200 or response.status_code >= 300:
        raise ApiError(response.status_code)

    return response.json()
