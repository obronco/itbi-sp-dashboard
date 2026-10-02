#!/usr/bin/env python3
"""
Build geo/quadras_geo.parquet: one row per fiscal block (setor + quadra) with
its centroid, distrito and subprefeitura, from the Prefeitura's GeoSampa WFS.

The dashboard joins it to ITBI rows on the first 6 digits of the SQL
(setor 3 + quadra 3), so every transaction gets a location and an official
region without geocoding addresses. Condominium units share one lote polygon
in GeoSampa, so block level is the precision that works for the whole base.

Fiscal blocks change rarely, so the output is committed to the repo and this
script is run by hand (not in CI) when a refresh is wanted. Needs duckdb with
the spatial extension (downloaded on first use).
"""

from __future__ import annotations

import json
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "geo" / "quadras_geo.parquet"

WFS = "https://wfs.geosampa.prefeitura.sp.gov.br/geoserver/geoportal/wfs"
PAGE = 10_000


def wfs_get(layer: str, props: list[str], start: int | None = None) -> dict:
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": f"geoportal:{layer}",
        "outputFormat": "application/json",
        "srsName": "EPSG:4326",
        "propertyName": ",".join(props),
    }
    if start is not None:
        params |= {"count": PAGE, "startIndex": start, "sortBy": "cd_identificador"}
    url = f"{WFS}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=300) as r:
        return json.load(r)


def download(layer: str, props: list[str], dest: Path, paged: bool = False) -> list[Path]:
    if not paged:
        data = wfs_get(layer, props)
        dest.write_text(json.dumps(data))
        print(f"  {layer}: {len(data['features']):,} features")
        return [dest]
    paths, start = [], 0
    while True:
        data = wfs_get(layer, props, start)
        n = len(data["features"])
        if n == 0:
            break
        p = dest.with_name(f"{dest.stem}_{start // PAGE}.json")
        p.write_text(json.dumps(data))
        paths.append(p)
        start += n
        if n < PAGE:
            break
    print(f"  {layer}: {start:,} features")
    return paths


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        print("Downloading from GeoSampa WFS ...")
        quadras = download(
            "quadra_fiscal",
            ["cd_setor_fiscal", "cd_quadra_fiscal", "ge_poligono"],
            tmp / "quadras.json",
            paged=True,
        )
        distritos = download(
            "distrito_municipal",
            ["nm_distrito_municipal", "cd_identificador_subprefeitura", "ge_poligono"],
            tmp / "distritos.json",
        )[0]
        subpref = download(
            "subprefeitura",
            ["cd_identificador_subprefeitura", "nm_subprefeitura"],
            tmp / "subpref.json",
        )[0]

        c = duckdb.connect()
        c.sql("INSTALL spatial; LOAD spatial;")
        union = " UNION ALL BY NAME ".join(f"SELECT * FROM st_read('{p}')" for p in quadras)
        # A quadra can be split into several polygons (subquadras): merge first
        c.sql(f"""
            CREATE TABLE quadras AS
            SELECT cd_setor_fiscal AS setor, cd_quadra_fiscal AS quadra,
                   st_centroid(st_union_agg(geom)) AS c
            FROM ({union})
            WHERE cd_setor_fiscal IS NOT NULL AND cd_quadra_fiscal IS NOT NULL
            GROUP BY 1, 2
        """)
        c.sql(f"""
            CREATE TABLE distritos AS
            SELECT d.nm_distrito_municipal AS distrito, s.nm_subprefeitura AS subpref, d.geom
            FROM st_read('{distritos}') d
            LEFT JOIN st_read('{subpref}') s USING (cd_identificador_subprefeitura)
        """)
        # Centroid inside a distrito; the few on borders/outside fall back to nearest
        c.sql("""
            CREATE TABLE out AS
            SELECT q.setor || q.quadra AS sq,
                   round(st_y(q.c), 5)::FLOAT AS lat,
                   round(st_x(q.c), 5)::FLOAT AS lon,
                   coalesce(d.distrito, n.distrito) AS distrito,
                   coalesce(d.subpref, n.subpref) AS subpref
            FROM quadras q
            LEFT JOIN distritos d ON st_contains(d.geom, q.c)
            LEFT JOIN (
                SELECT q2.setor, q2.quadra,
                       arg_min(d2.distrito, st_distance(d2.geom, q2.c)) AS distrito,
                       arg_min(d2.subpref, st_distance(d2.geom, q2.c)) AS subpref
                FROM quadras q2, distritos d2
                WHERE NOT EXISTS (SELECT 1 FROM distritos d3 WHERE st_contains(d3.geom, q2.c))
                GROUP BY 1, 2
            ) n ON n.setor = q.setor AND n.quadra = q.quadra
            -- a centroid on a shared border can fall in two distritos; keep one
            QUALIFY row_number() OVER (PARTITION BY q.setor, q.quadra ORDER BY d.distrito) = 1
            ORDER BY sq
        """)
        c.sql(f"COPY out TO '{OUT}' (FORMAT parquet, COMPRESSION zstd)")
        n, nd, ndist = c.sql(
            "SELECT count(*), count(distrito), count(DISTINCT distrito) FROM out"
        ).fetchone()
        print(f"\n{OUT.relative_to(ROOT)}: {n:,} quadras, {nd:,} with distrito "
              f"({ndist} distritos), {OUT.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
