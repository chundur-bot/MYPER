"""Assembles the single-file viewer: the page template with sql.js and its engine built in, so it needs no internet."""
import base64
from pathlib import Path

S = Path(__file__).resolve().parent  # viewer/src
OUT = S.parent  # viewer
dist = S / "sqljs"
page = (S / "viewer_template.html").read_text(encoding="utf-8")
js = (dist / "sql-wasm.js").read_text(encoding="utf-8")
assert "</script" not in js.lower()
wasm = base64.b64encode((dist / "sql-wasm.wasm").read_bytes()).decode("ascii")
page = page.replace("%%SQLJS%%", js, 1).replace("%%WASM_B64%%", wasm, 1)
assert "%%" not in page
OUT.mkdir(exist_ok=True)
(OUT / "buyback_viewer.html").write_text(page, encoding="utf-8")
(OUT / "THIRD_PARTY_LICENCE_sql.js.txt").write_text("buyback_viewer.html includes sql.js 1.10.3 (https://github.com/sql-js/sql.js).\n\n" + (dist / "LICENSE").read_text(encoding="utf-8"), encoding="utf-8")
print("written", round((OUT / "buyback_viewer.html").stat().st_size / 1e6, 2), "MB")
