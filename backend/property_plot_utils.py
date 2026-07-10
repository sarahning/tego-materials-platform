import ast
import re
import os
import shutil
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from .config import (
    DATABASE_CSV,
    RETRIEVAL_CSVS,
    PROPERTY_LABELS,
    PROPERTY_PLOT_DIR,
    PROPERTY_SPECS,
    PROPERTY_UNITS,
    ROOT_DIR,
)
from .retrieval_core import safe_float, safe_name

# The distribution module follows the user's previous plotting script:
# merge train/test/val CSV files first, then plot one total distribution per property.
# It also keeps the stress-to-scalar handling by Frobenius norm.
PROPERTY_PLOT_CONFIG = {
    "band_gap": {
        "title": "Band Gap Distribution",
        "xlabel": "Band Gap (eV)",
        "outfile": "band_gap_distribution.png",
        "cutoff": None,
        "special": None,
    },
    "bulk_modulus": {
        "title": "Bulk Modulus Distribution",
        "xlabel": "Bulk Modulus (GPa)",
        "outfile": "bulk_modulus_distribution.png",
        "cutoff": None,
        "special": None,
    },
    "larsen_score_2d": {
        "title": "Larsen 2D Score Distribution",
        "xlabel": "Larsen 2D Score",
        "outfile": "larsen_score_2d_distribution.png",
        "cutoff": None,
        "special": None,
    },
    "dielectric_constant": {
        "title": "Dielectric Constant Distribution",
        "xlabel": "Mean Dielectric Constant from εx / εy / εz",
        "outfile": "dielectric_constant_distribution.png",
        "cutoff": None,
        "special": "dielectric_mean",
    },
    "mag_density": {
        "title": "Magnetic Density Distribution",
        "xlabel": "Magnetic Density (μB/Å³)",
        "outfile": "mag_density_distribution.png",
        "cutoff": 0.15,
        "special": None,
    },
    "cauchy_stress": {
        "title": "Cauchy Stress Distribution",
        "xlabel": "Cauchy Stress / Stress Magnitude (GPa)",
        "outfile": "cauchy_stress_distribution.png",
        "cutoff": None,
        "special": "stress_magnitude",
    },
}

ABS_DIST_PATHS = [
    Path(r"C:\Users\Lenovo\Desktop\1.15任务成果保存\mattergen-main\tego\mp20_with_jav_dielectric\mp20_with_jav_epsx_epsy_epsz.csv"),
]


def distribution_csv_paths(database_csv: Optional[Union[Path, str, Iterable[Union[Path, str]]]] = None) -> List[Path]:
    env_paths = [
        os.getenv("DIST_TRAIN_CSV"),
        os.getenv("DIST_VALIDATION_CSV"),
        os.getenv("DIST_TEST_CSV"),
    ]
    candidates: List[Path] = []
    for p in env_paths:
        if p:
            candidates.append(Path(p))

    # Use the merged MP20+JAV dielectric dataset by default.
    for base in [ROOT_DIR, ROOT_DIR.parent, ROOT_DIR.parent.parent]:
        candidates.extend([
            base / "mp20_with_jav_epsx_epsy_epsz.csv",
            base / "mp20_with_jav_dielectric" / "mp20_with_jav_epsx_epsy_epsz.csv",
        ])

    candidates.extend(ABS_DIST_PATHS)
    if database_csv:
        if isinstance(database_csv, (str, Path)):
            candidates.append(Path(database_csv))
        else:
            for p in database_csv:
                candidates.append(Path(p))
    candidates.extend([Path(p) for p in RETRIEVAL_CSVS])
    candidates.append(Path(DATABASE_CSV))

    seen = set()
    out = []
    for p in candidates:
        key = str(p.resolve() if p.exists() else p)
        if key in seen:
            continue
        seen.add(key)
        if p.exists() and p.is_file():
            out.append(p)
    return out


