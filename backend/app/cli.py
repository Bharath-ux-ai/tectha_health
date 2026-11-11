"""Admin commands.

  python -m app.cli create-system-admin --email ops@tectha.in --name "Ops" [--password ...]
  python -m app.cli seed-demo [--admin-email ...] [--staff-email ...] [--password ...]
  python -m app.cli create-hospital --name "..." --admin-email ... --admin-name ... [--password ...]
"""
import argparse
import os
import secrets
import string
import sys

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Hospital
from app.services import demo
from app.services.hospitals import create_hospital, create_user


def _password(given: str | None) -> tuple[str, bool]:
    if given:
        return given, False
    alphabet = string.ascii_letters + string.digits
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(14))
        if any(c.isupper() for c in pw) and any(c.isdigit() for c in pw) and any(c.islower() for c in pw):
            return pw, True


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("create-system-admin")
    a.add_argument("--email", required=True)
    a.add_argument("--name", required=True)
    a.add_argument("--password", default=os.environ.get("ADMIN_PASSWORD"))
    d = sub.add_parser("seed-demo")
    d.add_argument("--admin-email", default="admin@demo.tectha.in")
    d.add_argument("--staff-email", default="staff@demo.tectha.in")
    d.add_argument("--password", default=os.environ.get("DEMO_PASSWORD"))
    h = sub.add_parser("create-hospital")
    h.add_argument("--name", required=True)
    h.add_argument("--slug")
    h.add_argument("--admin-email", required=True)
    h.add_argument("--admin-name", required=True)
    h.add_argument("--password", default=os.environ.get("ADMIN_PASSWORD"))
    args = p.parse_args(argv)

    with SessionLocal() as db:
        if args.cmd == "create-system-admin":
            pw, generated = _password(args.password)
            create_user(db, email=args.email, full_name=args.name, password=pw, role_code="system_admin",
                        hospital_id=None)
            db.commit()
            print(f"System admin created: {args.email}" + (f"\nGenerated password: {pw}" if generated else ""))
        elif args.cmd == "create-hospital":
            pw, generated = _password(args.password)
            hosp, _ = create_hospital(db, name=args.name, slug=args.slug, address=None, phone=None,
                                      admin_email=args.admin_email, admin_name=args.admin_name, admin_password=pw)
            db.commit()
            print(f"Hospital created: {hosp.name} (/book/{hosp.slug})\nAdmin: {args.admin_email}"
                  + (f"\nGenerated password: {pw}" if generated else ""))
        elif args.cmd == "seed-demo":
            existing = db.scalar(select(Hospital).where(Hospital.slug == demo.DEMO_SLUG))
            if existing:
                demo.reset(db, existing)
                print("Demo hospital already existed; demo data was reset.")
                return 0
            pw, generated = _password(args.password)
            hosp, _ = create_hospital(db, name="TEC THA Demo Clinic", slug=demo.DEMO_SLUG,
                                      address="Avinashi Road, Coimbatore (demo)", phone="+91 422 400 0000",
                                      is_demo=True, admin_email=args.admin_email, admin_name="Demo Admin",
                                      admin_password=pw)
            create_user(db, email=args.staff_email, full_name="Reception Desk", password=pw, role_code="staff",
                        hospital_id=hosp.id)
            db.commit()
            demo.reset(db, hosp)
            print(f"Demo hospital ready at /book/{hosp.slug}\nAdmin: {args.admin_email}\nStaff: {args.staff_email}"
                  + (f"\nGenerated password (both): {pw}" if generated else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
