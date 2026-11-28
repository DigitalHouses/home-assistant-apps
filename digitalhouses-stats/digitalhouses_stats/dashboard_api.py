from __future__ import annotations

import logging

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from .config import get_settings
from .ha_timezone import zone_metadata
from .db import get_db
from .protocol import ALLOWED_PRODUCTS
from .journal import APP_VERSION, dashboard_proxy, require_confirmation
from .stats import countries, history, installation_history, products, summary, versions


settings = get_settings()
logging.basicConfig(level=settings.log_level.upper())

app = FastAPI(
    title="DigitalHouses Stats Local API",
    version=APP_VERSION,
    docs_url=None,
    redoc_url=None,
)


def _validate_product(product: str | None) -> str | None:
    if product is not None and product not in ALLOWED_PRODUCTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="unsupported product",
        )
    return product


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/stats/summary")
def stats_summary(db: Session = Depends(get_db)) -> dict[str, object]:
    return {**summary(db), **zone_metadata(settings)}


@app.get("/v1/stats/products")
def stats_products(db: Session = Depends(get_db)) -> list[dict[str, object]]:
    return products(db)


@app.get("/v1/stats/versions")
def stats_versions(
    product: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    return versions(db, product=_validate_product(product))


@app.get("/v1/stats/countries")
def stats_countries(
    product: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    return countries(db, product=_validate_product(product))


@app.get("/v1/stats/history")
def stats_history(
    days: int = Query(default=30, ge=1, le=3650),
    product: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    return history(db, days=days, product=_validate_product(product))


@app.get("/v1/stats/installation-history")
def stats_installation_history(
    days: int = Query(default=7, ge=1, le=365),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    return installation_history(db, days=days)


@app.get("/v1/stats/log")
def stats_log(request: Request):
    return dashboard_proxy(settings, "/log", request.url.query)


@app.get("/v1/stats/log/toasts")
def stats_toasts(request: Request):
    return dashboard_proxy(settings, "/log/toasts", request.url.query)


@app.get("/v1/stats/log/export")
def stats_log_export(request: Request):
    return dashboard_proxy(settings, "/log/export", request.url.query)


@app.post("/v1/stats/log/clear")
async def stats_log_clear(request: Request):
    await require_confirmation(request)
    return await run_in_threadpool(dashboard_proxy, settings, "/log/clear", clear=True)
