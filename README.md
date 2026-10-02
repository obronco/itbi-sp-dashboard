# ITBI São Paulo — Dashboard

Single-page dashboard of real-estate transactions in São Paulo with ITBI payment (official municipal data).

- **Source**: [Prefeitura de São Paulo — Dados das Transações Imobiliárias (ITBI)](https://prefeitura.sp.gov.br/web/fazenda/w/acesso_a_informacao/31501)
- **Lookback**: 2006 to today. The last 5 years load by default; older years load on demand (pick them in *Ano pagamento* or press *Carregar histórico*).
- **Stack**: static HTML + DuckDB-WASM + Chart.js + MapLibre GL (basemap tiles from [OpenFreeMap](https://openfreemap.org/), no API key)
- **Pipeline**: GitHub Actions downloads the yearly Excels, cleans them into one compact Parquet per year (`parquet/itbi_YYYY.parquet` + `manifest.json`), and deploys to GitHub Pages. The page draws the most recent year first and loads the others in the background.

## Live site

After the first successful workflow run:

`https://<your-user>.github.io/<repo-name>/`

## Local development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Download official Excel files into data/
python scripts/download_itbi.py

# Clean + build parquet/itbi_YYYY.parquet + parquet/manifest.json (+ ipca.json)
python scripts/preprocess_itbi.py

# (Optional) the history, into the same folder (~350 MB of Excel, ~10 min)
python scripts/download_itbi.py --years 2006-2021
python scripts/preprocess_itbi.py --years 2006-2021
python scripts/preprocess_itbi.py --manifest parquet   # list every year in the manifest

# (Optional) Rebuild the block → distrito/subprefeitura lookup from GeoSampa.
# geo/quadras_geo.parquet is committed; refresh it only occasionally.
python scripts/build_quadras_geo.py

# Serve (must be same origin for the parquet fetch)
python -m http.server 8080
# open http://localhost:8080
```

## GitHub Pages setup (one-time)

1. Push this repository to GitHub.
2. **Settings → Pages → Build and deployment → Source**: *GitHub Actions*.
3. Run the workflow once: **Actions → Update ITBI dashboard → Run workflow**.
4. After ~10–20 minutes the site is live.

The workflow also runs automatically on the 5th of every month (shortly after the municipal monthly release).

## Download URLs

The Prefeitura renames the current year's Excel every month, so `scripts/download_itbi.py` reads the links from the official page on every run (https://prefeitura.sp.gov.br/web/fazenda/w/acesso_a_informacao/31501) and takes the 5 most recent years. `YEAR_URLS` in that script is only a fallback for a year the page parse misses. Each download's source link is saved next to it (`data/itbi_YYYY.url`); a changed link triggers a fresh download.

## Data notes

- Each row is a paid DTI in the **payment month** (sheet name), not necessarily the transaction month.
- Self-declared values; rural properties and PPI parcelamentos are excluded by the source.
- `preco_m2` is computed only when area (built area, or land area for `terreno`) is within the segment's expected band and the result is between R$ 100 and R$ 150 000.
- Means are sensitive to large corporate deals; prefer medians.
- Values are **nominal** by default. *Valores corrigidos pelo IPCA* expresses every value in R$ of the latest IPCA month, using IBGE's IPCA number index (SIDRA table 1737) by the month of the deal — needed for anything comparing years far apart.
- History (2006 … this year − 5) and the recent years are processed separately, so a DTI re-published across that boundary isn't deduplicated (rare).
- `area_m2` / `preco_m2` use IPTU *built* area, which for condominium units includes the share of common areas and parking — so R$/m² runs below the private-area R$/m² quoted in listings. The dashboard has an optional per-building *privativa ÷ construída* factor.
- **Distrito / subprefeitura** come from `geo/quadras_geo.parquet`: the centroid of each fiscal block (setor + quadra, the first 6 SQL digits) from the [GeoSampa](https://geosampa.prefeitura.sp.gov.br/) WFS, spatially joined to the official 96 distritos / 32 subprefeituras. ~99.95% of rows match. The raw `bairro` field is free text and empty for ~half the rows.
- **Atypical deals** (on by default, toggle in the sidebar): rows whose R$/m² (or value, without area) is outside ⅓×–3× the median of the *current filter* for the same segment and fiscal block, judged only where that group has ≥ 5 deals — catches bulk sales booked on a single unit and symbolic values without flagging expensive neighbourhoods.
- **Período** filters on the transaction date, relative to the latest transaction in the data (the ITBI is paid 1–2 months after the deal, so the last months are incomplete).
- **Raio** (300 m – 2 km) turns the address/CEP filter into a center and returns every deal around it, so other filters (segment, area, period) find comparables nearby; clicking the map picks the center instead, and the map's *locate me* button uses the device's position (never written to the shareable URL). Distance is measured to fiscal-block centroids.
- When the filter lands on a single address, a **building sheet** shows sales per year, unit types (grouped by IPTU area, which units of one type share) and the latest sales.
- **Exportar CSV** downloads every filtered row (not just the 100 shown), formatted for Excel pt-BR (`;` separator, decimal comma, UTF-8 BOM).
- **Seleção × cidade**: median R$/m² per semester (transaction date) of the selection vs the same filters city-wide without any location filter; semesters with < 5 priced deals are gaps and the current semester is left out (ITBI lag).
- **Imprimir / salvar PDF**: print stylesheet (white, no sidebar) with a header listing the active filters, an optional name for who prepared it, the date and the link back to the same view; the map prints as a snapshot.
- All filters are mirrored in the page URL, so a filtered view can be shared as a link.
- Exact re-published DTI rows (same property, date, value and street) are deduplicated before the parquet is written.

## License / attribution

Raw data © Prefeitura do Município de São Paulo.  
This processing pipeline and dashboard code are provided as-is for transparency and research use.
