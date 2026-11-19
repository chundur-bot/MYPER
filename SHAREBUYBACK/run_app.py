"""Start the local web page:  python run_app.py   (options: --port 8770 --no-browser --rebuild; --read-only "<folder>" to view a published copy)"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # also works when run with -P

from sbb import server

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8770)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--read-only", nargs="?", const="", default=None, metavar="FOLDER_OR_FILE",
                    help="show a published copy of the database, never writing to it. Give the folder or file the first time; it is remembered")
    ap.add_argument("--rebuild", action="store_true", help="rebuild every figure from the filings held, even if nothing changed")
    a = ap.parse_args()
    server.serve(a.port, not a.no_browser, a.read_only, a.rebuild)
