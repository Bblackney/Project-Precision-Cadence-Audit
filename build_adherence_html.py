#!/usr/bin/env python3
"""
build_adherence_html.py — render adherence.html from adherence_data.json + adherence_template.html.

Inlines the latest run's data into the template (self-contained page that works locally and on
GitHub Pages, same pattern as the weekly index.html). Run after salesloft_adherence_scorer.py;
run_adherence.sh calls it automatically.

    python3 build_adherence_html.py
"""
import os, json, sys

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "adherence_data.json")
TPL  = os.path.join(BASE, "adherence_template.html")
OUT  = os.path.join(BASE, "adherence.html")
PLACEHOLDER = "__ADHERENCE_DATA__"

def main():
    if not os.path.exists(DATA):
        sys.exit(f"[ERR] {DATA} not found — run salesloft_adherence_scorer.py first.")
    if not os.path.exists(TPL):
        sys.exit(f"[ERR] {TPL} not found.")
    with open(DATA, encoding="utf-8") as f:
        data = json.load(f)
    with open(TPL, encoding="utf-8") as f:
        tpl = f.read()
    # compact JSON; make it safe to embed inside <script> (no premature </script>)
    blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    if PLACEHOLDER not in tpl:
        sys.exit(f"[ERR] placeholder {PLACEHOLDER} not in template.")
    html = tpl.replace(PLACEHOLDER, blob)
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(html)
    os.replace(tmp, OUT)
    print(f"  wrote adherence.html ({len(html)/1e6:.2f} MB) from {len(data.get('rows', []))} rows", flush=True)

if __name__ == "__main__":
    main()
