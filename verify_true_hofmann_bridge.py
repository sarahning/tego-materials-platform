from pathlib import Path
import shutil

from pymatgen.core import Lattice, Structure

from backend.rendering import render_three_views, renderer_status


def main() -> None:
    status = renderer_status()
    print("[STATUS]", status)
    if not status.get("available"):
        raise SystemExit(
            "The true Hofmann renderer is unavailable. Start the application "
            "with run_windows_cpu_true_hofmann.ps1."
        )

    structure = Structure(
        Lattice.cubic(5.43),
        ["Si"] * 8,
        [
            [0.0, 0.0, 0.0],
            [0.5, 0.5, 0.0],
            [0.5, 0.0, 0.5],
            [0.0, 0.5, 0.5],
            [0.25, 0.25, 0.25],
            [0.75, 0.75, 0.25],
            [0.75, 0.25, 0.75],
            [0.25, 0.75, 0.75],
        ],
    )

    output_dir = Path(__file__).resolve().parent / "runtime" / "true_hofmann_test"
    shutil.rmtree(output_dir, ignore_errors=True)
    paths = render_three_views(structure, output_dir, "silicon", zoom=1.20)

    for path in paths:
        print(f"[IMAGE] {path} bytes={path.stat().st_size}")
    print("[OK] True Hofmann bridge produced all three images.")


if __name__ == "__main__":
    main()
