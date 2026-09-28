# ITBI São Paulo — Dashboard

Single-page dashboard of real-estate transactions in São Paulo with ITBI payment (official municipal data).

- **Source**: [Prefeitura de São Paulo — Dados das Transações Imobiliárias (ITBI)](https://prefeitura.sp.gov.br/web/fazenda/w/acesso_a_informacao/31501)
- **Lookback**: last 5 calendar years
- **Stack**: static HTML + DuckDB-WASM + Chart.js
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
- `preco_m2` is computed only when built area > 0 and the result is between R$ 100 and R$ 150 000.
- Means are sensitive to large corporate deals; prefer medians.

## License / attribution

Raw data © Prefeitura do Município de São Paulo.  
This processing pipeline and dashboard code are provided as-is for transparency and research use.
