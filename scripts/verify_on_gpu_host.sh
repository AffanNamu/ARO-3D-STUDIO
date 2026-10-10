#!/usr/bin/env bash
# Phase 2 on a GPU host: set up TripoSR, pin + verify the weights, run the real-model tests and record evidence.
#
#   CONCEPT_IMAGE=/path/concept.png scripts/verify_on_gpu_host.sh        # or TITAN_RENDER=1 to use a render of the procedural asset as INPUT
#
# Needs: NVIDIA GPU + driver, Python 3.11+, git, outbound HTTPS to huggingface.co / github.com / pypi.org.
# Costs nothing but your own GPU time. It never uses a paid API. It stops at the first failing step.
# Pinning (step 3) edits aro_studio/engines/locks/triposr.json: REVIEW AND COMMIT THAT DIFF - the script will not commit it.
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=${OUT:-docs/acceptance/evidence/ai}
PY=${PY:-python3}
TRIPOSR_DIR=${TRIPOSR_DIR:-$HOME/TripoSR}
TRIPOSR_REF=$(python3 -c "import json;print(json.load(open('aro_studio/engines/locks/triposr.json'))['code']['commit'])")
BY=${PINNED_BY:-$(git config user.email || echo unknown)}
mkdir -p "$OUT"; exec > >(tee "$OUT/verify_on_gpu_host.log") 2>&1

echo "== 1. GPU"; nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv || { echo "BLOCKED: no NVIDIA GPU"; exit 3; }
echo "== 2. environment"
$PY -m venv .venv-gpu && . .venv-gpu/bin/activate
pip install -q -U pip && pip install -q -r requirements.txt
pip install -q "torch>=2.6.0" torchvision --index-url "${TORCH_INDEX:-https://download.pytorch.org/whl/cu121}"
[ -d "$TRIPOSR_DIR" ] || git clone https://github.com/VAST-AI-Research/TripoSR "$TRIPOSR_DIR"
git -C "$TRIPOSR_DIR" checkout "$TRIPOSR_REF"
pip install -q -r requirements-triposr.txt
export PYTHONPATH="$TRIPOSR_DIR${PYTHONPATH:+:$PYTHONPATH}"
python -c "import torch,tsr;print('torch',torch.__version__,'cuda',torch.cuda.is_available())"
echo "== 3. pin weights (writes aro_studio/engines/locks/triposr.json if still null)"
if python -c "from aro_studio.engines.weights import load_lock;import sys;sys.exit(1 if load_lock('triposr').missing() else 0)"; then
  echo "lock already complete"
else
  python scripts/pin_triposr_weights.py --by "$BY"
  echo ">>> REVIEW: git diff aro_studio/engines/locks/triposr.json  and commit it."
fi
echo "== 4. verify weights against the lock"
python scripts/verify_triposr_weights.py
echo "== 5. real-model tests (pytest -m model)"
set +e
ARO_RUN_MODEL_TESTS=1 python -m pytest -m model -v -rs tests/test_triposr_real.py --junitxml="$OUT/model-tests-junit.xml" 2>&1 | tee "$OUT/model-tests.txt"
echo "pytest exit: ${PIPESTATUS[0]}" | tee -a "$OUT/model-tests.txt"
set -e
echo "== 6. record inference evidence (hardware, VRAM, timings, renders, pipeline, export)"
if [ -n "${CONCEPT_IMAGE:-}" ]; then python scripts/record_real_inference.py --image "$CONCEPT_IMAGE" --out "$OUT" "$@"
elif [ "${TITAN_RENDER:-0}" = 1 ]; then python scripts/record_real_inference.py --titan-render --out "$OUT" "$@"
else echo "set CONCEPT_IMAGE=... or TITAN_RENDER=1"; exit 2; fi
echo "Done. Review $OUT/inference-evidence.json; check raw-views/ and final-views/ by eye; commit the evidence."
