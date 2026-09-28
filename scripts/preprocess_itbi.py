#!/usr/bin/env python3
"""
Preprocess ITBI São Paulo Excel files (last 5 years) into a clean, compact Parquet.

Adds quality flags and segments so the dashboard can default to market-like
slices (compra e venda, full transfer, unit-scale area) and treat offices
(uso 30 salas vs uso 31 prédios) correctly.
"""

from __future__ import annotations

import re
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

warnings.filterwarnings("ignore", category=UserWarning)

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUT_PARQUET = ROOT / "itbi_sp_5y.parquet"
YEARS = [2022, 2023, 2024, 2025, 2026]
MONTH_MAP = {
    "JAN": 1,
    "FEV": 2,
    "MAR": 3,
    "ABR": 4,
    "MAI": 5,
    "JUN": 6,
    "JUL": 7,
    "AGO": 8,
    "SET": 9,
    "OUT": 10,
    "NOV": 11,
    "DEZ": 12,
}

CANONICAL = [
    "sql",
    "logradouro",
    "numero",
    "complemento",
    "bairro",
    "referencia",
    "cep",
    "natureza",
    "valor_transacao",
    "data_transacao",
    "valor_venal",
    "proporcao",
    "valor_venal_prop",
    "base_calculo",
    "tipo_financiamento",
    "valor_financiado",
    "cartorio",
    "matricula",
    "situacao_sql",
    "area_terreno",
    "testada",
    "fracao_ideal",
    "area_construida",
    "uso",
    "desc_uso",
    "padrao",
    "desc_padrao",
    "acc",
]

RENAME = {
    "N° do Cadastro (SQL)": "sql",
    "Nome do Logradouro": "logradouro",
    "Número": "numero",
    "Complemento": "complemento",
    "Bairro": "bairro",
    "Referência": "referencia",
    "CEP": "cep",
    "Natureza de Transação": "natureza",
    "Valor de Transação (declarado pelo contribuinte)": "valor_transacao",
    "Data de Transação": "data_transacao",
    "Valor Venal de Referência": "valor_venal",
    "Proporção Transmitida (%)": "proporcao",
    "Valor Venal de Referência (proporcional)": "valor_venal_prop",
    "Base de Cálculo adotada": "base_calculo",
    "Tipo de Financiamento": "tipo_financiamento",
    "Valor Financiado": "valor_financiado",
    "Cartório de Registro": "cartorio",
    "Matrícula do Imóvel": "matricula",
    "Situação do SQL": "situacao_sql",
    "Área do Terreno (m2)": "area_terreno",
    "Testada (m)": "testada",
    "Fração Ideal": "fracao_ideal",
    "Área Construída (m2)": "area_construida",
    "Uso (IPTU)": "uso",
    "Descrição do uso (IPTU)": "desc_uso",
    "Padrão (IPTU)": "padrao",
    "Descrição do padrão (IPTU)": "desc_padrao",
    "ACC (IPTU)": "acc",
}

# IPTU uso → analysis segment
USO_SEGMENTO = {
    20: "apt_condominio",
    21: "predio_apt_nao_condo",
    22: "predio_apt_misto",
    24: "garagem_residencial",
    25: "flat_residencial",
    10: "residencia",
    12: "residencia_coletiva",
    14: "residencia_mista",
    30: "sala_condominio",  # office unit — primary office interest
    31: "predio_escritorio",  # non-condo office building
    32: "predio_misto_nao_res",
    40: "loja",
    41: "loja_condominio",
    42: "loja_residencia",
    23: "garagem_escritorio",
    0: "terreno",
    50: "industria",
    51: "deposito",
    60: "oficina",
    80: "hotel",
    85: "flat_comercial",
    71: "escola",
}

# Area bands (m²) where valor/area is meaningful as unit (or small-building) R$/m²
AREA_BANDS = {
    "sala_condominio": (20, 500),
    "loja_condominio": (15, 400),
    "apt_condominio": (20, 600),
    "flat_residencial": (20, 200),
    "flat_comercial": (20, 200),
    "garagem_residencial": (8, 50),
    "garagem_escritorio": (8, 50),
    "residencia": (30, 800),
    "residencia_coletiva": (30, 800),
    "residencia_mista": (30, 1000),
    "predio_escritorio": (50, 2000),  # only for full-transfer small/medium
    "predio_apt_nao_condo": (50, 2000),
    "predio_apt_misto": (50, 2000),
    "predio_misto_nao_res": (50, 2000),
    "loja": (15, 800),
    "loja_residencia": (30, 1000),
    "default": (20, 600),
}

