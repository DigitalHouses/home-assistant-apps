from __future__ import annotations

import logging

from fastapi import Depends, FastAPI, HTTPException, Query, status
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .protocol import ALLOWED_PRODUCTS
from .stats import countries, history, products, summary, versions


settings = get_settings()
logging.basicConfig(level=settings.log_level.upper())

app = FastAPI(
    title="DigitalHouses Stats Local API",
    version="0.4.0",
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
    return summary(db)


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
