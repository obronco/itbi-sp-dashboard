#!/usr/bin/env python3
"""
Refresh ref/ipca_index.json — the IPCA number index (IBGE SIDRA table 1737,
variable 2266; Dec/1993 = 100) the pipeline uses for inflation-adjusted values.

The index is committed so builds never depend on IBGE being reachable: this
script only adds months IBGE has published since. If SIDRA is down, the file
is left as is (exit 0) and the build uses the last known month.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX_FILE = ROOT / "ref" / "ipca_index.json"
SIDRA_URL = "https://apisidra.ibge.gov.br/values/t/1737/n1/all/v/2266/p/all?formato=json"


def fetch() -> dict[str, float]:
    with urllib.request.urlopen(SIDRA_URL, timeout=60) as r:
        rows = json.load(r)[1:]  # first row is the header
    return {f"{r['D3C'][:4]}-{r['D3C'][4:]}": float(r["V"])
            for r in rows if r["V"] not in ("...", "-", "")}


def main() -> None:
    current = json.loads(INDEX_FILE.read_text()) if INDEX_FILE.exists() else {"index": {}}
    try:
        fresh = fetch()
    except Exception as e:
        last = max(current["index"], default="none")
        print(f"WARNING: SIDRA unavailable ({e}); keeping {INDEX_FILE.name} (last month {last})")
        return
    merged = {**current["index"], **fresh}
    if merged == current["index"]:
        print(f"IPCA index up to date (last month {max(merged)})")
        return
    added = sorted(set(merged) - set(current["index"]))
    INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    INDEX_FILE.write_text(json.dumps({
        "source": "IBGE — IPCA, número-índice (dez/1993 = 100), SIDRA tabela 1737, variável 2266",
        "url": SIDRA_URL,
        "index": dict(sorted(merged.items())),
    }, indent=1, ensure_ascii=False) + "\n")
    print(f"IPCA index updated: {len(added)} new month(s), last {max(merged)}")


if __name__ == "__main__":
    sys.exit(main())
