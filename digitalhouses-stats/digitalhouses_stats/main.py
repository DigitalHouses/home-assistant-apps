from __future__ import annotations

import logging

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import get_settings
from .country import country_from_cloudflare
from .db import get_db
from .models import Heartbeat, Installation
from .protocol import ALLOWED_PRODUCTS, DeletePayload, HeartbeatPayload
from .security import bearer_token, token_hash, token_matches
from .stats import countries, history, products, summary, versions


settings = get_settings()
logging.basicConfig(level=settings.log_level.upper())

app = FastAPI(
    title="DigitalHouses Stats",
    version="0.2.0",
    docs_url=None,
    redoc_url=None,
)

MAX_TELEMETRY_BODY_BYTES = 2048


@app.middleware("http")
async def enforce_telemetry_body_limit(request: Request, call_next):
    if request.url.path in {"/v1/heartbeat", "/v1/installation"}:
        content_length = request.headers.get("content-length")
        if content_length is None:
            return Response(status_code=status.HTTP_411_LENGTH_REQUIRED)
        try:
            length = int(content_length)
        except ValueError:
            return Response(status_code=status.HTTP_400_BAD_REQUEST)
        if length < 0 or length > MAX_TELEMETRY_BODY_BYTES:
            return Response(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)

        body = await request.body()
        if len(body) > MAX_TELEMETRY_BODY_BYTES:
            return Response(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)

    return await call_next(request)


def require_json(content_type: str | None = Header(default=None)) -> None:
    media_type = (content_type or "").split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Content-Type must be application/json",
        )


def _load_installation(
    db: Session,
    *,
    product: str,
    installation_id: object,
) -> Installation | None:
    return db.get(Installation, (product, installation_id))


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/v1/heartbeat",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_json)],
)
def heartbeat(
    payload: HeartbeatPayload,
    request: Request,
    token: str = Depends(bearer_token),
    db: Session = Depends(get_db),
) -> Response:
    country = country_from_cloudflare(request.headers.get("cf-ipcountry"))

    installation = _load_installation(
        db,
        product=payload.product,
        installation_id=payload.installation_id,
    )

    if installation is None:
        installation = Installation(
            product=payload.product,
            installation_id=payload.installation_id,
            installation_token_hash=token_hash(token),
        )
        db.add(installation)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            installation = _load_installation(
                db,
                product=payload.product,
                installation_id=payload.installation_id,
            )
            if installation is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="installation registration conflict",
                )

    if not token_matches(token, installation.installation_token_hash):
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="installation token mismatch",
        )

    db.add(
        Heartbeat(
            product=payload.product,
            installation_id=payload.installation_id,
            version=payload.version,
            country=country,
            telemetry_policy_version=payload.telemetry_policy_version,
        )
    )
    db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.delete(
    "/v1/installation",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_json)],
)
def delete_installation(
    payload: DeletePayload,
    token: str = Depends(bearer_token),
    db: Session = Depends(get_db),
) -> Response:
    installation = _load_installation(
        db,
        product=payload.product,
        installation_id=payload.installation_id,
    )

    if installation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="installation not found",
        )

    if not token_matches(token, installation.installation_token_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="installation token mismatch",
        )

    db.delete(installation)
    db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)



def _validate_stats_product(product: str | None) -> str | None:
    if product is not None and product not in ALLOWED_PRODUCTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="unsupported product",
        )
    return product


@app.get("/v1/stats/summary")
def stats_summary(db: Session = Depends(get_db)) -> dict[str, int]:
    return summary(db)


@app.get("/v1/stats/products")
def stats_products(db: Session = Depends(get_db)) -> list[dict[str, object]]:
    return products(db)


@app.get("/v1/stats/versions")
def stats_versions(
    product: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    return versions(db, product=_validate_stats_product(product))


@app.get("/v1/stats/countries")
def stats_countries(
    product: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    return countries(db, product=_validate_stats_product(product))


@app.get("/v1/stats/history")
def stats_history(
    days: int = Query(default=30, ge=1, le=3650),
    product: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    return history(
        db,
        days=days,
        product=_validate_stats_product(product),
    )
