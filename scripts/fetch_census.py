"""
fetch_census.py
----------------
Fetches district-level Census of India 2011 data products for Tamil Nadu
(32 districts, 2011 boundaries) and writes them into data/census/.

Follows the same conventions as the other fetch_*.py scripts in this
pipeline:
  - Standard library only (urllib, re, json, csv) — no pip installs, so the
    GitHub Actions runner needs no "pip install" step.
  - Plain constants at the top — no argparse (argparse exit codes collide
    with the pipeline's own error-code convention: 2 = "file not
    found"/"bad args", not something we want to trigger by accident).
  - Per-item try/except — one district or one part failing does not abort
    the run. Anything unresolved is logged to data/census/unresolved.csv
    instead of silently skipped or faked.
  - Exit code 1 only if EVERYTHING failed (e.g. genuine outage). Partial
    success exits 0, same as the WHO GHO script's convention.

Census 2011 is static — it will never update — so this is meant to be run
via workflow_dispatch (manual trigger) rather than on the monthly cron used
for WHO/World Bank. Run it once, commit the result, done. Re-running is
still safe: already-downloaded files are skipped.

Data sources hit by this script:
  1. censusindia.gov.in/nada  — District Census Handbook (DCHB) Part A/B
     PDFs, located via the NADA free-text search + catalog page scrape
     (the NADA install here doesn't expose a documented public JSON API,
     so this parses the HTML with regex — brittle by nature of the source,
     which is why every step is logged, not assumed).
  2. data.gov.in — state-wide Primary Census Abstract (PCA) catalog page.

IMPORTANT: this script was written and syntax-checked in a network-locked
sandbox that could not reach censusindia.gov.in or data.gov.in, so the HTML
scraping logic below could not be tested against a live response. The
first run in Actions (which does have outbound internet) should be
inspected — if the site's markup differs from what's assumed here, items
will land in unresolved.csv rather than fail loudly, and the regexes below
are the first thing to adjust.
"""

import csv
import os
import re
import sys
import time
import urllib.request
import urllib.error
from urllib.parse import quote

OUT_DIR = "data/census"
DCHB_DIR = os.path.join(OUT_DIR, "dchb")
PCA_DIR = os.path.join(OUT_DIR, "pca")
UNRESOLVED_PATH = os.path.join(OUT_DIR, "unresolved.csv")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

STATE_CODE = "33"  # Tamil Nadu

# Tamil Nadu districts, 2011 Census boundaries (32 districts).
DISTRICTS = {
    "01": "THIRUVALLUR", "02": "CHENNAI", "03": "KANCHEEPURAM", "04": "VELLORE",
    "05": "THIRUVANNAMALAI", "06": "VILUPPURAM", "07": "SALEM", "08": "NAMAKKAL",
    "09": "DHARMAPURI", "10": "KRISHNAGIRI", "11": "COIMBATORE", "12": "TIRUPPUR",
    "13": "ERODE", "14": "THE NILGIRIS", "15": "DINDIGUL", "16": "KARUR",
    "17": "TIRUCHIRAPPALLI", "18": "PERAMBALUR", "19": "ARIYALUR", "20": "CUDDALORE",
    "21": "NAGAPATTINAM", "22": "TIRUVARUR", "23": "THANJAVUR", "24": "PUDUKKOTTAI",
    "25": "SIVAGANGA", "26": "MADURAI", "27": "THENI", "28": "VIRUDHUNAGAR",
    "29": "RAMANATHAPURAM", "30": "THOOTHUKUDI", "31": "TIRUNELVELI", "32": "KANYAKUMARI",
}

NADA_SEARCH_URL = "https://censusindia.gov.in/nada/index.php/catalog/free_search?search={q}"
NADA_CATALOG_URL = "https://censusindia.gov.in/nada/index.php/catalog/{id}"
PCA_CATALOG_PAGE = "https://www.data.gov.in/catalog/villagetown-wise-primary-census-abstract-2011-tamil-nadu"

REQUEST_DELAY_SEC = 1.0  # be polite to government servers


def http_get(url, binary=False):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read()
    return data if binary else data.decode("utf-8", errors="replace")


def find_catalog_ids(query):
    """Search the NADA free-text search page and pull out catalog IDs."""
    url = NADA_SEARCH_URL.format(q=quote(query))
    html = http_get(url)
    return re.findall(r'/nada/index\.php/catalog/(\d+)"', html)


def find_pdf_links(catalog_id):
    """Scrape a NADA catalog entry page for its downloadable PDF links."""
    url = NADA_CATALOG_URL.format(id=catalog_id)
    html = http_get(url)
    links = re.findall(
        r'href="(/nada/index\.php/catalog/\d+/download/\d+/[^"]+?\.pdf)"', html
    )
    return sorted(set(links))


