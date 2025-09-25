# 🗂️ Autonomous Vault Sorting Agent (LLM + Heuristics)

This toolkit keeps a personal `_Vault` tidy by combining a local large language model with deterministic filesystem tools. The agent watches your inbox, inspects files, and decides where to archive them inside `Documents`, `Projects`, or `Media` without relying on brittle keyword rules.

---

## 🧠 What This Project Does

It turns a messy folder organisatio into a curated vault through a multi-stage routine:

1. **Pre-stage intake** – moves everything from `~/Downloads` and `~/Desktop` into `_Vault/INBOX`, preserving folder trees.
2. **Context snapshots** – builds lightweight directory and file summaries (file counts, extensions, OCR snippets, PDF text extracts).
3. **Decision loop** – streams observations to an HTTP LLM endpoint (default: `http://127.0.0.1:8080/completion`) that replies with JSON actions.
4. **Tool execution** – performs `list_dir`, `inspect_file`, or `plan_move` actions, safely renaming with ASCII rules and creating folders as needed.
5. **Post-run cleanup** – flattens ambiguous owner folders, removes empty directories, and leaves symbolic links in `INBOX/_moved_today` for auditing.

## ⚙️ Technologies & Libraries

* Python 3.10+
* `requests`, `Unidecode`, `pdfminer.six`, `Pillow`, `pytesseract`
* `llama.cpp` (`llama-server`) with a local GGUF model (default: Qwen2.5-32B)
* System tools: `ffmpeg` (for `ffprobe`), `tesseract-ocr`
* Optional shell helpers: `caffeinate` (macOS) to prevent sleep during runs

---

## 🏗️ Agent Pipeline

### Intake & Context Building

* Mirrors configurable taxonomy roots (`Documents`, `Projects`, `Media`).
* Generates bounded snapshots per directory (cap on subdirs/files) for stable LLM prompts.
* Uses OCR/PDF text extraction to enrich metadata before decisions.

### Decision & Execution Loop

* Constructs deterministic system prompts listing allowed destinations (`Documents/*`, `Media/*`, `Projects`).
* Retries bad JSON responses with fallbacks and request timeouts.
* Enforces ASCII-safe filenames, unique targets, and symlink breadcrumbs.

### Cleanup & Logging

* Normalises owner-specific folders using `config/people.local.json`.
* Drops empty directories inside `INBOX` after each run.
* Streams structured events to `logs/YYYY-MM-DD_agent.jsonl` for post-mortems.

## 🧰 Heuristics & Utilities

* Owner detection via configurable name/pattern lists.
* Media heuristics to detect whole TV series folders vs single episodes.
* Graphic asset detection for PNG logos vs photo scans.
* Queue cooldown to avoid thrashing problematic files.
* Environment-driven knobs for max steps, retries, and memory windows.

## 🗄️ Vault Layout

* `_Vault/INBOX` – ingestion queue populated automatically from desktop and downloads.
* `_Vault/Documents/<Category>/<Owner?>` – canonical archive for paperwork with optional owner folders.
* `_Vault/Projects` – catch-all for work-in-progress directories.
* `_Vault/Media/<Bucket>` – media-specific buckets (Movies, Series, Music, Images, Assets by default).

---

## 🚀 Quick Start

### Prerequisites

* macOS or Linux shell environment (tested on macOS Sonoma).
* Python 3.10+ with `pip`.
* `llama-server` from the `llama.cpp` project and a compatible GGUF model (e.g., Qwen2.5-32B-Instruct-Q4_K_M.gguf).
* `ffmpeg` (for `ffprobe`) and `tesseract-ocr` binaries available on `PATH`.

### Installation

```bash
# Clone & enter the project
git clone https://github.com/your-org/agent_runner.git
cd agent_runner

# Create a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install Python dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

### Starting the Stack

Option A – one-shot script (launches llama-server, waits for readiness, runs the agent):

```bash
./run_sort_now.sh
```

Option B – manual steps:

```bash
# 1. Start llama-server in another terminal
llama-server -m /path/to/model/Qwen2.5-32B-Instruct-Q4_K_M.gguf -c 4096 -t 12 -ngl 6 --port 8080

# 2. Export runtime tweaks if desired
export MAX_STEPS=500 MEM_LIMIT=8

# 3. Run the agent (keep parent dir of agent_runner on PYTHONPATH)
python3 -m agent_runner
```

Stop the agent with `Ctrl+C`; cleanup hooks will still prune empty folders and finish logging.

---

## ⚙️ Configuration

* `config/people.local.json` – define known people (`label` + `patterns`) so documents can inherit owners.
* `config/taxonomy.local.json` – customise allowed categories under Documents/Media for LLM guidance.
* Environment variables (`LLM_URL`, `MAX_STEPS`, `MEM_LIMIT`, `INSPECT_CAP_PER_FILE`, etc.) override defaults from `config.py`.
* Set `DRY_RUN=1` to simulate decisions without moving files.

---

## 🧠 Skills Demonstrated

* Tool-augmented LLM orchestration with strict JSON contracts.
* Filesystem safety: collision-free moves, ASCII sanitisation, audit symlinks.
* Lightweight perception of heterogeneous files (OCR, PDF parsing, media metadata).
* Configurable heuristics that blend deterministic rules with LLM reasoning.

## 🗺️ Operational Notes

* Daily runs append to `logs/YYYY-MM-DD_agent.jsonl`; rotate or archive as needed.
* `_Vault/INBOX/_moved_today` contains symlinks to freshly sorted items for quick human review.
* To rerun the LLM on a single stubborn file, delete its symlink and re-drop it into INBOX.

---

## 🙋‍♂️ Author

👋 Hi! I'm a Ludovic Malot, a French engineer focused on AI/ML and cybersecurity applications. This project was a hands-on experiment to blend classic deep learning with reinforcement learning in a real-world industrial setting.

Feel free to connect with me on [LinkedIn](https://www.linkedin.com/in/ludovic-malot/) or drop a ⭐ if this repo helped you!
