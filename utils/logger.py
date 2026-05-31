import logging
import json
from datetime import datetime
from pathlib import Path

from rich.logging import RichHandler


_loggers: dict[str, logging.Logger] = {}
_log_file: str = "trading_system.log"
_log_level: str = "INFO"


def configure_logging(log_file: str = "trading_system.log", log_level: str = "INFO") -> None:
    global _log_file, _log_level
    _log_file = log_file
    _log_level = log_level


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({
            "ts": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "agent": record.name,
            "msg": record.getMessage(),
        })


def get_logger(name: str) -> logging.Logger:
    if name in _loggers:
        return _loggers[name]

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    if not logger.handlers:
        fh = logging.FileHandler(_log_file, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(_JsonFormatter())

        rh = RichHandler(rich_tracebacks=True, markup=True, show_path=False)
        rh.setLevel(getattr(logging, _log_level.upper(), logging.INFO))

        logger.addHandler(fh)
        logger.addHandler(rh)

    _loggers[name] = logger
    return logger
