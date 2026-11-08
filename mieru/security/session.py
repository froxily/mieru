import base64
import hashlib
import hmac
import secrets
import threading
import time
from collections import deque

from fastapi import HTTPException, Request, Response

SESSION_COOKIE_NAME: str = "mieru_session"
SESSION_COOKIE_MAX_AGE_SECONDS: int = 24 * 60 * 60
MUTATION_HEADER_NAME: str = "X-MIERU-Request"
MUTATION_HEADER_VALUE: str = "1"


def sign_token(secret: bytes, token: str) -> str:
    digest = hmac.new(secret, token.encode("ascii"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def build_cookie_value(secret: bytes, token: str) -> str:
    return f"{token}.{sign_token(secret, token)}"


def verify_cookie_value(secret: bytes, cookie_value: str | None) -> str | None:
    if not cookie_value or "." not in cookie_value or len(cookie_value) > 200:
        return None
    token, signature = cookie_value.rsplit(".", 1)
    if not token or not hmac.compare_digest(signature, sign_token(secret, token)):
        return None
    return token


def owner_fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def current_session_token(request: Request) -> str | None:
    settings = request.app.state.settings
    return verify_cookie_value(settings.session_secret, request.cookies.get(SESSION_COOKIE_NAME))


def ensure_session_token(request: Request, response: Response) -> str:
    existing = current_session_token(request)
    if existing:
        return existing
    settings = request.app.state.settings
    token = secrets.token_urlsafe(32)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        build_cookie_value(settings.session_secret, token),
        max_age=SESSION_COOKIE_MAX_AGE_SECONDS,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="strict",
        path="/",
    )
    return token


def require_mutation_header(request: Request) -> None:
    if request.headers.get(MUTATION_HEADER_NAME) != MUTATION_HEADER_VALUE:
        raise HTTPException(status_code=403, detail="Missing request header; this endpoint only accepts requests from the MIERU web app.")


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            events = self._events.setdefault(key, deque())
            while events and now - events[0] > self.window_seconds:
                events.popleft()
            if len(events) >= self.limit:
                return False
            events.append(now)
            if len(self._events) > 10_000:
                for stale_key in [item for item, queue in self._events.items() if not queue]:
                    del self._events[stale_key]
            return True


def client_address(request: Request) -> str:
    return request.client.host if request.client else "unknown"
