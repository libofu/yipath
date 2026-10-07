"""Back up the production database.

Usage:  python scripts/backup_db.py [--db PATH] [--out DIR] [--keep N]
Defaults: --db $YIPATH_DB, --out <db folder>/backups, --keep 14.
Run it from cron (e.g. daily), and copy the backups folder somewhere off the server.
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.backup import backup_database  # noqa: E402
from app.store import DEFAULT_DB  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", default=os.environ.get("YIPATH_DB") or str(DEFAULT_DB))
    p.add_argument("--out", default=None)
    p.add_argument("--keep", type=int, default=14)
    args = p.parse_args()
    out = args.out or str(Path(args.db).parent / "backups")
    print(backup_database(args.db, out, keep=args.keep))


if __name__ == "__main__":
    main()
