"""Housekeeping for the database, run from a Command Prompt in the app's folder. Nothing here runs by itself.

  python -P maintain.py publish "<shared folder>"     publish a read-only copy of buyback.db for the team (the folder is remembered: next time just "publish")
  python -P maintain.py backups                       list the copies in the backups folder, with their sizes
  python -P maintain.py backups --keep 5              delete all but the newest 5 (shows them and asks first)
  python -P maintain.py compact                       give back unused space in buyback.db (copies it to backups first; close the app before)

publish never changes buyback.db. It writes buyback_published.db in the shared folder in one step, so a reader always opens a whole
file, and keeps the last few published copies in a "history" folder beside it (--keep N, 5 unless you say otherwise).
Team members open it with:  python -P run_app.py --read-only "<shared folder>"
"""
import argparse
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from sbb import db, server  # noqa: E402

PUBLISHED = "buyback_published.db"
COUNTED = ("documents", "transactions", "programmes", "snapshots", "cancellations", "review")


def _size(n):
    return f"{n / 1_048_576:,.1f} MB"


def publish(folder, source=None, keep=5):
    """A whole, checked copy of the database in the shared folder. Returns the published file. Raises ValueError with a plain reason."""
    source, folder = Path(source or db.DB_PATH), Path(folder)
    if not source.is_file():
        raise ValueError(f"No database at {source}.")
    if not folder.is_dir():
        raise ValueError(f"Folder not found from this PC: {folder}")
    if folder.resolve() == source.parent.resolve():
        raise ValueError("Choose a different folder from the one the app is in: the published copy is for others to read, and the app's folder is yours.")
    part, target = folder / "buyback_published.part", folder / PUBLISHED
    part.unlink(missing_ok=True)
    live = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)  # the live database is only read
    try:
        live.execute("vacuum into ?", (str(part),))  # one consistent copy, even if the app is running, with no unused space
        want = {t: live.execute(f"select count(*) from {t}").fetchone()[0] for t in COUNTED}
    finally:
        live.close()
    made = sqlite3.connect(part)
    try:
        ok = made.execute("pragma integrity_check").fetchone()[0]
        got = {t: made.execute(f"select count(*) from {t}").fetchone()[0] for t in COUNTED}
        if ok != "ok" or got != want:
            raise ValueError(f"The copy did not check out ({ok}; rows {got} against {want}), so nothing was published. The earlier published copy is unchanged.")
        made.execute("create table if not exists app_state (key text primary key, value text)")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for k, v in (("published_at", now), ("published_version", db.VERSION)):
            made.execute("insert into app_state(key, value) values(?, ?) on conflict(key) do update set value=excluded.value", (k, v))
        made.commit()
    except Exception:
        made.close()
        part.unlink(missing_ok=True)
        raise
    made.close()
    history = folder / "history"
    history.mkdir(exist_ok=True)
    shutil.copyfile(part, history / f"buyback_{datetime.now():%Y%m%d_%H%M%S}.db")
    os.replace(part, target)  # one step: a reader sees the old file or the new one, never half of one
    if keep and keep > 0:
        for old in sorted(history.glob("buyback_*.db"), key=lambda f: f.name, reverse=True)[keep:]:
            old.unlink()
    return target


def list_backups(folder=None):
    folder = Path(folder or ROOT / "backups")
    return sorted(folder.glob("*.db"), key=lambda f: f.stat().st_mtime, reverse=True) if folder.is_dir() else []


def prune_backups(keep, folder=None, confirm=input):
    """Delete all but the newest `keep` copies, after showing them and being told YES. Returns the files deleted."""
    files = list_backups(folder)
    extra = files[max(keep, 0):]
    if not extra:
        print(f"Nothing to delete: {len(files)} cop{'y' if len(files) == 1 else 'ies'} held.")
        return []
    print(f"These {len(extra)} older copies would be deleted ({_size(sum(f.stat().st_size for f in extra))}). The newest {min(keep, len(files))} stay:")
    for f in extra:
        print(f"  {datetime.fromtimestamp(f.stat().st_mtime):%Y-%m-%d %H:%M}  {_size(f.stat().st_size):>10}  {f.name}")
    if confirm("They cannot be brought back. Type YES to delete them: ").strip() != "YES":
        print("Nothing was deleted.")
        return []
    for f in extra:
        f.unlink()
    print(f"Deleted {len(extra)} copies.")
    return extra


def compact(path=None):
    """Give back the unused space in the database file. A copy is saved in backups first. Returns (bytes before, bytes after, the copy)."""
    path = Path(path or db.DB_PATH)
    if not path.is_file():
        raise ValueError(f"No database at {path}.")
    before = path.stat().st_size
    folder = path.parent / "backups"
    folder.mkdir(exist_ok=True)
    kept = folder / f"buyback_{datetime.now():%Y%m%d_%H%M%S}_before_compact.db"
    con = sqlite3.connect(path, timeout=5)
    try:
        copy = sqlite3.connect(kept)
        try:
            con.backup(copy)
        finally:
            copy.close()
        con.execute("vacuum")
    except sqlite3.OperationalError as e:
        raise ValueError(f"The database is in use ({e}). Close the app, then run this again.")
    finally:
        con.close()
    return before, path.stat().st_size, kept


def main():
    ap = argparse.ArgumentParser(description="Publish a read-only copy, list or trim backups, or compact the database.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("publish")
    p.add_argument("folder", nargs="?", default="")
    p.add_argument("--keep", type=int, default=5, help="published copies to keep in the history folder (0 keeps all)")
    b = sub.add_parser("backups")
    b.add_argument("--keep", type=int, default=None)
    sub.add_parser("compact")
    a = ap.parse_args()
    try:
        if a.cmd == "publish":
            folder = a.folder or server.local("publish_folder")
            if not folder:
                raise ValueError('Say where to publish, once:  python -P maintain.py publish "<shared folder>"')
            target = publish(folder, keep=a.keep)
            server.local("publish_folder", str(folder))
            print(f"Published {target} ({_size(target.stat().st_size)}).")
            print(f'The team opens it with:  python -P run_app.py --read-only "{folder}"')
        elif a.cmd == "backups":
            files = list_backups()
            if a.keep is None:
                for f in files:
                    print(f"  {datetime.fromtimestamp(f.stat().st_mtime):%Y-%m-%d %H:%M}  {_size(f.stat().st_size):>10}  {f.name}")
                print(f"{len(files)} cop{'y' if len(files) == 1 else 'ies'}, {_size(sum(f.stat().st_size for f in files))} in all. To keep only the newest 5:  python -P maintain.py backups --keep 5")
            else:
                prune_backups(a.keep)
        else:
            before, after, kept = compact()
            print(f"buyback.db: {_size(before)} before, {_size(after)} after. A copy of it as it was: {kept}")
    except ValueError as e:
        print(e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
