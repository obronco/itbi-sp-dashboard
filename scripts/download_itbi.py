#!/usr/bin/env python3
"""
Download the last 5 years of ITBI Excel files from Prefeitura de São Paulo.

The links are read from the official page on every run:
https://prefeitura.sp.gov.br/web/fazenda/w/acesso_a_informacao/31501

The Prefeitura renames the current year's file every month (e.g.
"GUIAS DE ITBI PAGAS (30092026).xlsx"), so hard-coded links silently freeze
the data. YEAR_URLS below is only a fallback for years the page parse misses.
"""

from __future__ import annotations

import re
import sys
import time
import urllib.parse
from pathlib import Path

from curl_cffi import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

PAGE_URL = "https://prefeitura.sp.gov.br/web/fazenda/w/acesso_a_informacao/31501"
N_YEARS = 5

# Fallback only (as of 2026-09) — used for a year the page parse doesn't find.
YEAR_URLS: dict[int, str] = {
    2022: "https://www.prefeitura.sp.gov.br/cidade/secretarias/upload/fazenda/arquivos/XLSX/GUIAS_DE_ITBI_PAGAS_12-2022.xlsx",
    2023: "https://www.prefeitura.sp.gov.br/cidade/secretarias/upload/fazenda/arquivos/XLSX/GUIAS-DE-ITBI-PAGAS-2023.xlsx",
    2024: "https://prefeitura.sp.gov.br/cidade/secretarias/upload/fazenda/arquivos/itbi/GUIAS-DE-ITBI-PAGAS-2024.xlsx",
    2025: "https://prefeitura.sp.gov.br/cidade/secretarias/upload/fazenda/arquivos/itbi/GUIAS%20DE%20ITBI%20PAGAS%20%2828012026%29%20XLS.xlsx",
    2026: "https://prefeitura.sp.gov.br/cidade/secretarias/upload/fazenda/arquivos/itbi/GUIAS%20DE%20ITBI%20PAGAS%20%2830092026%29.xlsx",
}

# Browser to impersonate at the TLS/HTTP2 fingerprint level (curl_cffi).
# The Prefeitura's edge appears to 403 requests whose TLS ClientHello doesn't
# match a real browser (plain urllib/requests get blocked; GitHub-hosted
# runners hit this reliably even though the URLs are otherwise reachable).
IMPERSONATE = "chrome124"

MIN_BYTES = 1_000_000  # reject tiny / error pages
MAX_RETRIES = 3
RETRY_SLEEP = 5


def download_one(year: int, url: str, dest: Path) -> None:
    print(f"  {year} ← {url}")
    last_err: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(
                url,
                impersonate=IMPERSONATE,
                timeout=180,
                allow_redirects=True,
            )
            resp.raise_for_status()
            data = resp.content
            if len(data) < MIN_BYTES:
                raise RuntimeError(
                    f"Download too small ({len(data)} bytes) — likely an error page"
                )
            dest.write_bytes(data)
            print(f"    → {dest.name} ({len(data) / 1e6:.1f} MB)")
            return
        except Exception as e:
            last_err = e
            print(f"    attempt {attempt}/{MAX_RETRIES} failed: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_SLEEP)

    raise SystemExit(f"Failed to download {year} after {MAX_RETRIES} tries: {last_err}")


def discover_urls() -> dict[int, str]:
    """
    Year → Excel URL from the official page, which lists each year as
    `2026 (<a href="...">Excel/xlsx</a>) (<a href="...">ODS</a>)`.
    Returns {} if the page can't be fetched or parsed.
    """
    try:
        resp = requests.get(PAGE_URL, impersonate=IMPERSONATE, timeout=60)
        resp.raise_for_status()
    except Exception as e:
        print(f"  could not fetch the download page ({e}); using fallback URLs")
        return {}
    found: dict[int, str] = {}
    pattern = r'\b(20\d\d)\s*\(\s*<a\s[^>]*href="([^"]+)"[^>]*>\s*(?:<[^>]+>\s*)*Excel'
    for year, href in re.findall(pattern, resp.text, re.IGNORECASE):
        # some hrefs carry raw spaces; keep existing %-escapes as they are
        found.setdefault(int(year), urllib.parse.quote(href, safe=":/%()?=&"))
    return found


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Downloading into {DATA_DIR}")

    found = discover_urls()
    print(f"  page lists {len(found)} years" + (f" ({min(found)}–{max(found)})" if found else ""))
    years = sorted(set(found) | set(YEAR_URLS))[-N_YEARS:]

    for year in years:
        url = found.get(year) or YEAR_URLS[year]
        if year not in found:
            print(f"  {year}: not found on the page — fallback URL")
        dest = DATA_DIR / f"itbi_{year}.xlsx"
        # The source URL is kept next to the file: a new link (the monthly
        # update of the current year) means a new file, even if one is present.
        src = dest.with_suffix(".url")
        same_source = src.exists() and src.read_text().strip() == url
        if dest.exists() and dest.stat().st_size >= MIN_BYTES and same_source:
            print(f"  {year} already present ({dest.stat().st_size / 1e6:.1f} MB) — skip")
            continue
        download_one(year, url, dest)
        src.write_text(url)

    print("Done.")


if __name__ == "__main__":
    main()
