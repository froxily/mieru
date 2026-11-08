import uvicorn

from mieru.config import load_settings


def main() -> None:
    settings = load_settings()
    print(f"MIERU starting on http://{settings.host}:{settings.port} (environment: {settings.environment})", flush=True)
    uvicorn.run(
        "mieru.main:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        proxy_headers=settings.forwarded_allow_ips is not None,
        forwarded_allow_ips=settings.forwarded_allow_ips,
        log_level="info",
    )


if __name__ == "__main__":
    main()
