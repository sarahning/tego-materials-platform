#!/usr/bin/env python3
"""Unified inference wrapper for CHGNet + ALIGNN property predictors.

Predicted properties
--------------------
1. CHGNet site-wise magnetic-moment magnitudes and local absolute magnetic
   moment density, in mu_B/Angstrom^3.
2. ALIGNN MBJ band gap, in eV.
3. ALIGNN DFPT maximum static dielectric constant (electronic + ionic).

Important magnetic-property note
--------------------------------
CHGNet's pretrained magnetic head applies an absolute value to site moments.
Therefore ``sum(site_moments) / volume`` is a LOCAL ABSOLUTE magnetic-moment
 density, not a signed/net ferri-/antiferromagnetic moment density.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass
from typing import Any

# Ensure DGL chooses the PyTorch backend before DGL/ALIGNN is imported.
os.environ.setdefault("DGLBACKEND", "pytorch")


CHGNET_MODEL_NAME = "0.3.0"
ALIGNN_MBJ_MODEL_NAME = "jv_mbj_bandgap_alignn"
ALIGNN_DFPT_MODEL_NAME = "jv_dfpt_piezo_max_dielectric_alignn"


def _load_alignn_model_windows_safe(alignn_pretrained, model_name: str):
    """Load an ALIGNN model while working around its Windows temp-file bug.

    ALIGNN's current ``get_figshare_model`` uses ``tempfile.mkstemp()``,
    reopens the path, and then deletes it without closing the descriptor
    returned by ``mkstemp``. Windows refuses to delete that open file.
    This temporary wrapper closes only that descriptor and restores the
    original function immediately after model loading.
    """
    if os.name != "nt":
        return alignn_pretrained.get_figshare_model(model_name)

    original_mkstemp = alignn_pretrained.tempfile.mkstemp

    def mkstemp_with_closed_descriptor(*args, **kwargs):
        file_descriptor, filename = original_mkstemp(*args, **kwargs)
        os.close(file_descriptor)
        return file_descriptor, filename

    alignn_pretrained.tempfile.mkstemp = mkstemp_with_closed_descriptor
    try:
        return alignn_pretrained.get_figshare_model(model_name)
    finally:
        alignn_pretrained.tempfile.mkstemp = original_mkstemp


@dataclass
class PredictionResult:
    """Serializable prediction result for one ordered periodic structure."""

    formula: str
    n_sites: int
    volume_A3: float

    chgnet_site_magmoms_muB: list[float]
    chgnet_local_abs_moment_muB: float
    chgnet_local_abs_mag_density_muB_A3: float
    chgnet_mean_site_magmom_muB: float
    chgnet_max_site_magmom_muB: float

    alignn_mbj_band_gap_raw_eV: float
    alignn_mbj_band_gap_eV: float
    alignn_dfpt_max_static_dielectric_raw: float
    alignn_dfpt_max_static_dielectric: float

    chgnet_model: str
    alignn_bandgap_model: str
    alignn_dielectric_model: str
    device: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


class MaterialPropertyPredictor:
    """Load all three pretrained models once and reuse them for inference."""

    def __init__(
        self,
        *,
        device: str = "auto",
        chgnet_model_name: str = CHGNET_MODEL_NAME,
        alignn_bandgap_model_name: str = ALIGNN_MBJ_MODEL_NAME,
        alignn_dielectric_model_name: str = ALIGNN_DFPT_MODEL_NAME,
        alignn_cutoff: float = 8.0,
        alignn_max_neighbors: int = 12,
        verbose: bool = True,
    ) -> None:
        # Heavy imports are intentionally delayed until object creation. This
        # lets CLI --help and schema inspection work before ML dependencies are installed.
        import numpy as np
        import torch
        from alignn import pretrained as alignn_pretrained
        from alignn.graphs import Graph
        from chgnet.model.model import CHGNet
        from chgnet.graph.converter import CrystalGraphConverter
        from jarvis.core.atoms import pmg_to_atoms
        from pymatgen.core import Structure

        self.np = np
        self.torch = torch
        self.Graph = Graph
        self.pmg_to_atoms = pmg_to_atoms
        self.Structure = Structure
        self.verbose = verbose
        self.alignn_cutoff = float(alignn_cutoff)
        self.alignn_max_neighbors = int(alignn_max_neighbors)
        self.chgnet_model_name = chgnet_model_name
        self.alignn_bandgap_model_name = alignn_bandgap_model_name
        self.alignn_dielectric_model_name = alignn_dielectric_model_name
        self.device = self._resolve_device(device)
        self.torch_device = torch.device(self.device)
        self._inference_lock = threading.Lock()

        if verbose:
            print(f"[MODEL] Device: {self.device}")
            print(f"[MODEL] Loading CHGNet {chgnet_model_name} ...")

        # CHGNet ships its pretrained checkpoint with the package.
        self.chgnet = CHGNet.load(
            model_name=chgnet_model_name,
            use_device=self.device,
            verbose=verbose,
        )

        # On Windows, CHGNet 0.3.x's compiled ``fast`` graph builder may
        # disagree with pymatgen/NumPy integer widths (C ``long`` is 32-bit
        # on Windows, while the neighbor list is int64).  The official
        # converter also provides a pure-Python ``legacy`` implementation,
        # which produces the same graph semantics without calling cygraph.
        # It is slightly slower, but is reliable for interactive CPU use.
        if os.name == "nt":
            old_converter = self.chgnet.graph_converter
            self.chgnet.graph_converter = CrystalGraphConverter(
                atom_graph_cutoff=float(old_converter.atom_graph_cutoff),
                bond_graph_cutoff=float(old_converter.bond_graph_cutoff),
                algorithm="legacy",
                on_isolated_atoms=getattr(
                    old_converter, "on_isolated_atoms", "error"
                ),
                verbose=verbose,
            )
            if verbose:
                print(
                    "[MODEL] Windows detected: CHGNet graph converter "
                    "switched to legacy mode."
                )

        self.chgnet.eval()

        # ALIGNN's official loader uses the module-level `device` variable.
        # Set it explicitly before loading so both models go to the requested device.
        alignn_pretrained.device = self.torch_device

        if verbose:
            print(f"[MODEL] Loading ALIGNN MBJ model: {alignn_bandgap_model_name}")
        self.alignn_bandgap = _load_alignn_model_windows_safe(
            alignn_pretrained, alignn_bandgap_model_name
        )
        self.alignn_bandgap.eval()

        if verbose:
            print(
                "[MODEL] Loading ALIGNN DFPT dielectric model: "
                f"{alignn_dielectric_model_name}"
            )
        self.alignn_dielectric = _load_alignn_model_windows_safe(
            alignn_pretrained, alignn_dielectric_model_name
        )
        self.alignn_dielectric.eval()

        if verbose:
            print("[MODEL] All models loaded successfully.")

    def _resolve_device(self, requested: str) -> str:
        requested = str(requested).strip().lower()
        if requested == "auto":
            if self.torch.cuda.is_available():
                return "cuda"
            # CHGNet supports MPS, but DGL/ALIGNN generally should stay on CPU
            # on macOS. Keep a shared CPU device for reliable joint inference.
            return "cpu"
        if requested == "cuda":
            if not self.torch.cuda.is_available():
                raise RuntimeError(
                    "--device cuda was requested, but torch.cuda.is_available() is False."
                )
            return "cuda"
        if requested == "cpu":
            return "cpu"
        raise ValueError("device must be one of: auto, cpu, cuda")

    def structure_from_cif_text(self, cif_text: str):
        if not isinstance(cif_text, str) or not cif_text.strip():
            raise ValueError("CIF text is empty or is not a string.")
        structure = self.Structure.from_str(cif_text, fmt="cif")
        if len(structure) == 0:
            raise ValueError("The CIF was parsed but contains no atomic sites.")
        if not structure.is_ordered:
            raise ValueError(
                "The structure contains partial/disordered occupancies. "
                "These pretrained graph models require an ordered structure."
            )
        if float(structure.volume) <= 0:
            raise ValueError("The parsed structure has a non-positive cell volume.")
        return structure

    def structure_from_file(self, path: str):
        structure = self.Structure.from_file(path)
        if not structure.is_ordered:
            raise ValueError(
                "The structure contains partial/disordered occupancies. "
                "These pretrained graph models require an ordered structure."
            )
        return structure

    def _build_alignn_graph(self, structure):
        atoms = self.pmg_to_atoms(structure)
        graph, line_graph = self.Graph.atom_dgl_multigraph(
            atoms,
            cutoff=self.alignn_cutoff,
            max_neighbors=self.alignn_max_neighbors,
        )
        # Match the official ALIGNN pretrained.py path.
        lattice = self.torch.tensor(atoms.lattice_mat)
        return (
            graph.to(self.torch_device),
            line_graph.to(self.torch_device),
            lattice.to(self.torch_device),
        )

    def _predict_alignn_scalar(self, model, graph, line_graph, lattice) -> float:
        with self.torch.no_grad():
            output = model([graph, line_graph, lattice])
        # Current ALIGNN may return either a tensor or {"out": tensor}.
        if isinstance(output, dict):
            if "out" not in output:
                raise RuntimeError(
                    f"ALIGNN returned a dict without an 'out' key: {list(output)}"
                )
            output = output["out"]
        values = self.np.asarray(output.detach().cpu().numpy()).reshape(-1)
        if values.size != 1:
            raise RuntimeError(
                f"Expected one scalar from ALIGNN, received shape {tuple(values.shape)}."
            )
        value = float(values[0])
        if not self.np.isfinite(value):
            raise RuntimeError(f"ALIGNN returned a non-finite prediction: {value}")
        return value

    def predict_structure(self, structure) -> PredictionResult:
        """Predict all requested properties for a pymatgen Structure."""
        if not structure.is_ordered:
            raise ValueError("Only ordered structures are supported.")

        # A lock makes this safe for a simple multi-threaded FastAPI deployment.
        # For high throughput, run one worker process per GPU instead of many threads.
        with self._inference_lock:
            volume = float(structure.volume)

            # task='em' computes energy and magnetic moments, while avoiding force/stress.
            chg_prediction = self.chgnet.predict_structure(structure, task="em")
            site_magmoms = self.np.asarray(chg_prediction["m"], dtype=float).reshape(-1)
            if site_magmoms.size != len(structure):
                raise RuntimeError(
                    "CHGNet site-moment count does not match structure site count: "
                    f"{site_magmoms.size} vs {len(structure)}"
                )
            if not self.np.all(self.np.isfinite(site_magmoms)):
                raise RuntimeError("CHGNet returned non-finite site magnetic moments.")

            # CHGNet's magnetic head returns magnitudes (absolute values).
            local_abs_moment = float(self.np.abs(site_magmoms).sum())
            local_abs_density = local_abs_moment / volume

            # Build the ALIGNN graph only once and reuse it for both models.
            graph, line_graph, lattice = self._build_alignn_graph(structure)
            band_gap_raw = self._predict_alignn_scalar(
                self.alignn_bandgap, graph, line_graph, lattice
            )
            dielectric_raw = self._predict_alignn_scalar(
                self.alignn_dielectric, graph, line_graph, lattice
            )

            # Preserve raw regression outputs while also providing physically clipped values.
            band_gap_clipped = max(0.0, band_gap_raw)
            dielectric_clipped = max(0.0, dielectric_raw)

            return PredictionResult(
                formula=structure.composition.reduced_formula,
                n_sites=len(structure),
                volume_A3=volume,
                chgnet_site_magmoms_muB=[float(x) for x in site_magmoms],
                chgnet_local_abs_moment_muB=local_abs_moment,
                chgnet_local_abs_mag_density_muB_A3=float(local_abs_density),
                chgnet_mean_site_magmom_muB=float(site_magmoms.mean()),
                chgnet_max_site_magmom_muB=float(site_magmoms.max()),
                alignn_mbj_band_gap_raw_eV=band_gap_raw,
                alignn_mbj_band_gap_eV=band_gap_clipped,
                alignn_dfpt_max_static_dielectric_raw=dielectric_raw,
                alignn_dfpt_max_static_dielectric=dielectric_clipped,
                chgnet_model=chgnet_model_label(self.chgnet_model_name),
                alignn_bandgap_model=self.alignn_bandgap_model_name,
                alignn_dielectric_model=self.alignn_dielectric_model_name,
                device=self.device,
            )

    def predict_cif_text(self, cif_text: str) -> PredictionResult:
        return self.predict_structure(self.structure_from_cif_text(cif_text))

    def predict_file(self, path: str) -> PredictionResult:
        return self.predict_structure(self.structure_from_file(path))


def chgnet_model_label(model_name: str) -> str:
    return f"CHGNet-{model_name}"
