from rq import Worker

from personal_dot.config import get_settings
from personal_dot.queue import get_queue, get_redis
from personal_dot.structured_logging import configure_logging


def main() -> None:
    settings = get_settings()
    configure_logging("worker", settings.log_level)
    connection = get_redis()
    worker = Worker([get_queue()], connection=connection)
    worker.work(with_scheduler=False)


if __name__ == "__main__":
    main()