@lru_cache(maxsize=4)
def _load_distribution_dataframe_cached(paths_key: Tuple[str, ...]) -> pd.DataFrame:
    dfs = []
    for path_str in paths_key:
        path = Path(path_str)
        if path.exists():
            try:
                df = pd.read_csv(path, low_memory=False)
                df.columns = [str(c).strip() for c in df.columns]
                dfs.append(df)
            except Exception:
                continue
    if not dfs:
        return pd.DataFrame()
    return pd.concat(dfs, axis=0, ignore_index=True)


def load_distribution_dataframe(database_csv: Optional[Union[Path, str, Iterable[Union[Path, str]]]] = None) -> pd.DataFrame:
    paths = distribution_csv_paths(database_csv)
    return _load_distribution_dataframe_cached(tuple(str(p) for p in paths))


def aliases_for(key: str) -> List[str]:
    for spec in PROPERTY_SPECS:
        if spec["key"] == key:
            aliases = [spec["key"]] + list(spec.get("aliases", []))
            if key == "cauchy_stress":
                aliases.extend(["pressure", "stress"])
            return list(dict.fromkeys(aliases))
    return [key]


def find_column(df: pd.DataFrame, aliases: List[str]) -> Optional[str]:
    lower_to_original = {str(c).lower(): c for c in df.columns}
    for alias in aliases:
        if alias in df.columns:
            return alias
        low = str(alias).lower()
        if low in lower_to_original:
            return lower_to_original[low]
    return None


def parse_stress_to_scalar(x):
    if pd.isna(x):
        return np.nan
    try:
        v = float(x)
        if np.isfinite(v):
            return v
    except Exception:
        pass

    s = str(x).strip()
    if s == "" or s.lower() in {"nan", "none", "null"}:
        return np.nan

    try:
        obj = ast.literal_eval(s)
        arr = np.array(obj, dtype=float)
        arr = arr[np.isfinite(arr)]
        if arr.size == 0:
            return np.nan
        return float(np.linalg.norm(arr))
    except Exception:
        pass

    try:
        nums = re.findall(r"[-+]?\d*\.\d+|[-+]?\d+", s)
        arr = np.array([float(v) for v in nums], dtype=float)
        arr = arr[np.isfinite(arr)]
        if arr.size == 0:
            return np.nan
        return float(np.linalg.norm(arr))
    except Exception:
        return np.nan


def clean_values(df: pd.DataFrame, key: str) -> Tuple[pd.Series, Optional[str]]:
    cfg = PROPERTY_PLOT_CONFIG.get(key, {})

    if key == "dielectric_constant":
        lower_to_original = {str(c).strip().lower(): c for c in df.columns}
        comp_cols = []
        for names in (["dielectric_epsx", "epsx"], ["dielectric_epsy", "epsy"], ["dielectric_epsz", "epsz"]):
            found = None
            for name in names:
                if name in df.columns:
                    found = name
                    break
                if name.lower() in lower_to_original:
                    found = lower_to_original[name.lower()]
                    break
            if found is not None:
                comp_cols.append(found)
        if comp_cols:
            vals = pd.DataFrame({c: pd.to_numeric(df[c], errors="coerce") for c in comp_cols}).mean(axis=1, skipna=True)
            vals = pd.to_numeric(vals, errors="coerce")
            vals = vals.replace([np.inf, -np.inf], np.nan).dropna()
            return vals, "/".join(str(c) for c in comp_cols)

    col = find_column(df, aliases_for(key))
    if col is None:
        return pd.Series(dtype=float), None

    if cfg.get("special") == "stress_magnitude":
        vals = df[col].apply(parse_stress_to_scalar)
    else:
        vals = pd.to_numeric(df[col], errors="coerce")
    vals = pd.to_numeric(vals, errors="coerce")
    vals = vals.replace([np.inf, -np.inf], np.nan).dropna()
    return vals, str(col)


