# Whisper

Local speech-to-text dictation for Windows using [faster-whisper](https://github.com/SYSTRAN/faster-whisper). Press **Win+J** to start/stop recording — transcribed text is typed directly into any focused application.

![Python](https://img.shields.io/badge/python-3.10+-blue) ![Windows](https://img.shields.io/badge/platform-Windows-lightgrey)

## Features

- **Real-time streaming** — text appears as you speak, not just after pauses
- **GPU accelerated** — CUDA support for fast transcription (CPU mode also available)
- **Filler word removal** — automatically strips "um", "uh", and other fillers
- **Voice commands** — say "period", "new line", "delete that", etc.
- **Compact overlay UI** — small frameless window that stays on top and fades when idle
- **System tray** — minimize to tray, optional start-minimized mode
- **Customizable themes** — 5 dark themes selectable from the menu
- **Configurable** — model size, device, hotkey, silence detection, and more via `config.py`

## Requirements

- Windows 10/11
- Python 3.10+
- For GPU: NVIDIA GPU with CUDA 12 toolkit installed

## Setup

```bash
pip install -r requirements.txt
python voice_typer.py
```

## Configuration

Edit `config.py` to change:

| Setting | Default | Description |
|---------|---------|-------------|
| `HOTKEY` | `windows+j` | Toggle recording hotkey |
| `MODEL_SIZE` | `small` | Whisper model (`tiny`, `base`, `small`, `medium`, `large-v3`) |
| `DEVICE` | `cpu` | `cuda` for GPU, `cpu` for CPU-only |
| `SILENCE_PAUSE` | `0.7` | Seconds of silence before sending a phrase |

## Building

Run `build.bat` to create a standalone exe with PyInstaller. Output goes to `dist\Whisper\`.