# Bairro values that are really complemento / building parts
# Bairro values that are really complemento / building / unit labels
BAIRRO_LIXO_RE = re.compile(
    r"^(?:"
    r"TORRE|BLOCO|BL\.?|"
    r"AP|APTO|APT|"
    r"SALA|SL\.?|ESCRIT(?:ORIO)?|ESCR\.?|"
    r"LJ\.?|LOJA|SOBRELOJA|SLJ|"
    r"CJ\.?|CONJ(?:UNTO)?|"
    r"ANDAR|AN\.?|PAV(?:IMENTO)?|"
    r"COBERTURA|COB\.?|DUPLEX|TRIPLEX|COBERT|"
    r"CASA|CS\.?|FUNDOS|FD\.?|"
    r"BOX|VAGA|VAGAS|VG\.?|"
    r"DEPOSITO|DEP\.?|"
    r"ED(?:IFICIO)?\.?|EDIF(?:ICIO)?\.?|"
    r"CONDOMINIO|COND\.?|"
    r"UNIDADE|UH\.?|APTOS?"
    r")\b"
    r"|\b(?:VAGAS?|DUPLEX|TRIPLEX)\b"
    r"|^[\d\s\.\-/]+$"
    r"|\d\s*VAGAS?",
    re.IGNORECASE,
)

# Light normalization of common neighborhood spellings (after junk filter)
BAIRRO_NORM = {
    "JD PAULISTA": "JARDIM PAULISTA",
    "JD. PAULISTA": "JARDIM PAULISTA",
    "JARDIM PAULISTA": "JARDIM PAULISTA",
    "ITAIM": "ITAIM BIBI",
    "ITAIM BIBI": "ITAIM BIBI",
    "ITAIM  BIBI": "ITAIM BIBI",
    "CHACARA ITAIM": "ITAIM BIBI",
    "JD AMERICA": "JARDIM AMERICA",
    "JD. AMERICA": "JARDIM AMERICA",
    "VILA OLIMPIA": "VILA OLIMPIA",
    "VL OLIMPIA": "VILA OLIMPIA",
    "VL. OLIMPIA": "VILA OLIMPIA",
    "BROOKLIN PAULISTA": "BROOKLIN",
    "BROOKLIN NOVO": "BROOKLIN",
}

DROP_COLS = [
    "referencia",
    "cartorio",
    "matricula",
    "situacao_sql",
    "testada",
    "acc",
    "valor_venal",
    "valor_venal_prop",
]


def clean_cep(s: pd.Series) -> pd.Series:
    s = s.astype(str).str.replace(r"\D", "", regex=True)
    s = s.str.zfill(8).str.slice(0, 8)
    valid = s.str.match(r"^\d{8}$") & (s != "00000000")
    return s.where(valid, other=pd.NA)


