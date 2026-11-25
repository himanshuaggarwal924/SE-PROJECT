"""
storage/migrate.py - One-off migration of data kept in files before Phase 7.

    python -m storage.migrate            # import interviews/*.json into the database
    python -m storage.migrate --dry-run

Careful by design: nothing is deleted. Each imported file is renamed to
<name>.json.migrated (so it is not imported twice and can be restored), and
transcripts already in the database are skipped. User accounts stay in
auth/users.yaml (no migration needed).
"""

import argparse
import json

import audit_log
import config
from storage import projects


def migrate_transcripts(dry_run: bool = False) -> dict:
    found = imported = skipped = 0
    if config.INTERVIEWS_DIR.exists():
        for path in sorted(config.INTERVIEWS_DIR.glob("*.json")):
            found += 1
            try:
                session = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                skipped += 1
                continue
            if projects.load_transcript(session["id"]) is not None:
                skipped += 1
                continue
            if not dry_run:
                projects.save_transcript(session)
                path.rename(path.with_name(path.name + ".migrated"))
            imported += 1
    if not dry_run and imported:
        audit_log.log_event("migration", "transcripts_migrated", imported=imported, skipped=skipped)
    return {"found": found, "imported": imported, "skipped": skipped, "dry_run": dry_run}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    print(json.dumps(migrate_transcripts(parser.parse_args().dry_run), indent=2))
