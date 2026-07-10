import shutil
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

from pymatgen.core import Structure
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

from .config import WYCKOFF_VIEW_DIR
from .rendering import render_three_views


def _dataset_get(dataset, key):
    try:
        return dataset[key]
    except Exception:
        return getattr(dataset, key)


def clear_wyckoff_views() -> None:
    if WYCKOFF_VIEW_DIR.exists():
        shutil.rmtree(WYCKOFF_VIEW_DIR, ignore_errors=True)
    WYCKOFF_VIEW_DIR.mkdir(parents=True, exist_ok=True)


def extract_wyckoff_groups(structure: Structure) -> List[Dict]:
    sga = SpacegroupAnalyzer(structure, symprec=1e-2, angle_tolerance=5)
    dataset = sga.get_symmetry_dataset()
    wyckoffs = _dataset_get(dataset, "wyckoffs")
    equiv_atoms = _dataset_get(dataset, "equivalent_atoms")

    groups = defaultdict(list)
    for i, site in enumerate(structure):
        elem = site.specie.symbol
        wy = str(wyckoffs[i])
        eq = int(equiv_atoms[i])
        groups[(elem, wy, eq)].append(i)

    rows = []
    for gid, ((elem, wy, eq), indices) in enumerate(groups.items(), start=1):
        rep = structure[indices[0]].frac_coords
        rows.append(
            {
                "gid": gid,
                "element": elem,
                "wyckoff": wy,
                "multiplicity": len(indices),
                "indices": [int(i) for i in indices],
                "representative_frac": [float(rep[0]), float(rep[1]), float(rep[2])],
            }
        )

    rows.sort(key=lambda x: (x["element"], x["wyckoff"], x["multiplicity"], x["indices"][0]))
    for i, row in enumerate(rows, start=1):
        row["gid"] = i
    return rows


def substructure_from_indices(structure: Structure, indices: List[int]) -> Structure:
    species = [structure[i].specie for i in indices]
    coords = [structure[i].frac_coords for i in indices]
    return Structure(structure.lattice, species, coords, coords_are_cartesian=False)


def analyze_wyckoff_with_images(structure: Structure) -> Dict:
    clear_wyckoff_views()
    session_dir = WYCKOFF_VIEW_DIR / "current"
    session_dir.mkdir(parents=True, exist_ok=True)

    full_paths = render_three_views(structure, session_dir, "full_structure", zoom=1.20)
    groups = extract_wyckoff_groups(structure)
    for g in groups:
        sub = substructure_from_indices(structure, g["indices"])
        prefix = f"group_{g['gid']:02d}_{g['element']}_{g['multiplicity']}{g['wyckoff']}"
        g_paths = render_three_views(sub, session_dir, prefix, zoom=1.30)
        g["image_files"] = [p.name for p in g_paths]

    return {
        "full_image_files": [p.name for p in full_paths],
        "groups": groups,
    }
