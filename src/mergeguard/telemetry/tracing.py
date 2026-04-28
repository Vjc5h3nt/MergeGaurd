"""OpenTelemetry tracing via Strands hooks — CloudWatch / Honeycomb."""

from __future__ import annotations

import contextlib
import contextvars
import logging
import time
from typing import Any

log = logging.getLogger(__name__)


class ReviewTrace:
    """Lightweight tracing context for a single PR review invocation."""

    def __init__(self, pr_ref: str) -> None:
        self.pr_ref = pr_ref
        self.start_time = time.time()
        self.spans: list[dict[str, Any]] = []

    def span(self, name: str, attributes: dict[str, Any] | None = None) -> SpanContext:
        return SpanContext(trace=self, name=name, attributes=attributes or {})

    def finish(self) -> dict[str, Any]:
        elapsed = time.time() - self.start_time
        summary = {
            "pr_ref": self.pr_ref,
            "duration_seconds": round(elapsed, 3),
            "span_count": len(self.spans),
            "spans": self.spans,
        }
        log.info("Review trace: %s (%.2fs)", self.pr_ref, elapsed)
        return summary


class SpanContext:
    def __init__(
        self,
        trace: ReviewTrace,
        name: str,
        attributes: dict[str, Any],
    ) -> None:
        self.trace = trace
        self.name = name
        self.attributes = attributes
        self._start = time.time()

    def __enter__(self) -> SpanContext:
        return self

    def __exit__(self, *args: Any) -> None:
        elapsed = time.time() - self._start
        span = {
            "name": self.name,
            "duration_ms": round(elapsed * 1000, 1),
            **self.attributes,
        }
        self.trace.spans.append(span)
        log.debug("Span [%s] %.1fms", self.name, elapsed * 1000)


def _try_setup_otel() -> bool:
    """Attempt to configure OpenTelemetry if sdk is installed."""
    try:
        from opentelemetry import trace  # type: ignore[import]
        from opentelemetry.sdk.trace import TracerProvider  # type: ignore[import]

        provider = TracerProvider()
        trace.set_tracer_provider(provider)
        log.info("OTel TracerProvider configured")
        return True
    except ImportError:
        log.debug("opentelemetry-sdk not installed; using lightweight ReviewTrace only")
        return False


_otel_configured: bool = False


def setup_telemetry() -> None:
    global _otel_configured
    if not _otel_configured:
        _otel_configured = _try_setup_otel()


def get_tracer(name: str = "mergeguard") -> Any:
    try:
        from opentelemetry import trace  # type: ignore[import]

        return trace.get_tracer(name)
    except ImportError:
        return None


# ---------------------------------------------------------------------------
# Active trace propagation via ContextVar
# ---------------------------------------------------------------------------

_active_trace: contextvars.ContextVar[ReviewTrace | None] = contextvars.ContextVar(
    "mergeguard_active_trace", default=None
)


def set_active_trace(trace: ReviewTrace) -> contextvars.Token:  # type: ignore[type-arg]
    return _active_trace.set(trace)


def get_active_trace() -> ReviewTrace | None:
    return _active_trace.get()


def reset_active_trace(token: contextvars.Token) -> None:  # type: ignore[type-arg]
    _active_trace.reset(token)


@contextlib.contextmanager  # type: ignore[arg-type]
def null_span():
    """No-op context manager used when no active trace exists."""
    yield
