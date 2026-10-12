"""Authenticated API and bundled dashboard for a single-process deployment."""

import hmac
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from importlib.resources import files
from pathlib import Path
from threading import RLock
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from tokenledger.demo import generate
from tokenledger.pricing import RateCard
from tokenledger.service import build_report, explain
from tokenledger.warehouse import Warehouse

logger = logging.getLogger("tokenledger")


class BodyLimit:
    def __init__(self, app, limit=2_000_000):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH"}:
            return await self.app(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > self.limit:
                return await JSONResponse({"detail": "request too large"}, 413)(
                    scope, receive, send
                )
            if not message.get("more_body", False):
                break
        consumed = False

        async def replay():
            nonlocal consumed
            if not consumed:
                consumed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


class Batch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    events: list[dict] = Field(min_length=1, max_length=5000)


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=3, max_length=500)


def create_app(
    data_dir: Path | None = None,
    mode: str | None = None,
    api_key: str | None = None,
    bootstrap_demo: bool | None = None,
) -> FastAPI:
    directory = data_dir or Path(os.getenv("TOKENLEDGER_DATA_DIR", ".local"))
    mode = mode or os.getenv("TOKENLEDGER_MODE", "demo")
    api_key = api_key if api_key is not None else os.getenv("TOKENLEDGER_API_KEY", "")
    if mode not in {"demo", "production"}:
        raise ValueError("TOKENLEDGER_MODE must be demo or production")
    if mode == "production" and len(api_key) < 32:
        raise ValueError("production requires TOKENLEDGER_API_KEY with at least 32 characters")
    if bootstrap_demo is None:
        bootstrap_demo = os.getenv("TOKENLEDGER_BOOTSTRAP_DEMO", "false").lower() == "true"
    if mode == "production" and bootstrap_demo:
        raise ValueError("demo bootstrap is forbidden in production")
    rate_path = os.getenv("TOKENLEDGER_RATE_CARD")

    @asynccontextmanager
    async def lifespan(app):
        warehouse = Warehouse(
            directory / "warehouse.duckdb", RateCard(Path(rate_path)) if rate_path else None
        )
        app.state.warehouse = warehouse
        app.state.report_cache = None
        app.state.cache_lock = RLock()
        try:
            if bootstrap_demo and not warehouse.overview()["requests"]:
                records, _ = generate()
                for offset in range(0, len(records), 5000):
                    warehouse.ingest(records[offset : offset + 5000], "demo")
            yield
        finally:
            warehouse.close()

    app = FastAPI(
        title="TokenLedger AI",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs" if mode == "demo" else None,
        redoc_url=None,
        openapi_url="/openapi.json" if mode == "demo" else None,
    )
    app.add_middleware(BodyLimit)

    @app.middleware("http")
    async def observe(request, call_next):
        started = time.perf_counter()
        request_id = str(uuid4())
        response = await call_next(request)
        response.headers.update(
            {
                "X-Request-ID": request_id,
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "Cache-Control": "no-store",
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; "
                "style-src 'self'; "
                "img-src 'self' data:; connect-src 'self'; "
                "frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
            }
        )
        logger.info(
            json.dumps(
                {
                    "request_id": request_id,
                    "method": request.method,
                    "status": response.status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                }
            )
        )
        return response

    def authorize(request: Request):
        if api_key:
            supplied = request.headers.get("Authorization", "")
            if not hmac.compare_digest(supplied.encode(), ("Bearer " + api_key).encode()):
                raise HTTPException(401, "a valid bearer token is required")

    def warehouse() -> Warehouse:
        return app.state.warehouse

    def report():
        # All expensive analytics are cached; serialize misses to avoid duplicate fitting.
        with app.state.cache_lock, warehouse().snapshot():
            fingerprint = warehouse().fingerprint()
            cached = app.state.report_cache
            if cached and cached[0] == fingerprint and time.monotonic() - cached[1] < 60:
                return cached[2]
            result = build_report(warehouse())
            result["mode"] = mode
            app.state.report_cache = (fingerprint, time.monotonic(), result)
            return result

    @app.get("/healthz")
    def health():
        return {"status": "ok"}

    @app.get("/readyz")
    def ready():
        warehouse().query("SELECT 1")
        return {"status": "ready"}

    @app.get("/api/v1/report", dependencies=[Depends(authorize)])
    def get_report():
        return report()

    @app.post("/api/v1/events", dependencies=[Depends(authorize)])
    def ingest(batch: Batch):
        if not api_key:
            raise HTTPException(403, "set TOKENLEDGER_API_KEY to enable HTTP ingestion")
        result = warehouse().ingest(batch.events)
        with app.state.cache_lock:
            app.state.report_cache = None
        return result

    @app.post("/api/v1/explain", dependencies=[Depends(authorize)])
    def answer(question: Question):
        return explain(question.question, report())

    @app.get("/metrics", dependencies=[Depends(authorize)], response_class=PlainTextResponse)
    def metrics():
        info = warehouse().overview()
        return (
            "# TYPE tokenledger_events gauge\n"
            f"tokenledger_events {info['requests']}\n"
            "# TYPE tokenledger_rejected_records_total counter\n"
            f"tokenledger_rejected_records_total {info['quality']['rejected']}\n"
            "# TYPE tokenledger_cost_usd gauge\n"
            f"tokenledger_cost_usd {info['cost_usd']}\n"
        )

    static = str(files("tokenledger").joinpath("static"))
    app.mount("/static", StaticFiles(directory=static), name="static")

    @app.get("/", include_in_schema=False)
    def home():
        return FileResponse(Path(static) / "index.html")

    return app
