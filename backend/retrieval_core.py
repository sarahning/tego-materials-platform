import ast
import json
import math
import re
import shutil
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple, Union

import pandas as pd

from .config import OUTPUT_DIR, PROPERTY_SPECS, PROPERTY_KEYS, RETRIEVAL_CSVS

PROPERTY_COLUMNS = PROPERTY_KEYS
PathLikeOrList = Union[Path, str, Iterable[Union[Path, str]], None]


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def safe_float(x) -> Optional[float]:
    try:
        if x is None or pd.isna(x):
            return None
        v = float(x)
        if math.isfinite(v):
            return v
        return None
    except Exception:
        return None


def stress_to_scalar(x) -> Optional[float]:
    v = safe_float(x)
    if v is not None:
        return v
    try:
        s = str(x).strip()
        if not s or s.lower() in {"nan", "none", "null"}:
            return None
        try:
            obj = ast.literal_eval(s)
            if isinstance(obj, (list, tuple)):
                flat = []
                stack = list(obj)
                while stack:
                    item = stack.pop()
                    if isinstance(item, (list, tuple)):
                        stack.extend(item)
                    else:
                        fv = safe_float(item)
                        if fv is not None:
                            flat.append(fv)
                if flat:
                    return math.sqrt(sum(float(i) ** 2 for i in flat))
        except Exception:
            pass
        nums = re.findall(r"[-+]?\d*\.\d+|[-+]?\d+", s)
        vals = [float(vv) for vv in nums if vv not in {"", "+", "-"}]
        vals = [vv for vv in vals if math.isfinite(vv)]
        if vals:
            return math.sqrt(sum(vv ** 2 for vv in vals))
    except Exception:
        return None
    return None


def property_value(x, prop: str) -> Optional[float]:
    if prop == "cauchy_stress":
        return stress_to_scalar(x)
    return safe_float(x)


def safe_name(x: object) -> str:
    text = str(x if x is not None else "material")
    for ch in ['\\', '/', ':', '*', '?', '"', '<', '>', '|', ' ']:
        text = text.replace(ch, '_')
    return text[:120] or "material"


def reset_output_dir() -> None:
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR, ignore_errors=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _normalize_paths(database_csv: PathLikeOrList = None) -> List[Path]:
    if database_csv is None:
        raw = RETRIEVAL_CSVS
    elif isinstance(database_csv, (str, Path)):
        raw = [database_csv]
    else:
        raw = list(database_csv)
    paths: List[Path] = []
    seen = set()
    for p in raw:
        pp = Path(p)
        key = str(pp).lower()
        if key in seen:
            continue
        seen.add(key)
        paths.append(pp)
    return paths




def _first_existing_column(df: pd.DataFrame, names: List[str]) -> Optional[str]:
    lower_to_original = {str(c).strip().lower(): c for c in df.columns}
    for name in names:
        if name in df.columns:
            return name
        low = str(name).strip().lower()
        if low in lower_to_original:
            return lower_to_original[low]
    return None


