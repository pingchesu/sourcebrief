from redis import Redis
from rq import Worker

from contextsmith_shared.config import get_settings


def main() -> None:
    redis = Redis.from_url(get_settings().redis_url)
    worker = Worker(["default"], connection=redis)
    worker.work(with_scheduler=True)


if __name__ == "__main__":
    main()
