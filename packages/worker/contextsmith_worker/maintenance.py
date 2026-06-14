from __future__ import annotations

import signal
import sys
import time


def main() -> None:
    running = True

    def stop(_signum: int, _frame: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print("ContextSmith maintenance scheduler placeholder started", flush=True)
    while running:
        time.sleep(5)
    print("ContextSmith maintenance scheduler placeholder stopped", flush=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
