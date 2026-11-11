import os
import sys

if sys.platform == "win32":
    pg_bin = r"C:\Program Files\PostgreSQL\17\bin"
    if os.path.isdir(pg_bin):
        try:
            os.add_dll_directory(pg_bin)
        except Exception:
            pass
        if pg_bin not in os.environ.get("PATH", ""):
            os.environ["PATH"] = pg_bin + os.pathsep + os.environ.get("PATH", "")
    os.environ.setdefault("PSYCOPG_IMPL", "python")

