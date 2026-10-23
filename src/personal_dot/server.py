import uvicorn

from personal_dot.config import get_settings
from personal_dot.structured_logging import configure_logging


def main() -> None:
    settings = get_settings()
    configure_logging("api", settings.log_level)
    uvicorn.run(
        "personal_dot.main:app",
        host=settings.api_host,
        port=settings.api_port,
        log_config=None,
    )


if __name__ == "__main__":
    main()