def auto_cutoff(vals: pd.Series, tail_quantile: float = 0.995) -> Optional[float]:
    vals = pd.to_numeric(vals, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if len(vals) == 0:
        return None
    q_val = float(vals.quantile(tail_quantile))
    max_val = float(vals.max())
    if not np.isfinite(q_val):
        return None
    return q_val if max_val > q_val else max_val


def format_number(x: Optional[float]) -> str:
    if x is None or not np.isfinite(float(x)):
        return "—"
    x = float(x)
    if abs(x) >= 100:
        return f"{x:.2f}"
    if abs(x) >= 1:
        return f"{x:.3f}"
    return f"{x:.4g}"


def plot_distribution_with_marker(
    vals: pd.Series,
    sample_value: Optional[float],
    key: str,
    out_path: Path,
    bins: int = 42,
    tail_quantile: float = 0.995,
) -> Optional[Dict]:
    vals = pd.to_numeric(vals, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if len(vals) == 0:
        return None

    cfg = PROPERTY_PLOT_CONFIG.get(key, {})
    cutoff = cfg.get("cutoff")
    cutoff = float(cutoff) if cutoff is not None else auto_cutoff(vals, tail_quantile)
    if cutoff is None or not np.isfinite(cutoff):
        return None

    vals_clip = np.minimum(vals.to_numpy(dtype=float), cutoff)
    x_min = float(np.nanmin(vals_clip))
    x_max = float(cutoff)
    if not np.isfinite(x_min) or not np.isfinite(x_max):
        return None
    if x_min == x_max:
        x_min -= 1e-6
        x_max += 1e-6

    bins_arr = np.linspace(x_min, x_max, bins + 1)
    sample = safe_float(sample_value)
    sample_plot = None if sample is None else min(max(float(sample), x_min), x_max)
    percentile = None
    if sample is not None:
        percentile = float((vals <= float(sample)).mean() * 100.0)

    # Industrial grayscale plot style: pure white canvas, pale gray bars,
    # dark graphite candidate marker. This matches the gray industrial UI.
    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "axes.edgecolor": "#c7ccd3",
        "axes.labelcolor": "#2f343b",
        "xtick.color": "#5f6670",
        "ytick.color": "#5f6670",
        "axes.titleweight": "800",
        "axes.linewidth": 0.85,
    })

    fig, ax = plt.subplots(figsize=(7.2, 4.35), facecolor="#f5f6f8")
    ax.set_facecolor("#ffffff")

    counts, bins_o, patches = ax.hist(
        vals_clip,
        bins=bins_arr,
        density=True,
        color="#d9dde3",
        edgecolor="#f7f8fa",
        linewidth=0.65,
        alpha=1.0,
        label="Dataset",
    )

    ax.step(
        bins_o,
        np.r_[counts, counts[-1]],
        where="post",
        color="#5a6069",
        linewidth=1.65,
    )

    y_max = float(np.nanmax(counts)) if len(counts) else 1.0
    if y_max <= 0 or not np.isfinite(y_max):
        y_max = 1.0

    mean_val = float(vals.mean())
    mean_plot = min(max(mean_val, x_min), x_max)
    ax.axvline(
        mean_plot,
        color="#8b949e",
        linestyle=(0, (4, 3)),
        linewidth=1.25,
        label=f"Mean {format_number(mean_val)}",
        zorder=5,
    )

    if float(vals.max()) > cutoff:
        ax.axvline(
            cutoff,
            color="#b7bec8",
            linestyle=(0, (1, 2)),
            linewidth=1.25,
            zorder=4,
        )

    if sample_plot is not None:
        candidate_color = "#20252b"
        ax.axvline(
            sample_plot,
            color=candidate_color,
            linestyle="-",
            linewidth=2.05,
            label="Candidate",
            zorder=8,
        )
        label = "Candidate"
        if percentile is not None:
            label += f"\nP{percentile:.1f}"

        ax.annotate(
            label,
            xy=(sample_plot, y_max * 0.80),
            xytext=(sample_plot, y_max * 1.13),
            ha="center",
            va="bottom",
            fontsize=9,
            fontweight="700",
            color=candidate_color,
            arrowprops=dict(
                arrowstyle="-|>",
                color=candidate_color,
                lw=1.25,
                shrinkA=2,
                shrinkB=2,
                mutation_scale=10,
            ),
            zorder=9,
        )

    title = cfg.get("title", f"{PROPERTY_LABELS.get(key, key)} Distribution")
    xlabel = cfg.get("xlabel", PROPERTY_LABELS.get(key, key))
    unit = PROPERTY_UNITS.get(key, "")
    if unit and unit not in xlabel:
        xlabel = f"{xlabel} ({unit})"

    ax.set_title(title, fontsize=13.5, color="#111827", pad=12)
    ax.set_xlabel(xlabel, fontsize=10.5, labelpad=8)
    ax.set_ylabel("Probability Density", fontsize=10.5, labelpad=8)

    # Industrial instrument-style horizontal grid only.
    ax.grid(axis="y", color="#e3e6ea", linewidth=0.8, alpha=1.0)
    ax.grid(axis="x", visible=False)
    ax.set_axisbelow(True)

    # Keep a closed rectangular plotting area, closer to engineering dashboards.
    for side in ("top", "right", "bottom", "left"):
        ax.spines[side].set_visible(True)
        ax.spines[side].set_color("#cfd5dd")
        ax.spines[side].set_linewidth(0.8)

    legend = ax.legend(
        frameon=True,
        fancybox=False,
        fontsize=9.5,
        loc="upper right",
        borderpad=0.55,
        labelspacing=0.55,
        handlelength=1.9,
    )
    legend.get_frame().set_edgecolor("#d4d9e0")
    legend.get_frame().set_linewidth(0.75)
    legend.get_frame().set_facecolor("#ffffff")
    legend.get_frame().set_alpha(0.92)

    ax.set_ylim(0, y_max * 1.32)
    fig.tight_layout(pad=1.05)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=230, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)

    return {
        "count": int(len(vals)),
        "mean": mean_val,
        "median": float(vals.median()),
        "std": float(vals.std()) if len(vals) > 1 else 0.0,
        "min": float(vals.min()),
        "max": float(vals.max()),
        "plot_cutoff": cutoff,
        "sample": sample,
        "percentile": percentile,
    }


