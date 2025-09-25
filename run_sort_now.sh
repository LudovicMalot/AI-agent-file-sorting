#!/bin/zsh
set -euo pipefail

# --- Local configuration (override as needed) ---
: ${MODEL_DIR:="$HOME/models/qwen2.5-32b"}
: ${MODEL_NAME:="Qwen2.5-32B-Instruct-Q4_K_M.gguf"}
: ${LLAMA_PORT:=8080}
: ${LLM_URL:="http://127.0.0.1:${LLAMA_PORT}/completion"}

# Optional heuristics exported to the Python process
export LLM_URL               # consumed by agent_runner.config
export MAX_STEPS=${MAX_STEPS:-500}
export MEM_LIMIT=${MEM_LIMIT:-8}
export INSPECT_CAP_PER_FILE=${INSPECT_CAP_PER_FILE:-2}
export DIR_LIST_CAP_PER_DIR=${DIR_LIST_CAP_PER_DIR:-1}
export YEAR_DIR_REGEX=${YEAR_DIR_REGEX:-'^(19|20)\d{2}$'}
export MIN_SAME_EXT=${MIN_SAME_EXT:-4}
export MIN_SUBTREE_FILES=${MIN_SUBTREE_FILES:-6}

# --- Model availability check ---
MODEL_FILE="${MODEL_DIR}/${MODEL_NAME}"
if [[ ! -f "$MODEL_FILE" ]]; then
  echo "ERROR: model not found: $MODEL_FILE"
  echo "Download with:"
  echo "  hf download bartowski/Qwen2.5-32B-Instruct-GGUF --include \"$MODEL_NAME\" --local-dir \"$MODEL_DIR\""
  exit 1
fi

# --- Start server ---
# Stop any lingering server bound to the port
if lsof -iTCP:${LLAMA_PORT} -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port :${LLAMA_PORT} already in use. Stopping old llama-server..."
  # Try to identify the matching process if possible
  OLD_PIDS=$(pgrep -f "llama-server.*-m .*${MODEL_NAME}" || true)
  if [[ -n "${OLD_PIDS}" ]]; then
    kill ${OLD_PIDS} 2>/dev/null || true
    sleep 1
  fi
fi

echo "Starting llama-server..."
# --- Server parameters ---
: ${PORT:=8080}
: ${CTX:=15000}        
: ${NGL:=999}        # maximum layers offloaded to GPU (Metal)
: ${UB:=1024}        # micro-batch size
: ${THREADS:=10}     # 8–10 is a good default on M2 Max

echo "Starting llama-server on port ${PORT} with ctx=${CTX}, ngl=${NGL}, ub=${UB}, t=${THREADS}"
nohup llama-server \
  -m "${MODEL_FILE}" \
  -c ${CTX} \
  -ngl ${NGL} \
  -ub ${UB} \
  -t ${THREADS} \
  --port ${PORT} \
  --parallel 2 \
  --cont-batching \
  > /tmp/llama.out 2>&1 &
echo $! > /tmp/llama.pid
echo "llama-server PID: $(cat /tmp/llama.pid)"

LLAMA_PID=$!
echo "llama-server PID: $LLAMA_PID"

cleanup() {
  echo "Stopping llama-server (PID $LLAMA_PID)..."
  kill "$LLAMA_PID" 2>/dev/null || true
  wait "$LLAMA_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# --- Wait for the port to open ---
echo "Waiting for llama-server on :${LLAMA_PORT} ..."
for i in {1..120}; do
  if lsof -iTCP:${LLAMA_PORT} -sTCP:LISTEN >/dev/null 2>&1; then
    break
  fi
  sleep 1
  [[ $i -eq 120 ]] && { echo "Server never opened :${LLAMA_PORT}. Check /tmp/llama.out"; exit 2; }
done

# --- Wait for the model to finish loading (HTTP 200) ---
echo "Waiting for model to finish loading ..."
for i in {1..600}; do
  code=$(curl -s -o /dev/null -w "%{http_code}" \
            -X POST "http://127.0.0.1:${LLAMA_PORT}/completion" \
            -H 'Content-Type: application/json' \
            -d '{"prompt":"ping","n_predict":4,"temperature":0.1,"stream":false}' || true)
  if [[ "$code" == "200" ]]; then
    echo "llama-server ready."
    break
  fi
  sleep 1
  [[ $i -eq 600 ]] && { echo "Model did not become ready. Check /tmp/llama.out"; exit 3; }
done

# --- Smoke test ---
curl -sSf -X POST "http://127.0.0.1:${LLAMA_PORT}/completion" \
     -H 'Content-Type: application/json' \
     -d '{"prompt":"ping","n_predict":8,"temperature":0.1,"stream":false}' >/dev/null
echo "llama-server responding OK."

# --- Launch the agent package ---
# Ensure the parent directory of agent_runner is on PYTHONPATH if needed:
# export PYTHONPATH="$HOME/bin:${PYTHONPATH:-}"
echo "Running vault_agent..."
caffeinate -s python3 -m agent_runner

echo "Done."
