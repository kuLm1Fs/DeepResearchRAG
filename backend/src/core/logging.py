import re
import structlog
from structlog.types import Processor

from .config import settings

SENSITIVE_PATTERNS = [
    (re.compile(r"sk-[a-zA-Z0-9]{20,}"), "sk-***REDACTED***"),
    (re.compile(r"Bearer\s+\S+"), "Bearer ***REDACTED***"),
    (re.compile(r"volcengine[_-]?api[_-]?key[=:]\s*\S+", re.IGNORECASE), "volcengine_api_key=***REDACTED***"),
]


def redact_sensitive(value: str) -> str:
    for pattern, replacement in SENSITIVE_PATTERNS:
        value = pattern.sub(replacement, value)
    return value


def add_timestamp(logger, method_name, event_dict):
    import datetime
    event_dict["timestamp"] = datetime.datetime.utcnow().isoformat()
    return event_dict


def configure_logging():
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            add_timestamp,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            Processor(googlers=redact_sensitive),  # type: ignore
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(structlog, settings.log_level.upper(), structlog.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )


def get_logger(name: str):
    return structlog.get_logger(name)