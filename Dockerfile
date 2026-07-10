FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    MPLBACKEND=Agg \
    MPLCONFIGDIR=/tmp/matplotlib \
    DGLBACKEND=pytorch \
    TEGO_PROPERTY_DEVICE=cpu \
    RETRIEVAL_CSVS=/app/mp20_with_jav_dielectric/mp20_with_jav_epsx_epsy_epsz.csv \
    OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MALLOC_ARENA_MAX=2

WORKDIR /app

# Runtime libraries used by scientific Python, DGL and Matplotlib/Hofmann.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
        libgl1 \
        libglib2.0-0 \
        fontconfig \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --upgrade pip setuptools wheel

# Keep the CPU-only Torch build. Installing it first prevents another package
# from selecting a CUDA wheel during dependency resolution.
RUN python -m pip install \
      torch==2.2.1 \
      --index-url https://download.pytorch.org/whl/cpu

COPY requirements-render.txt /app/requirements-render.txt
RUN python -m pip install -r /app/requirements-render.txt

COPY . /app
RUN mkdir -p /app/runtime /tmp/matplotlib

# Fail the image build early if the scientific stack is incompatible.
RUN python -c "import torch, dgl, chgnet, alignn, pymatgen; from hofmann import StructureScene, BondSpec; print('Render dependency check OK', torch.__version__, dgl.__version__)"

# Cache the two ALIGNN checkpoints inside the image. This makes the first
# public prediction much faster and avoids downloading weights after restart.
RUN python download_property_models.py

EXPOSE 10000

CMD ["sh", "-c", "python -m uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-10000} --workers 1"]
