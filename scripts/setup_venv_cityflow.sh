#!/usr/bin/env bash
set -euo pipefail

# Create a fresh Python virtualenv at repo root named venv-cityflow and install API requirements.

if [ -d "venv-cityflow" ]; then
  echo "venv-cityflow already exists at $(pwd)/venv-cityflow"
  echo "If you want a clean env, remove it first: rm -rf venv-cityflow"
  exit 0
fi

python3 -m venv venv-cityflow
source venv-cityflow/bin/activate
python -m pip install --upgrade pip
if [ -f requirements.txt ]; then
  pip install -r requirements.txt
elif [ -f api/requirements.txt ]; then
  pip install -r api/requirements.txt
else
  echo "WARN: requirements.txt not found; install dependencies manually."
fi

echo
echo "Done. Activate with:"
echo "  source venv-cityflow/bin/activate"
echo "Run API locally with:"
echo "  uvicorn api.main:app --reload"
