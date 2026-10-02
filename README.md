# ITBI São Paulo — Dashboard

Single-page dashboard of real-estate transactions in São Paulo with ITBI payment (official municipal data).

- **Source**: [Prefeitura de São Paulo — Dados das Transações Imobiliárias (ITBI)](https://prefeitura.sp.gov.br/web/fazenda/w/acesso_a_informacao/31501)
- **Lookback**: last 5 calendar years
- **Stack**: static HTML + DuckDB-WASM + Chart.js + MapLibre GL (basemap tiles from [OpenFreeMap](https://openfreemap.org/), no API key)
- **Pipeline**: GitHub Actions downloads the yearly Excels, cleans them into a compact Parquet, and deploys to GitHub Pages

## Live site

After the first successful workflow run:

`https://<your-user>.github.io/<repo-name>/`

## Local development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Download official Excel files into data/
python scripts/download_itbi.py

# Clean + build itbi_sp_5y.parquet
python scripts/preprocess_itbi.py

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

## Updating download URLs

The Prefeitura occasionally rotates the Excel links (especially for the current year).  
Edit `YEAR_URLS` in `scripts/download_itbi.py` when a download starts failing.  
Official page: https://prefeitura.sp.gov.br/web/fazenda/w/acesso_a_informacao/31501

## Data notes

- Each row is a paid DTI in the **payment month** (sheet name), not necessarily the transaction month.
- Self-declared values; rural properties and PPI parcelamentos are excluded by the source.
- `preco_m2` is computed only when area (built area, or land area for `terreno`) is within the segment's expected band and the result is between R$ 100 and R$ 150 000.
- Means are sensitive to large corporate deals; prefer medians.
- `area_m2` / `preco_m2` use IPTU *built* area, which for condominium units includes the share of common areas and parking — so R$/m² runs below the private-area R$/m² quoted in listings. The dashboard has an optional per-building *privativa ÷ construída* factor.
- **Distrito / subprefeitura** come from `geo/quadras_geo.parquet`: the centroid of each fiscal block (setor + quadra, the first 6 SQL digits) from the [GeoSampa](https://geosampa.prefeitura.sp.gov.br/) WFS, spatially joined to the official 96 distritos / 32 subprefeituras. ~99.95% of rows match. The raw `bairro` field is free text and empty for ~half the rows.
- **Atypical deals** (on by default, toggle in the sidebar): rows whose R$/m² (or value, without area) is outside ⅓×–3× the median of the *current filter* for the same segment and fiscal block, judged only where that group has ≥ 5 deals — catches bulk sales booked on a single unit and symbolic values without flagging expensive neighbourhoods.
- **Período** filters on the transaction date, relative to the latest transaction in the data (the ITBI is paid 1–2 months after the deal, so the last months are incomplete).
- All filters are mirrored in the page URL, so a filtered view can be shared as a link.
- Exact re-published DTI rows (same property, date, value and street) are deduplicated before the parquet is written.

## License / attribution

Raw data © Prefeitura do Município de São Paulo.  
This processing pipeline and dashboard code are provided as-is for transparency and research use.
