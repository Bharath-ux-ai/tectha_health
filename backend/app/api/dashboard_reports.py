from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import local_today
from app.core.deps import CurrentUser, client_ip, require_hospital
from app.db import get_db
from app.models import Hospital, MonthlyReport
from app.services.audit import audit
from app.services.dashboard import dashboard
from app.services.reports import monthly_report, report_csv

router = APIRouter(prefix="/api", tags=["dashboard", "reports"])


@router.get("/dashboard")
def get_dashboard(on: date | None = None, current: CurrentUser = Depends(require_hospital("appointments:read")),
                  db: Session = Depends(get_db)):
    h = db.get(Hospital, current.hospital_id)
    return dashboard(db, h, on)


def _month(h: Hospital, month: str | None) -> date:
    if not month:
        return local_today(h).replace(day=1)
    try:
        y, m = (int(x) for x in month.split("-"))
        return date(y, m, 1)
    except (ValueError, TypeError):
        raise HTTPException(400, "Month must look like 2026-11.")


@router.get("/reports/monthly")
def get_report(month: str | None = None, current: CurrentUser = Depends(require_hospital("reports:read")),
               db: Session = Depends(get_db)):
    h = db.get(Hospital, current.hospital_id)
    m = _month(h, month)
    report = monthly_report(db, h, m)
    snap = db.scalar(select(MonthlyReport).where(MonthlyReport.hospital_id == h.id, MonthlyReport.month == m))
    report["saved_at"] = snap.generated_at.isoformat() if snap else None
    return report


@router.post("/reports/monthly/{month}/save")
def save_report(month: str, request: Request, current: CurrentUser = Depends(require_hospital("reports:read")),
                db: Session = Depends(get_db)):
    """Freeze this month's figures (e.g. the copy shared with the hospital owner)."""
    h = db.get(Hospital, current.hospital_id)
    m = _month(h, month)
    data = monthly_report(db, h, m)
    snap = db.scalar(select(MonthlyReport).where(MonthlyReport.hospital_id == h.id, MonthlyReport.month == m))
    if snap is None:
        snap = MonthlyReport(hospital_id=h.id, month=m, data=data, generated_by_user_id=current.id)
        db.add(snap)
    else:
        from app.core.clock import utcnow
        snap.data, snap.generated_by_user_id, snap.generated_at = data, current.id, utcnow()
    audit(db, "report.saved", hospital_id=h.id, user_id=current.id, entity_type="monthly_report",
          details={"month": m.isoformat()}, ip=client_ip(request))
    db.commit()
    return {"ok": True, "saved_at": snap.generated_at.isoformat()}


@router.get("/reports/monthly/{month}/export.csv")
def export_csv(month: str, request: Request, current: CurrentUser = Depends(require_hospital("reports:read")),
               db: Session = Depends(get_db)):
    h = db.get(Hospital, current.hospital_id)
    m = _month(h, month)
    body = report_csv(monthly_report(db, h, m))
    audit(db, "report.exported", hospital_id=h.id, user_id=current.id, entity_type="monthly_report",
          details={"month": m.isoformat()}, ip=client_ip(request))
    db.commit()
    filename = f"tectha-report-{h.slug}-{m:%Y-%m}.csv"
    return Response(content="﻿" + body, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})