def to_numeric(s: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(s):
        return pd.to_numeric(s, errors="coerce")
    s = s.astype(str).str.replace(r"[^\d,.\-]", "", regex=True)
    s = s.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
    return pd.to_numeric(s, errors="coerce")


def clean_bairro(s: pd.Series) -> pd.Series:
    """Keep only values that look like real neighborhood names."""
    out = s.astype("string").str.strip()
    out = out.replace({"": pd.NA, "nan": pd.NA, "None": pd.NA, "<NA>": pd.NA})
    # collapse internal whitespace
    out = out.str.replace(r"\s+", " ", regex=True)
    bad = out.notna() & out.str.contains(BAIRRO_LIXO_RE, na=False)
    bad = bad | (out.str.len() < 3)
    out = out.mask(bad, other=pd.NA)
    # normalize known aliases
    upper = out.str.upper()
    mapped = upper.map(BAIRRO_NORM)
    out = mapped.fillna(out)
    return out


def map_segmento(uso: pd.Series) -> pd.Series:
    return uso.map(USO_SEGMENTO).fillna("outros").astype("string")


def normalize_proporcao_pct(proporcao: pd.Series) -> pd.Series:
    """
    Map raw proporcao into a 0–100 percentage when possible.
    - (0, 1]  → treat as fraction → ×100
    - (1, 100] → already percent
    - else    → NA (noise / unknown scale)
    """
    p = pd.to_numeric(proporcao, errors="coerce")
    out = pd.Series(np.nan, index=p.index, dtype="float64")
    frac = (p > 0) & (p <= 1)
    pct = (p > 1) & (p <= 100)
    out = out.mask(frac, p * 100.0)
    out = out.mask(pct, p)
    # exact 100 already covered by pct; keep 100
    out = out.mask(p == 100, 100.0)
    return out


def area_band_ok(segmento: pd.Series, area: pd.Series) -> pd.Series:
    ok = pd.Series(False, index=segmento.index)
    area = pd.to_numeric(area, errors="coerce")
    for seg, (lo, hi) in AREA_BANDS.items():
        if seg == "default":
            continue
        m = segmento == seg
        ok = ok | (m & area.between(lo, hi))
    # fallback for unlisted segments
    lo, hi = AREA_BANDS["default"]
    m = ~segmento.isin([s for s in AREA_BANDS if s != "default"])
    ok = ok | (m & area.between(lo, hi))
    return ok.fillna(False)


def enrich(df: pd.DataFrame) -> pd.DataFrame:
    """Derived quality fields and segments."""
    df = df.copy()

    # --- bairro ---
    df["bairro_raw"] = df["bairro"].astype("string")
    df["bairro"] = clean_bairro(df["bairro_raw"])

    # --- ownership / natureza ---
    nat = df["natureza"].astype("string").fillna("")
    df["is_compra_venda"] = nat.str.contains("Compra e venda", case=False, na=False)

    df["proporcao_pct"] = normalize_proporcao_pct(df["proporcao"])
    df["is_transferencia_total"] = df["proporcao_pct"].between(99, 101)

    # --- segment ---
    df["segmento"] = map_segmento(df["uso"])

    # --- area & price ---
    area = pd.to_numeric(df["area_construida"], errors="coerce").replace(0, np.nan)
    df["area_util_ok"] = area_band_ok(df["segmento"], area)

    # Raw R$/m² only when area is in segment band (avoids building-scale SQL)
    preco = df["valor_transacao"] / area
    preco = preco.where(df["area_util_ok"])
    preco = preco.where((preco >= 100) & (preco <= 150_000))
    df["preco_m2"] = preco.round(2)

    # Market-analysis ready: compra e venda + full transfer + usable unit area + price
    df["mercado_ok"] = (
        df["is_compra_venda"]
        & df["is_transferencia_total"]
        & df["area_util_ok"]
        & df["preco_m2"].notna()
    )

    # Office convenience flags
    df["is_sala_escritorio"] = df["segmento"] == "sala_condominio"
    df["is_predio_escritorio"] = df["segmento"] == "predio_escritorio"

    return df


def process_sheet(df: pd.DataFrame, year: int, month: int) -> pd.DataFrame:
    df = df.rename(columns=lambda c: str(c).strip() if c is not None else c)
    df = df.dropna(how="all")
    if df.empty:
        return pd.DataFrame()

    df = df.rename(columns={k: v for k, v in RENAME.items() if k in df.columns})

    keep = [c for c in CANONICAL if c in df.columns]
    df = df[keep].copy()
    for c in CANONICAL:
        if c not in df.columns:
            df[c] = np.nan
    df = df[CANONICAL]

    df["sql"] = df["sql"].astype(str).str.replace(r"\D", "", regex=True).str.strip()
    df.loc[df["sql"].isin(["", "nan", "None", "0"]), "sql"] = pd.NA

    for col in [
        "logradouro",
        "complemento",
        "bairro",
        "referencia",
        "natureza",
        "tipo_financiamento",
        "cartorio",
        "situacao_sql",
        "desc_uso",
        "desc_padrao",
    ]:
        df[col] = (
            df[col]
            .astype(str)
            .str.strip()
            .replace({"nan": None, "None": None, "": None, "<NA>": None})
        )

    df["cep"] = clean_cep(df["cep"])

    for col in [
        "numero",
        "valor_transacao",
        "valor_venal",
        "proporcao",
        "valor_venal_prop",
        "base_calculo",
        "valor_financiado",
        "area_terreno",
        "testada",
        "fracao_ideal",
        "area_construida",
        "uso",
        "padrao",
        "acc",
        "matricula",
    ]:
        df[col] = to_numeric(df[col])

    df["data_transacao"] = pd.to_datetime(df["data_transacao"], errors="coerce")

    df["ano_pag"] = year
    df["mes_pag"] = month
    df["ano_mes_pag"] = f"{year}-{month:02d}"

    mask = (
        df["valor_transacao"].notna()
        & (df["valor_transacao"] > 1000)
        & (df["valor_transacao"] < 500_000_000)
        & (df["sql"].notna() | df["logradouro"].notna())
    )
    df = df.loc[mask].copy()
    if df.empty:
        return df

    df = df.drop(columns=[c for c in DROP_COLS if c in df.columns], errors="ignore")
    df = enrich(df)
    return df


def process_year(year: int) -> pd.DataFrame:
    path = DATA_DIR / f"itbi_{year}.xlsx"
    print(f"Processing {path.name} ...")
    xl = pd.ExcelFile(path, engine="openpyxl")
    frames = []
    for sheet in xl.sheet_names:
        m = re.match(
            r"^(JAN|FEV|MAR|ABR|MAI|JUN|JUL|AGO|SET|OUT|NOV|DEZ)-(\d{4})$", sheet
        )
        if not m:
            continue
        month = MONTH_MAP[m.group(1)]
        y = int(m.group(2))
        if y != year:
            continue
        print(f"  sheet {sheet} ...", end=" ", flush=True)
        try:
            df = pd.read_excel(xl, sheet_name=sheet, header=0, dtype=object)
            has_header = any(
                ("Cadastro" in str(c)) or ("SQL" in str(c)) or (str(c) == "sql")
                for c in df.columns
            )
            if not has_header:
                df = pd.read_excel(xl, sheet_name=sheet, header=None, dtype=object)
                if df.shape[1] >= 28:
                    df = df.iloc[:, :28].copy()
                    df.columns = list(RENAME.keys())
                else:
                    print(f"unexpected cols={df.shape[1]}")
                    continue
            cleaned = process_sheet(df, year, month)
            print(f"{len(cleaned):,} rows")
            if not cleaned.empty:
                frames.append(cleaned)
        except Exception as e:
            print(f"ERROR: {e}")
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    all_frames = []
    for y in YEARS:
        path = DATA_DIR / f"itbi_{y}.xlsx"
        if not path.exists():
            print(f"WARNING: missing {path} — skip year {y}")
            continue
        df = process_year(y)
        if not df.empty:
            all_frames.append(df)
            print(f"  year {y}: {len(df):,} clean rows")

    if not all_frames:
        raise SystemExit("No data produced — check downloads")

    full = pd.concat(all_frames, ignore_index=True)

    str_cols = [
        "sql",
        "cep",
        "logradouro",
        "complemento",
        "bairro",
        "bairro_raw",
        "natureza",
        "tipo_financiamento",
        "desc_uso",
        "desc_padrao",
        "ano_mes_pag",
        "segmento",
    ]
    for c in str_cols:
        if c in full.columns:
            full[c] = full[c].astype("string")

    bool_cols = [
        "is_compra_venda",
        "is_transferencia_total",
        "area_util_ok",
        "mercado_ok",
        "is_sala_escritorio",
        "is_predio_escritorio",
    ]
    for c in bool_cols:
        if c in full.columns:
            full[c] = full[c].astype("boolean")

    table = pa.Table.from_pandas(full, preserve_index=False)
    pq.write_table(table, OUT_PARQUET, compression="zstd")
    size_mb = OUT_PARQUET.stat().st_size / (1024 * 1024)
    print(f"\nFinal: {OUT_PARQUET}  rows={len(full):,}  size={size_mb:.1f} MB")
    print(full.groupby("ano_pag").size().to_string())
    print("\nsegmento counts:")
    print(full["segmento"].value_counts().head(15).to_string())
    print(
        f"\nmercado_ok: {full['mercado_ok'].sum():,} "
        f"({100 * full['mercado_ok'].mean():.1f}%)"
    )
    print(
        f"sala_condominio mercado_ok: "
        f"{full.loc[full['is_sala_escritorio'] & full['mercado_ok']].shape[0]:,}"
    )
    print(
        f"predio_escritorio mercado_ok: "
        f"{full.loc[full['is_predio_escritorio'] & full['mercado_ok']].shape[0]:,}"
    )


if __name__ == "__main__":
    main()