def reset_property_plot_dir() -> None:
    if PROPERTY_PLOT_DIR.exists():
        shutil.rmtree(PROPERTY_PLOT_DIR, ignore_errors=True)
    PROPERTY_PLOT_DIR.mkdir(parents=True, exist_ok=True)


def build_candidate_property_plots(
    candidate_id: str,
    properties: Dict[str, Optional[float]],
    database_csv: Optional[Union[Path, str, Iterable[Union[Path, str]]]] = None,
) -> List[Dict]:
    df = load_distribution_dataframe(database_csv)
    out_dir = PROPERTY_PLOT_DIR / safe_name(candidate_id)
    if out_dir.exists():
        shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    plots: List[Dict] = []
    for spec in PROPERTY_SPECS:
        key = spec["key"]
        label = PROPERTY_LABELS.get(key, key)
        unit = PROPERTY_UNITS.get(key, "")
        vals, source_col = clean_values(df, key)
        sample_value = safe_float(properties.get(key))

        if len(vals) == 0:
            plots.append({
                "key": key,
                "name": label,
                "unit": unit,
                "title": f"{label} 数据集位置图",
                "url": None,
                "note": "暂无可用分布数据",
                "stats": None,
            })
            continue

        outfile = PROPERTY_PLOT_CONFIG.get(key, {}).get("outfile", f"{key}_distribution.png")
        out_path = out_dir / outfile
        stats = plot_distribution_with_marker(vals, sample_value, key, out_path)
        if stats is None:
            plots.append({
                "key": key,
                "name": label,
                "unit": unit,
                "title": f"{label} 数据集位置图",
                "url": None,
                "note": "暂无可用分布数据",
                "stats": None,
            })
            continue

        percentile = stats.get("percentile")
        if percentile is None:
            note = f"数据列：{source_col}；候选值缺失，已展示总体分布。"
        else:
            note = f"数据列：{source_col}；候选值约位于全数据集 P{percentile:.1f}。"
        plots.append({
            "key": key,
            "name": label,
            "unit": unit,
            "title": f"{label} 数据集位置图",
            "url": f"/api/assets/property/{safe_name(candidate_id)}/{outfile}",
            "note": note,
            "stats": stats,
        })

    return plots
