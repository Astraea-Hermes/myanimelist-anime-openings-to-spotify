"""Console + file logging with timestamps, stage banners, and countdown waits."""
import logging
import os
import sys
import time

LOGGER_NAME = "mal_openings"
LOG_FILENAME = "mal-openings.log"

_stage = {"name": "", "done": 0, "total": 0}


def setup_logger(workdir: str | None = None, verbose: bool = False) -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")

    ch = logging.StreamHandler(sys.stderr)
    ch.setLevel(logging.DEBUG if verbose else logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    if workdir:
        os.makedirs(workdir, exist_ok=True)
        fh = logging.FileHandler(os.path.join(workdir, LOG_FILENAME),
                                 encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)


def banner(stage: str, total: int) -> None:
    _stage["name"], _stage["done"], _stage["total"] = stage, 0, total
    get_logger().info("[%s] start (%d items)", stage, total)


def progress(i: int, n: int, detail: str = "") -> None:
    _stage["done"] = i
    msg = f"[{_stage['name']}] {i}/{n}"
    if detail:
        msg += f" {detail}"
    get_logger().info(msg)


def sleep_with_countdown(seconds: float, reason: str = "rate limit") -> None:
    """Sleep honoring a Retry-After style wait, logging a visible countdown."""
    logger = get_logger()
    remaining = float(seconds)
    logger.info("[%s] waiting %.0fs (%s)", _stage["name"] or "wait",
                remaining, reason)
    while remaining > 0:
        step = min(remaining, 10.0)
        time.sleep(step)
        remaining -= step
        if remaining > 15:
            logger.info("... %.0fs remaining", remaining)