def _ensure_dielectric_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure dielectric_epsx / dielectric_epsy / dielectric_epsz and scalar dielectric_constant exist.

    The scalar dielectric_constant is only used for sorting and plotting; the three original
    components remain available for display.
    """
    component_aliases = {
        "dielectric_epsx": ["dielectric_epsx", "epsx", "epsilon_x", "eps_x"],
        "dielectric_epsy": ["dielectric_epsy", "epsy", "epsilon_y", "eps_y"],
        "dielectric_epsz": ["dielectric_epsz", "epsz", "epsilon_z", "eps_z"],
    }

    for target_col, aliases in component_aliases.items():
        if target_col not in df.columns:
            src = _first_existing_column(df, aliases)
            df[target_col] = df[src] if src is not None else None

    scalar_src = _first_existing_column(
        df,
        [
            "dielectric_constant",
            "dielectric",
            "dielectric_mean",
            "dielectric_avg",
            "epsilon",
            "epsilon_mean",
            "eps_mean",
            "avg_epsilon",
            "mean_epsilon",
        ],
    )

    if scalar_src is not None and scalar_src != "dielectric_constant":
        df["dielectric_constant"] = df[scalar_src]
    elif "dielectric_constant" not in df.columns:
        df["dielectric_constant"] = None

    eps_df = pd.DataFrame({
        "x": pd.to_numeric(df["dielectric_epsx"], errors="coerce"),
        "y": pd.to_numeric(df["dielectric_epsy"], errors="coerce"),
        "z": pd.to_numeric(df["dielectric_epsz"], errors="coerce"),
    })
    component_mean = eps_df.mean(axis=1, skipna=True)
    scalar = pd.to_numeric(df["dielectric_constant"], errors="coerce")
    df["dielectric_constant"] = scalar.where(scalar.notna(), component_mean)
    return df


def _standardize_dataframe(df: pd.DataFrame, source_name: str) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    lower_to_original = {str(c).lower(): c for c in df.columns}

    if "cif" not in df.columns:
        cif_col = lower_to_original.get("cif")
        if cif_col is None:
            raise ValueError("missing cif")
        df["cif"] = df[cif_col]

    if "material_id" not in df.columns:
        mid_col = lower_to_original.get("material_id")
        if mid_col is not None:
            df["material_id"] = df[mid_col]
        elif "pretty_formula" in df.columns:
            df["material_id"] = [f"{source_name}_{i}_{v}" for i, v in enumerate(df["pretty_formula"].astype(str))]
        else:
            df["material_id"] = [f"{source_name}_row_{i}" for i in range(len(df))]

    for spec in PROPERTY_SPECS:
        key = spec["key"]
        if key in df.columns:
            continue
        found = None
        for alias in spec.get("aliases", []):
            if alias in df.columns:
                found = alias
                break
            low = str(alias).lower()
            if low in lower_to_original:
                found = lower_to_original[low]
                break
        df[key] = df[found] if found is not None else None

    df = _ensure_dielectric_columns(df)

    df["source_dataset"] = source_name
    return df


def load_database(database_csv: PathLikeOrList = None) -> pd.DataFrame:
    paths = _normalize_paths(database_csv)
    dfs: List[pd.DataFrame] = []
    missing = []
    for path in paths:
        if not path.exists():
            missing.append(str(path))
            continue
        try:
            df = pd.read_csv(path, low_memory=False)
            dfs.append(_standardize_dataframe(df, path.name))
        except Exception:
            continue

    if not dfs:
        if missing:
            raise FileNotFoundError(f"database csv not found: {missing[0]}")
        raise FileNotFoundError("database csv not found")

    return pd.concat(dfs, axis=0, ignore_index=True)


def weighted_relative_error(
    row: pd.Series,
    target_properties: Dict[str, float],
    property_weights: Dict[str, float],
    eps: float = 1e-12,
) -> Tuple[float, Dict[str, Dict[str, Optional[float]]]]:
    weighted_sum = 0.0
    weight_sum = 0.0
    detail = {}

    for prop in PROPERTY_COLUMNS:
        w = float(property_weights.get(prop, 0.0) or 0.0)
        if w == 0.0:
            continue

        if prop not in target_properties:
            continue

        target_val = property_value(target_properties[prop], prop)
        row_val = property_value(row.get(prop, None), prop)

        if target_val is None or row_val is None:
            detail[prop] = {
                "target": target_val,
                "value": row_val,
                "relative_error": None,
                "weight": w,
                "used": False,
            }
            continue

        denom = max(abs(row_val), abs(target_val))
        if denom < eps:
            rel_err = 0.0
        else:
            rel_err = abs(row_val - target_val) / denom

        weighted_sum += w * rel_err
        weight_sum += w
        detail[prop] = {
            "target": target_val,
            "value": row_val,
            "relative_error": rel_err,
            "weight": w,
            "used": True,
        }

    total_error = weighted_sum / weight_sum if weight_sum > 0 else float("inf")
    return total_error, detail


def save_cif(cif_text: str, material_id: object, rank: int) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / f"rank_{rank:03d}_{safe_name(material_id)}.cif"
    out.write_text("" if cif_text is None else str(cif_text), encoding="utf-8")
    return out


def retrieve_candidates(
    target_properties: Dict[str, Optional[float]],
    property_weights: Dict[str, float],
    k: int = 5,
    database_csv: PathLikeOrList = None,
) -> Dict:
    if k <= 0:
        raise ValueError("k must be > 0")

    reset_output_dir()
    paths = _normalize_paths(database_csv)
    df = load_database(paths)

    valid_positive_weight_count = 0
    for prop in PROPERTY_COLUMNS:
        w = float(property_weights.get(prop, 0.0) or 0.0)
        if w > 0 and prop in target_properties and property_value(target_properties[prop], prop) is not None:
            valid_positive_weight_count += 1
    if valid_positive_weight_count == 0:
        raise ValueError("At least one property must have positive weight and valid target value.")

    records: List[Dict] = []
    for idx, row in df.iterrows():
        cif_text = row.get("cif", None)
        if cif_text is None or pd.isna(cif_text) or not str(cif_text).strip():
            continue

        total_error, detail = weighted_relative_error(
            row=row,
            target_properties=target_properties,
            property_weights=property_weights,
        )
        if math.isinf(total_error):
            continue

        rec = {
            "row_index": int(idx),
            "source_row_idx": int(idx),
            "source_dataset": str(row.get("source_dataset", "")),
            "material_id": row["material_id"],
            "cif": str(cif_text),
            "retrieval_error": float(total_error),
            "score": float(total_error),
            "error_detail": detail,
        }
        for prop in PROPERTY_COLUMNS:
            rec[prop] = property_value(row.get(prop, None), prop)
        for comp in ("dielectric_epsx", "dielectric_epsy", "dielectric_epsz"):
            rec[comp] = safe_float(row.get(comp, None))
        records.append(rec)

    if not records:
        raise RuntimeError("No valid retrieval results found.")

    records.sort(key=lambda x: x["retrieval_error"])
    topk = records[: min(k, len(records))]

    saved_results = []
    for rank, item in enumerate(topk, start=1):
        cif_path = save_cif(item["cif"], item["material_id"], rank)
        result_item = {
            "rank": rank,
            "candidate_id": f"cand_{rank:03d}",
            "material_id": str(item["material_id"]),
            "source_row_idx": item["source_row_idx"],
            "source_dataset": item.get("source_dataset", ""),
            "retrieval_error": item["retrieval_error"],
            "score": item["retrieval_error"],
            "cif_path": str(cif_path),
            "properties": {
                **{prop: item[prop] for prop in PROPERTY_COLUMNS},
                "dielectric_epsx": item.get("dielectric_epsx"),
                "dielectric_epsy": item.get("dielectric_epsy"),
                "dielectric_epsz": item.get("dielectric_epsz"),
            },
            "error_detail": item["error_detail"],
        }
        saved_results.append(result_item)

    summary = {
        "database_csvs": [str(p) for p in paths],
        "output_dir": str(OUTPUT_DIR.resolve()),
        "k_requested": k,
        "k_returned": len(saved_results),
        "target_properties": target_properties,
        "property_weights": property_weights,
        "results": saved_results,
    }

    (OUTPUT_DIR / "generation_results.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary
