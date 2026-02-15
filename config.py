# ─── Whisper Configuration ────────────────────────────────────────────────────

# Hotkey to toggle recording on/off (press once to start, again to stop)
# Win+J is free on Windows 10. Other free options: Win+Y, Win+`
HOTKEY = "windows+j"

# Whisper model size: tiny, base, small, medium, large-v3
# With a 4080 Super you can comfortably run large-v3 for best accuracy
MODEL_SIZE = "small"

# Device: "cuda" for GPU, "cpu" for CPU-only
# (requires CUDA 12 toolkit for GPU — use "cpu" if you get cublas errors)
DEVICE = "cuda"

# Compute type: "float16" for GPU (fast), "int8" for CPU (lighter)
COMPUTE_TYPE = "float16"

# Language: "en" for English, or None for auto-detect (slightly slower)
LANGUAGE = "en"

# ─── Silence Detection ──────────────────────────────────────────────────────

# How long a pause (in seconds) before a phrase is sent for transcription.
# Lower = more responsive but may cut mid-thought. Higher = waits longer.
SILENCE_PAUSE = 0.7

# Multiplier for ambient noise level to set the silence threshold.
# Higher = less sensitive (needs louder speech). Lower = more sensitive.
SILENCE_MULTIPLIER = 3.0

# ─── Audio ───────────────────────────────────────────────────────────────────

# Sample rate in Hz (16000 is what Whisper expects, don't change this)
SAMPLE_RATE = 16000

# Audio input device index. Set to None to use system default microphone.
# Run `python -m sounddevice` to list available devices and their indices.
INPUT_DEVICE = None

# ─── Voice Commands ──────────────────────────────────────────────────────────
# Say these words/phrases and they'll be replaced with the corresponding text.
# Matching is case-insensitive. Checked in order, so longer phrases first.
VOICE_COMMANDS = {
    # Punctuation
    "period": ".",
    "full stop": ".",
    "comma": ",",
    "question mark": "?",
    "exclamation mark": "!",
    "exclamation point": "!",
    "colon": ":",
    "semicolon": ";",
    "dash": " — ",
    "hyphen": "-",
    "ellipsis": "...",
    "dot dot dot": "...",
    "open quote": '"',
    "close quote": '"',
    "open paren": "(",
    "close paren": ")",
    "open bracket": "[",
    "close bracket": "]",

    # Whitespace / formatting
    "new line": "\n",
    "newline": "\n",
    "new paragraph": "\n\n",
    "tab key": "\t",

    # Editing commands (these return special action strings)
    "backspace": "\x08",       # handled specially in voice_typer.py
    "delete that": "\x7f",     # handled specially — deletes last phrase
    "undo that": "\x1a",       # handled specially — Ctrl+Z
    "select all": "\x01",      # handled specially — Ctrl+A
}

# Enable auto-capitalization after sentence-ending punctuation
AUTO_CAPITALIZE = True

# Enable system tray icon (requires pystray and Pillow)
ENABLE_TRAY_ICON = True
