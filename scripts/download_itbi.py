#!/usr/bin/env python3
"""
Download the last 5 years of ITBI Excel files from Prefeitura de São Paulo.

URLs are the official links from:
https://prefeitura.sp.gov.br/web/fazenda/w/acesso_a_informacao/31501

They change occasionally (especially the current year). Update YEAR_URLS when needed.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from curl_cffi import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Official Excel download URLs (as of 2026-09). Update when Prefeitura rotates links.
YEAR_URLS: dict[int, str] = {
    2022: "https://www.prefeitura.sp.gov.br/cidade/secretarias/upload/fazenda/arquivos/XLSX/GUIAS_DE_ITBI_PAGAS_12-2022.xlsx",
    2023: "https://www.prefeitura.sp.gov.br/cidade/secretarias/upload/fazenda/arquivos/XLSX/GUIAS-DE-ITBI-PAGAS-2023.xlsx",
    2024: "https://prefeitura.sp.gov.br/cidade/secretarias/upload/fazenda/arquivos/itbi/GUIAS-DE-ITBI-PAGAS-2024.xlsx",
    2025: "https://prefeitura.sp.gov.br/cidade/secretarias/upload/fazenda/arquivos/itbi/GUIAS%20DE%20ITBI%20PAGAS%20%2828012026%29%20XLS.xlsx",
    2026: "https://prefeitura.sp.gov.br/documents/d/fazenda/guias-de-itbi-pagas-27082026-xls-xlsx",
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


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Downloading into {DATA_DIR}")

    for year, url in sorted(YEAR_URLS.items()):
        dest = DATA_DIR / f"itbi_{year}.xlsx"
        if dest.exists() and dest.stat().st_size >= MIN_BYTES:
            print(f"  {year} already present ({dest.stat().st_size / 1e6:.1f} MB) — skip")
            continue
        download_one(year, url, dest)

    print("Done.")


if __name__ == "__main__":
    main()
