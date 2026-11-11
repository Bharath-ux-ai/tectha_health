import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.services.whatsapp.webhook import process_payload, verify_signature

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])
log = logging.getLogger("tectha.webhook")


@router.get("/whatsapp", response_class=PlainTextResponse)
def subscribe(mode: str = Query(alias="hub.mode", default=""), token: str = Query(alias="hub.verify_token", default=""),
              challenge: str = Query(alias="hub.challenge", default="")):
    """Meta's subscription handshake."""
    if mode == "subscribe" and settings.WHATSAPP_VERIFY_TOKEN and token == settings.WHATSAPP_VERIFY_TOKEN:
        return challenge
    raise HTTPException(403, "Verification failed")


@router.post("/whatsapp")
async def receive(request: Request, db: Session = Depends(get_db)):
    raw = await request.body()
    if not verify_signature(raw, request.headers.get("x-hub-signature-256")):
        log.warning("Rejected webhook with invalid signature")
        raise HTTPException(401, "Invalid signature")
    try:
        payload = json.loads(raw)
    except ValueError:
        raise HTTPException(400, "Invalid JSON")
    try:
        stats = process_payload(db, payload)
        db.commit()
    except Exception:
        db.rollback()
        log.exception("Webhook processing failed")
        raise  # 500 → Meta retries; dedupe keys make the retry safe
    return {"ok": True, **stats}