def download_file(path_or_url, dest_path):
    url = path_or_url
    if url.startswith("/"):
        url = "https://censusindia.gov.in" + url
    data = http_get(url, binary=True)
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    with open(dest_path, "wb") as f:
        f.write(data)
    return len(data)


def fetch_dchb(unresolved):
    """District Census Handbook Part A/B for every district."""
    os.makedirs(DCHB_DIR, exist_ok=True)
    ok, failed = 0, 0

    for code, name in DISTRICTS.items():
        dest = os.path.join(DCHB_DIR, f"{name.title().replace(' ', '_')}")
        if os.path.exists(dest + "_PartA.pdf") and os.path.exists(dest + "_PartB.pdf"):
            print(f"[dchb] {name}: already have both parts, skipping")
            ok += 1
            continue

        try:
            catalog_ids = find_catalog_ids(f"District Census Handbook {name} Tamil Nadu")
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            print(f"[dchb] {name}: search failed ({e})")
            unresolved.append((f"{name}_DCHB", NADA_SEARCH_URL.format(q=name), f"search failed: {e}"))
            failed += 1
            continue

        if not catalog_ids:
            print(f"[dchb] {name}: no catalog match found")
            unresolved.append((f"{name}_DCHB", NADA_SEARCH_URL.format(q=name), "no catalog match"))
            failed += 1
            continue

        found_any = False
        for cid in catalog_ids[:3]:  # first few candidates only
            try:
                pdf_links = find_pdf_links(cid)
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
                continue
            for link in pdf_links:
                part = "A" if "PART_A" in link.upper() else ("B" if "PART_B" in link.upper() else "X")
                out_path = f"{dest}_Part{part}.pdf"
                if os.path.exists(out_path):
                    continue
                try:
                    size = download_file(link, out_path)
                    print(f"[dchb] {name} Part {part}: saved {size/1024:.0f} KB")
                    found_any = True
                    time.sleep(REQUEST_DELAY_SEC)
                except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
                    unresolved.append((f"{name}_Part{part}", link, f"download failed: {e}"))
            if found_any:
                break

        if found_any:
            ok += 1
        else:
            unresolved.append((
                f"{name}_DCHB", NADA_CATALOG_URL.format(id=catalog_ids[0]),
                "catalog match found but no PDF links extracted — check page markup",
            ))
            failed += 1

        time.sleep(REQUEST_DELAY_SEC)

    return ok, failed


def fetch_state_pca(unresolved):
    """State-wide combined Primary Census Abstract (data.gov.in)."""
    os.makedirs(PCA_DIR, exist_ok=True)
    try:
        html = http_get(PCA_CATALOG_PAGE)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        unresolved.append(("PCA_TamilNadu_State", PCA_CATALOG_PAGE, f"page fetch failed: {e}"))
        return 0, 1

    # data.gov.in resource download links typically look like
    # /files/<uuid>/<filename>.<ext> or /catalog/.../resource/download/<id>
    links = re.findall(r'href="([^"]+\.(?:csv|xlsx|xls|pdf))"', html, flags=re.IGNORECASE)
    if not links:
        unresolved.append((
            "PCA_TamilNadu_State", PCA_CATALOG_PAGE,
            "no downloadable file links found on catalog page — likely needs a click-through, check manually",
        ))
        return 0, 1

    ok = 0
    for link in links[:5]:
        url = link if link.startswith("http") else "https://www.data.gov.in" + link
        fname = os.path.join(PCA_DIR, os.path.basename(link.split("?")[0]))
        try:
            size = download_file(url, fname)
            print(f"[pca] saved {os.path.basename(fname)} ({size/1024:.0f} KB)")
            ok += 1
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            unresolved.append(("PCA_TamilNadu_State", url, f"download failed: {e}"))
        time.sleep(REQUEST_DELAY_SEC)

    return ok, (0 if ok else 1)


def write_unresolved(unresolved):
    os.makedirs(OUT_DIR, exist_ok=True)
    if not unresolved:
        if os.path.exists(UNRESOLVED_PATH):
            os.remove(UNRESOLVED_PATH)
        return
    with open(UNRESOLVED_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["item", "url", "note"])
        w.writerows(unresolved)
    print(f"Wrote {len(unresolved)} unresolved items to {UNRESOLVED_PATH}")


def main():
    unresolved = []

    print("== Step 1/2: District Census Handbooks (32 districts) ==")
    dchb_ok, dchb_failed = fetch_dchb(unresolved)

    print("== Step 2/2: State-wide Primary Census Abstract ==")
    pca_ok, pca_failed = fetch_state_pca(unresolved)

    write_unresolved(unresolved)

    total_ok = dchb_ok + pca_ok
    total_failed = dchb_failed + pca_failed
    print(f"Done. {total_ok} succeeded, {total_failed} need manual follow-up.")

    if total_ok == 0:
        # Nothing at all worked — treat as a genuine failure (outage,
        # site markup changed, network blocked), same convention as the
        # WHO script's "exit 1 = all indicators failed".
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
