# Chatbots and Human Interaction

An interactive TouchDesigner installation in which two AI bots hold an autonomous conversation, turn their dialogue into kinetic typography and live comic-style images, and pause so a visitor can enter the exchange through speech.

The project uses a hybrid local/cloud architecture:

- **Local:** TouchDesigner, Python coordination, OSC messaging, microphone capture, and speech-to-text
- **Cloud:** `minimax-m3:cloud` language inference and the Stable Diffusion image backend used by the TouchDesigner project
- **Ollama:** local client and request interface for the cloud language model

## Demo and project notes

- [Video demo](https://youtu.be/d2zMN3U40t4)
- [Design process and prototype revision](https://app.notion.com/p/Chatbots-and-Human-Interaction-39be33b0423f8125a509fb43e5786d99?source=copy_link)
- [Original operation notes](https://app.notion.com/p/how-to-start-opration-39be33b0423f80429335e0eec7971967?source=copy_link)

The setup instructions below replace the machine-specific paths in the original operation notes with commands that can be used on another computer.

---

## System overview

```text
Visitor microphone
        |
        v
faster-whisper STT service
        |
        | completed transcript
        v
      Bot A  <--------------------  Bot B
        |                               |
        |                               |
        +----------> TouchDesigner <----+
                       |
                       +--> kinetic typography
                       +--> Stable Diffusion images
                       +--> microphone button states
```

### Conversation flow

1. Bot A and Bot B continue talking without audience input.
2. Both completed responses are sent to TouchDesigner.
3. The same completed response is also sent to the other bot.
4. When a visitor requests to speak, the current exchange is closed on Bot B.
5. The interface turns green when the visitor may press and hold to speak.
6. The completed transcript is sent to Bot A.
7. Bot A answers first, Bot B responds, and the autonomous loop resumes.

Partial speech and partial model output are not sent into the visual system. The project routes complete text messages so typography, image generation, and conversation state remain synchronized.

---

## Repository structure

```text
.
├── audience_ready_with_bots_7_12.toe
├── README.md
└── chatBots/
    ├── README_SIMPLE_LOOP.txt
    ├── botA/
    │   ├── __init__.py
    │   ├── agent.py
    │   ├── bot_a_service.py
    │   ├── osc_bridge.py
    │   └── persona_bot_a.md
    ├── botB/
    │   ├── __init__.py
    │   ├── agent.py
    │   ├── bot_b_service.py
    │   ├── osc_bridge.py
    │   └── persona_bot_b.md
    ├── services/
    │   └── stt_bot_service.py
    └── chatbot_env/
```

Generated `__pycache__/` folders and `.pyc` files are omitted from this diagram.

---

## What each project file does

### Root files

| File | Purpose |
|---|---|
| `audience_ready_with_bots_7_12.toe` | Main TouchDesigner project. It renders the two typography systems, receives bot text and status messages over OSC, controls the visitor microphone interface, and sends prompts to the Stable Diffusion image system. |
| `README.md` | Public project overview, installation instructions, operating sequence, file reference, and troubleshooting guide. |

### `chatBots/`

| File or folder | Purpose |
|---|---|
| `README_SIMPLE_LOOP.txt` | Earlier concise notes describing the direct Bot A/B loop, OSC routing, delays, startup commands, and the localhost proxy fix used by the Ollama clients. |
| `chatbot_env/` | A machine-generated Python virtual environment. It contains installed third-party packages and Windows-specific executables. It is not portable and should be recreated on each computer instead of committed to the repository. |
| `__pycache__/` and `*.pyc` | Python bytecode caches generated automatically while the services run. They are not source files and may be deleted safely. |

### `chatBots/botA/`

| File | Purpose |
|---|---|
| `__init__.py` | Marks `botA` as a Python package so the service can be launched with `python -m botA.bot_a_service`. |
| `agent.py` | Implements `BotAAgent`. It loads Bot A's persona, connects to Ollama at `127.0.0.1:11434`, calls `minimax-m3:cloud`, maintains a bounded conversation history, cleans the model output, and limits response length. |
| `bot_a_service.py` | Bot A's executable entry point and master controller. It defines model, port, timing, history, and initial prompt settings; starts the Bot A OSC bridge; and provides terminal commands such as `start`, `stop`, `reset`, `status`, `user`, and `seed`. |
| `osc_bridge.py` | Coordinates the complete conversation. It receives STT transcripts and Bot B messages, sends Bot A text to TouchDesigner and Bot B, tracks the visible speaker, handles interruption Case 1 and Case 2, cancels stale delayed turns, and resumes the loop after the visitor speaks. |
| `persona_bot_a.md` | System persona for Bot A. It defines an analytical, restrained, archival voice that organizes information, preserves the main idea, and responds in short direct English. |

### `chatBots/botB/`

| File | Purpose |
|---|---|
| `__init__.py` | Marks `botB` as a Python package so the service can be launched with `python -m botB.bot_b_service`. |
| `agent.py` | Implements `BotBAgent`. It loads Bot B's persona, calls the same Ollama model, maintains bounded history, cleans output, and retries when the model returns punctuation-only or incomplete text. |
| `bot_b_service.py` | Bot B's executable entry point. It defines ports, timing, model settings, and diagnostic terminal controls, then starts the Bot B OSC bridge and waits for Bot A's master start command. |
| `osc_bridge.py` | Receives Bot A text, waits for the configured reading/display delay, generates Bot B's response, and routes it to TouchDesigner and normally back to Bot A. During interruption, it sends the final Bot B response only to TouchDesigner and signals when the visitor may speak. |
| `persona_bot_b.md` | System persona for Bot B. It defines a sensory, cinematic, associative voice focused on movement, texture, rhythm, space, and shifts in attention. |

### `chatBots/services/`

| File | Purpose |
|---|---|
| `stt_bot_service.py` | Local microphone and speech-to-text service. It records audio, monitors silence, saves a temporary WAV file, transcribes the completed recording with **faster-whisper**, sends status/results to TouchDesigner, and forwards the completed transcript to Bot A over OSC. |

---

## Speech-to-text model

This project uses **faster-whisper**, a CTranslate2-based implementation of Whisper:

```python
from faster_whisper import WhisperModel
```

The current project uses the **Whisper base** model converted for CTranslate2. The model can be loaded by name:

```python
model = WhisperModel("base")
```

or from a downloaded local model folder.

The current runtime settings are:

```python
DEVICE = "cpu"
COMPUTE_TYPE = "int8"
```

The service sends text only after the visitor releases the button or the silence monitor stops the recording and the full transcription is complete. Partial transcripts are not forwarded to the bots.

---

## Requirements

### Software

- Python 3.11 recommended
- TouchDesigner
- Ollama running locally
- Access to the `minimax-m3:cloud` model through Ollama
- A working microphone
- A configured Stable Diffusion backend inside the TouchDesigner project

### Python packages

Create a fresh `chatbot_env` on each computer instead of reusing a committed virtual-environment folder.

```bash
pip install ollama python-osc numpy sounddevice faster-whisper huggingface_hub
```

`huggingface_hub` is only required when downloading the STT model explicitly into the project folder.

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/proxima-j/chatbots_human_interaction_demo.git
cd chatbots_human_interaction_demo/chatBots
```

### 2. Create `chatbot_env`

Python virtual environments contain machine-specific paths and executables. A `chatbot_env` copied from another computer may not activate correctly, so it should be recreated locally.

If the cloned repository already contains `chatBots/chatbot_env/`, remove that folder before creating a new environment.

#### Windows PowerShell

From the `chatBots` directory:

```powershell
Remove-Item -Recurse -Force .\chatbot_env -ErrorAction SilentlyContinue
py -3.11 -m venv chatbot_env
.\chatbot_env\Scripts\Activate.ps1
```

If PowerShell blocks the activation script, allow it for the current terminal session only:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\chatbot_env\Scripts\Activate.ps1
```

A successful activation places `(chatbot_env)` at the beginning of the terminal prompt.

#### macOS or Linux

```bash
rm -rf chatbot_env
python3.11 -m venv chatbot_env
source chatbot_env/bin/activate
```

To leave the environment later:

```bash
deactivate
```

### 3. Install dependencies inside `chatbot_env`

Confirm that the environment is active, then run:

```bash
python -m pip install --upgrade pip
python -m pip install ollama python-osc numpy sounddevice faster-whisper huggingface_hub
```

Optional verification:

```bash
python -c "import ollama, numpy, sounddevice, faster_whisper; print('Python dependencies are ready.')"
```

### 4. Download and configure the faster-whisper base model

The STT model used by this project is:

```text
Systran/faster-whisper-base
```

It is a CTranslate2 conversion of `openai/whisper-base`.

Two setup methods are available.

#### Option A — automatic download on first run

This is the simplest setup.

Open:

```text
chatBots/services/stt_bot_service.py
```

Replace the machine-specific `MODEL_PATH` value with:

```python
MODEL_PATH = "base"
```

When the STT service starts for the first time, faster-whisper downloads the base model into the local Hugging Face cache. An internet connection is required for the first download.

#### Option B — download the model into the project folder

Use this method when the model should remain in a known local folder or the installation must be prepared for later offline use.

From the `chatBots` directory, run:

```bash
python -c "from huggingface_hub import snapshot_download; snapshot_download(repo_id='Systran/faster-whisper-base', local_dir='stt_models/faster-whisper-base')"
```

The resulting structure should look similar to:

```text
chatBots/
├── services/
│   └── stt_bot_service.py
└── stt_models/
    └── faster-whisper-base/
        ├── config.json
        ├── model.bin
        ├── tokenizer.json
        └── ...
```

For a cross-platform local path, add this import near the top of `stt_bot_service.py`:

```python
from pathlib import Path
```

Then set:

```python
MODEL_PATH = str(
    Path(__file__).resolve().parents[1]
    / "stt_models"
    / "faster-whisper-base"
)
```

This path is resolved from the script location and does not contain another user's Windows account name.

#### Verify the model

With `chatbot_env` active, run:

```bash
python -c "from faster_whisper import WhisperModel; WhisperModel('base', device='cpu', compute_type='int8'); print('faster-whisper base model is ready.')"
```

When Option B is used, verify the downloaded directory instead:

```bash
python -c "from faster_whisper import WhisperModel; WhisperModel('stt_models/faster-whisper-base', device='cpu', compute_type='int8'); print('Local faster-whisper model is ready.')"
```

#### Select the microphone

List available audio devices:

```bash
python services/stt_bot_service.py --list-devices
```

Use the system default microphone:

```python
DEVICE_INDEX = None
```

or set a specific device:

```python
DEVICE_INDEX = 3  # example device index
```

### 5. Confirm Ollama

Start Ollama and confirm that the configured model responds before launching the installation:

```bash
ollama run minimax-m3:cloud
```

Both agents connect through:

```text
http://127.0.0.1:11434
```

The clients use `trust_env=False` so localhost requests are not accidentally routed through `HTTP_PROXY` or `HTTPS_PROXY`.

---

## How to run the installation

Use **three separate terminals**, all opened in the `chatBots` directory.

### Terminal 1 — speech-to-text

Activate `chatbot_env`, then run the STT service.

#### Windows PowerShell

```powershell
.\chatbot_env\Scripts\Activate.ps1
python services/stt_bot_service.py
```

#### macOS or Linux

```bash
source chatbot_env/bin/activate
python services/stt_bot_service.py
```

Wait for:

```text
Loading faster-whisper model...
Model loaded.
Microphone stream started.
```

### Terminal 2 — Bot B

Activate `chatbot_env`, then run:

#### Windows PowerShell

```powershell
.\chatbot_env\Scripts\Activate.ps1
python -m botB.bot_b_service
```

#### macOS or Linux

```bash
source chatbot_env/bin/activate
python -m botB.bot_b_service
```

Bot B should remain waiting for Bot A's master start command.

### Terminal 3 — Bot A

Activate `chatbot_env`, then run:

#### Windows PowerShell

```powershell
.\chatbot_env\Scripts\Activate.ps1
python -m botA.bot_a_service
```

#### macOS or Linux

```bash
source chatbot_env/bin/activate
python -m botA.bot_a_service
```

Do not type `start` yet.

### Open TouchDesigner

1. Open `audience_ready_with_bots_7_12.toe`.
2. Confirm that the OSC inputs and microphone interface are active.
3. Confirm that the Stable Diffusion backend is connected.
4. If the image component opens in a stale state, switch between the available local/cloud backend options and reconnect.
5. Return to the Bot A terminal.

### Start the autonomous conversation

In the Bot A terminal:

```text
start
```

The bots should begin exchanging messages, and TouchDesigner should receive both text and status updates.

### Stop or reset

In the Bot A terminal:

```text
stop
```

Clear both bot histories:

```text
reset
```

Restart with another topic:

```text
seed Write a new starting topic here
```

Simulate a visitor transcript without using the microphone:

```text
user Write a test visitor message here
```

---

## TouchDesigner microphone states

```text
white  = bots are talking
orange = visitor is waiting
green  = visitor may press and hold to speak
```

The first press requests entry into the conversation. When the button turns green, press and hold to record, then release to stop and transcribe.

If the interface becomes stuck and the microphone icon must be returned to idle, run this in the TouchDesigner Textport:

```python
op('/stt_button_system/ui_state').text = 'idle'
```

---

## OSC routing

All services use localhost by default.

| Direction | OSC address | Port |
|---|---|---:|
| TouchDesigner → STT | `/stt/start`, `/stt/stop`, `/stt/cancel`, `/stt/ping` | 9000 |
| STT → TouchDesigner | `/stt/status`, `/stt/result`, `/stt/error`, `/stt/level` | 9001 |
| STT → Bot A | `/user/transcript` | 9100 |
| Bot A → TouchDesigner | `/botA/text`, `/botA/status`, `/botA/error` | 9001 |
| Bot A → Bot B | `/botB/input` | 9200 |
| Bot B → TouchDesigner | `/botB/text`, `/botB/status`, `/botB/error` | 9001 |
| Bot B → Bot A | `/botA/input`, Bot B status/ready messages | 9100 |
| TouchDesigner → Bot A | `/conversation/user_request` | 9100 |

Change the IP addresses and ports in the service files if the components run on different computers.

---

## Main configuration points

### Bot A

Edit `chatBots/botA/bot_a_service.py`:

```python
MODEL_NAME = "minimax-m3:cloud"
MAX_HISTORY_MESSAGES = 10
MAX_REPLY_CHARACTERS = 240
TURN_DELAY_SECONDS = 15.0
```

### Bot B

Edit `chatBots/botB/bot_b_service.py`:

```python
MODEL_NAME = "minimax-m3:cloud"
MAX_HISTORY_MESSAGES = 10
MAX_REPLY_CHARACTERS = 240
TURN_DELAY_SECONDS = 20.0
```

### STT

Edit `chatBots/services/stt_bot_service.py`.

Automatic model download:

```python
MODEL_PATH = "base"
DEVICE_INDEX = None
SAMPLE_RATE = 48000
DEVICE = "cpu"
COMPUTE_TYPE = "int8"
SILENCE_SECONDS = 2.5
MAX_RECORD_SECONDS = 20.0
```

For a model downloaded into `chatBots/stt_models/faster-whisper-base`, use the cross-platform `Path` configuration described in the installation section.


---

## Troubleshooting

### The STT model cannot be found

For automatic download, set:

```python
MODEL_PATH = "base"
```

For a manual local download, confirm that `MODEL_PATH` resolves to the directory containing files such as `model.bin`, `config.json`, and `tokenizer.json`.

Also confirm that `chatbot_env` is active and that `faster-whisper` is installed:

```bash
python -c "import faster_whisper; print('faster-whisper is installed.')"
```

### The wrong microphone is used

List devices:

```bash
python services/stt_bot_service.py --list-devices
```

Copy the correct index into `DEVICE_INDEX`.

### Ollama works in the terminal but Python returns an empty HTTP 502

The agents already use:

```python
Client(
    host="http://127.0.0.1:11434",
    trust_env=False,
)
```

Confirm that Ollama is running on port `11434` and that the service files have not been changed to use a proxy-routed client.

### Bot B is open but the conversation does not start

Bot B waits for Bot A. Start both services, then type:

```text
start
```

in the Bot A terminal.

### TouchDesigner receives no messages

Check that ports `9000`, `9001`, `9100`, and `9200` are not used by another application. Confirm that every service uses the same IP and port configuration.

### The Stable Diffusion image remains frozen

Confirm the image backend is online. Reconnect or switch the backend option inside the TouchDesigner project, then restart the visual stream.

### The microphone button remains in the wrong state

Use the TouchDesigner Textport:

```python
op('/stt_button_system/ui_state').text = 'idle'
```

---

## Repository cleanup before public release

The current repository contains a committed virtual environment and Python cache files. These are machine-specific and make the repository much larger than necessary.

Recommended `.gitignore` entries:

```gitignore
# Python virtual environments
.venv/
venv/
chatbot_env/

# Python cache
__pycache__/
*.py[cod]

# Local model files
stt_models/
models/

# Secrets and local configuration
.env
*.local

# Editor and operating-system files
.vscode/
.DS_Store
Thumbs.db
```

After confirming that dependencies can be installed from the README, remove `chatBots/chatbot_env/` and all `__pycache__/` folders from Git history or from the next clean release.

---

## Notes

- Bot A is the conversation master.
- Bot B should be running before `start` is entered in the Bot A terminal.
- The STT service may be started before or after Bot B, but it must be ready before a visitor speaks.
- The current language model request is non-streaming.
- The STT service uses faster-whisper locally.
- The TouchDesigner project receives completed text messages and owns the public visual presentation.
