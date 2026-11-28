from __future__ import annotations

import logging

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from .config import get_settings
from .country import country_from_cloudflare
from .db import get_db
from .models import Heartbeat, Installation
from .journal import APP_VERSION, lifespan_for, observe, rejected, internal_get, clear_internal
from .protocol import DeletePayload, HeartbeatPayload
from .security import bearer_token, token_hash, token_matches


settings = get_settings()
logging.basicConfig(level=settings.log_level.upper())

app = FastAPI(
    title="DigitalHouses Stats",
    version=APP_VERSION,
    lifespan=lifespan_for(settings),
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
    return db.get(Installation, (product, installation_id), with_for_update=True)


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

    new = installation is None
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
            new = False
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

    journal = getattr(request.app.state, "journal", None)
    previous = None
    if journal is not None and not new:
        # An optional diagnostic read must not poison the heartbeat transaction.
        try:
            with db.begin_nested():
                previous = db.execute(select(Heartbeat).where(
                    Heartbeat.product == payload.product,
                    Heartbeat.installation_id == payload.installation_id,
                ).order_by(Heartbeat.received_at.desc(), Heartbeat.id.desc()).limit(1)).scalar_one_or_none()
        except SQLAlchemyError:
            journal.report_failure()
            journal = None

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
    observe(journal, product=payload.product, version=payload.version, country=country,
            previous=previous, new=new)

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



@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    if request.url.path == "/v1/heartbeat":
        rejected(getattr(request.app.state, "journal", None), exc.errors(),
                 country_from_cloudflare(request.headers.get("cf-ipcountry")))
    return await request_validation_exception_handler(request, exc)


@app.get("/internal/journal/log", include_in_schema=False)
def internal_log(request: Request):
    return internal_get(request, settings, "/api/log")


@app.get("/internal/journal/log/export", include_in_schema=False)
def internal_export(request: Request):
    return internal_get(request, settings, "/api/log/export")


@app.post("/internal/journal/log/clear", include_in_schema=False)
async def internal_clear(request: Request):
    return await clear_internal(request)
