from pathlib import Path
import os

ROOT_DIR = Path(__file__).resolve().parents[1]
FRONTEND_DIR = ROOT_DIR / "frontend"
RUNTIME_DIR = ROOT_DIR / "runtime"
OUTPUT_DIR = RUNTIME_DIR / "output_structures"
CANDIDATE_VIEW_DIR = RUNTIME_DIR / "candidate_views"
WYCKOFF_VIEW_DIR = RUNTIME_DIR / "wyckoff_views"
PROPERTY_PLOT_DIR = RUNTIME_DIR / "property_plots"

STRESS_DATASET_NAMES = ["mp20_with_jav_epsx_epsy_epsz.csv"]
ABS_STRESS_DATASETS = [
    Path(r"C:\Users\Lenovo\Desktop\1.15任务成果保存\mattergen-main\tego_dielectric_web\mp20_with_jav_dielectric\mp20_with_jav_epsx_epsy_epsz.csv"),
]


def _split_env_paths(text: str):
    out = []
    for part in text.replace(";", ",").split(","):
        part = part.strip().strip('"').strip("'")
        if part:
            out.append(Path(part))
    return out


def _first_existing_path(paths):
    for p in paths:
        try:
            p = Path(p)
            if p.exists() and p.is_file():
                return p
        except Exception:
            pass
    return None


def _find_database_csv() -> Path:
    env = os.getenv("DATABASE_CSV")
    if env:
        p = Path(env)
        if p.exists() and p.is_file():
            return p

    cwd = Path.cwd()
    parent = ROOT_DIR.parent
    grandparent = parent.parent
    candidates = [
        ROOT_DIR / "database_cleaned.csv",
        cwd / "database_cleaned.csv",
        parent / "database_cleaned.csv",
        parent / "website" / "database_cleaned.csv",
        parent / "ripple_next_web" / "database_cleaned.csv",
        parent / "ripple_next_web_v4_property_plots" / "database_cleaned.csv",
        grandparent / "website" / "database_cleaned.csv",
    ]
    found = _first_existing_path(candidates)
    return found if found is not None else ROOT_DIR / "database_cleaned.csv"


def _find_retrieval_csvs():
    env_multi = os.getenv("RETRIEVAL_CSVS")
    if env_multi:
        paths = [p for p in _split_env_paths(env_multi) if p.exists() and p.is_file()]
        if paths:
            return paths

    env_single = os.getenv("DATABASE_CSV")
    if env_single:
        p = Path(env_single)
        if p.exists() and p.is_file():
            return [p]

    candidates = []
    for base in [ROOT_DIR, ROOT_DIR.parent, ROOT_DIR.parent.parent, Path.cwd()]:
        candidates.extend([base / name for name in STRESS_DATASET_NAMES])
    candidates.extend(ABS_STRESS_DATASETS)

    seen = set()
    found = []
    for p in candidates:
        key = str(p).lower()
        if key in seen:
            continue
        seen.add(key)
        if p.exists() and p.is_file():
            found.append(p)

    if found:
        return found

    db = _find_database_csv()
    return [db]


DEFAULT_DATABASE_CSV = ROOT_DIR / "database_cleaned.csv"
DATABASE_CSV = _find_database_csv()
RETRIEVAL_CSVS = _find_retrieval_csvs()

PROPERTY_SPECS = [
    {
        "key": "band_gap",
        "label": "带隙",
        "unit": "eV",
        "default_target": 1.5,
        "default_weight": 1.0,
        "aliases": ["band_gap", "dft_band_gap", "azure_band_gap"],
    },
    {
        "key": "bulk_modulus",
        "label": "体模量",
        "unit": "GPa",
        "default_target": 120.0,
        "default_weight": 1.0,
        "aliases": ["bulk_modulus", "azure_bulk_modulus", "dft_bulk_modulus"],
    },
    {
        "key": "larsen_score_2d",
        "label": "Larsen 二维分数",
        "unit": "",
        "default_target": 0.5,
        "default_weight": 1.0,
        "aliases": ["larsen_score_2d", "larsen_2d", "larsen_score"],
    },
    {
        "key": "dielectric_constant",
        "label": "介电常数",
        "unit": "",
        "default_target": 10.0,
        "default_weight": 1.0,
        "aliases": [
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
    },
    {
        "key": "mag_density",
        "label": "磁密度",
        "unit": "μB/Å³",
        "default_target": 0.20,
        "default_weight": 1.0,
        "aliases": ["mag_density", "dft_mag_density", "magnetic_density"],
    },
    {
        "key": "cauchy_stress",
        "label": "柯西应力",
        "unit": "GPa",
        "default_target": 0.0,
        "default_weight": 1.0,
        "aliases": ["cauchy_stress", "cauchy_pressure", "cauchy", "stress", "pressure", "stress_indicator"],
    },
]

PROPERTY_KEYS = [x["key"] for x in PROPERTY_SPECS]
PROPERTY_LABELS = {x["key"]: x["label"] for x in PROPERTY_SPECS}
PROPERTY_UNITS = {x["key"]: x["unit"] for x in PROPERTY_SPECS}


def ensure_runtime_dirs() -> None:
    for p in (RUNTIME_DIR, OUTPUT_DIR, CANDIDATE_VIEW_DIR, WYCKOFF_VIEW_DIR, PROPERTY_PLOT_DIR):
        p.mkdir(parents=True, exist_ok=True)
