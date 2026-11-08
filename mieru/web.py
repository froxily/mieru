from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

CONTENT_SECURITY_POLICY: str = "; ".join(
    (
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob:",
        "font-src 'self' data:",
        "connect-src 'self'",
        "worker-src 'self' blob:",
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "object-src 'none'",
    )
)
BASELINE_SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
}
FRONTEND_MISSING_HTML: str = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>MIERU</title>
<style>body{font-family:'Segoe UI',system-ui,sans-serif;background:#f6f7f9;color:#111827;display:grid;place-items:center;height:100vh;margin:0}
main{background:#fff;border:1px solid #e5e7eb;border-radius:14px;padding:32px 40px;max-width:560px;box-shadow:0 1px 3px rgba(16,24,40,.08)}
code{background:#f3f4f6;padding:2px 6px;border-radius:6px}</style></head><body><main><h1>MIERU API is running</h1>
<p>The web interface has not been built yet. Run <code>npm --prefix frontend install</code> and
<code>npm --prefix frontend run build</code>, then restart, or use the Vite dev server on port 5173.</p>
<p>API docs: <a href="/api/docs">/api/docs</a></p></main></body></html>"""


def install_security_headers(app: FastAPI, enable_hsts: bool) -> None:
    @app.middleware("http")
    async def add_security_headers(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        response = await call_next(request)
        for header_name, header_value in BASELINE_SECURITY_HEADERS.items():
            response.headers.setdefault(header_name, header_value)
        if not request.url.path.startswith("/api/"):
            response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        if request.url.path.startswith("/api/") and "cache-control" not in response.headers:
            response.headers["Cache-Control"] = "no-store"
        if enable_hsts:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response


def resolve_static_file(dist_dir: Path, requested_path: str) -> Path | None:
    if not requested_path:
        return None
    candidate = (dist_dir / requested_path).resolve()
    try:
        candidate.relative_to(dist_dir.resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def mount_frontend(app: FastAPI, dist_dir: Path) -> None:
    index_path = dist_dir / "index.html"
    assets_dir = dist_dir / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")

    @app.get("/{requested_path:path}", include_in_schema=False)
    def serve_frontend(requested_path: str) -> Response:
        if requested_path.startswith("api/") or requested_path == "api":
            raise HTTPException(status_code=404, detail="Unknown API route.")
        if not index_path.is_file():
            return HTMLResponse(FRONTEND_MISSING_HTML, status_code=200)
        static_file = resolve_static_file(dist_dir, requested_path)
        if static_file is not None and static_file != index_path:
            return FileResponse(static_file)
        return FileResponse(index_path, headers={"Cache-Control": "no-cache"})
