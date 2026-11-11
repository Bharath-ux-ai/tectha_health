import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api import (
    appointments, auth, dashboard_reports, demo, followups, hospital, patients, public, system, webhooks, whatsapp,
)
from app.config import settings
from app.core.errors import ServiceError
from app.db import SessionLocal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(
    title="TEC THA Follow-Up Engine API",
    version="1.0.0",
    docs_url=None if settings.is_production else "/api/docs",
    redoc_url=None,
    openapi_url=None if settings.is_production else "/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "X-Requested-With", "Authorization"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if request.url.path.startswith("/api/") and request.url.path != "/api/health":
        response.headers.setdefault("Cache-Control", "no-store")
    if settings.COOKIE_SECURE:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


@app.exception_handler(ServiceError)
async def service_error_handler(request: Request, exc: ServiceError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message, "code": exc.code})


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    errors = []
    for e in exc.errors():
        field = ".".join(str(p) for p in e.get("loc", [])[1:]) or "request"
        errors.append({"field": field, "message": e.get("msg", "Invalid value")})
    first = errors[0] if errors else {"field": "request", "message": "Invalid request"}
    return JSONResponse(status_code=422, content={
        "detail": f"{first['field'].replace('_', ' ').capitalize()}: {first['message']}", "errors": errors})


for r in (auth, public, appointments, patients, followups, dashboard_reports, hospital, whatsapp, webhooks, system, demo):
    app.include_router(r.router)


@app.get("/api/health")
def health():
    with SessionLocal() as db:
        db.execute(text("select 1"))
    return {"ok": True, "service": "tectha-followup-api", "version": app.version}
