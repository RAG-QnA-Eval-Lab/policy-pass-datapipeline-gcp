#!/usr/bin/env bash
# macOS FAISS + PyTorch OpenMP 충돌 방지 — Python 시작 전에 설정해야 함
export USE_TF=0
export KMP_DUPLICATE_LIB_OK=TRUE
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export MKL_THREADING_LAYER=sequential
export OPENBLAS_NUM_THREADS=1
export VECLIB_MAXIMUM_THREADS=1
export NUMEXPR_NUM_THREADS=1

exec uvicorn src.api.main:app --host 0.0.0.0 --port "${PORT:-8000}" "$@"
