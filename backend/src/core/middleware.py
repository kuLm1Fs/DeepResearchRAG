import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from .logging import get_logger

logger = get_logger(__name__)


class TraceIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        trace_id = request.headers.get("X-Trace-ID", str(uuid.uuid4())[:8])
        request.state.trace_id = trace_id

        # Propagate to response headers
        response = await call_next(request)
        response.headers["X-Trace-ID"] = trace_id

        logger.info("request_started",
            trace_id=trace_id,
            method=request.method,
            path=request.url.path,
        )

        return response