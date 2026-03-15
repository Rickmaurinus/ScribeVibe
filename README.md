# ScribeVibe

GPU-accelerated push-to-talk transcription for Windows. Press a hotkey, speak, press again — your words appear at the cursor. Powered by [faster-whisper](https://github.com/SYSTRAN/faster-whisper) on NVIDIA CUDA.

## Features

- **Push-to-talk transcription** — F13 for English, F14 for Dutch (configurable)
- **Instant paste** — transcribed text is pasted directly at your cursor via clipboard
- **System tray controls** — switch models, microphones, and view history without leaving your workflow
- **Model hot-swapping** — change Whisper models on the fly; VRAM is managed automatically
- **Transcription history** — searchable, scrollable history window with copy buttons and live updates
- **Audio feedback** — distinct sounds for start, stop, and completion so you never have to look at the screen

## Requirements

- **Windows 10/11**
- **NVIDIA GPU** with CUDA support
- **Python 3.10+**

## Installation

```bash
git clone https://github.com/youruser/ScribeVibe.git
cd ScribeVibe
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

## Usage

```bash
python main.py
```

A green microphone icon appears in the system tray. The default English model loads and a CUDA warm-up pass runs automatically.

| Action | Key |
|---|---|
| Record in English | Press **F13** to start, press again to stop |
| Record in Dutch | Press **F14** to start, press again to stop |
| Quit | **Ctrl+C** in terminal or **Quit** from tray menu |

After you stop recording, the transcription is processed in the background and pasted at your cursor within seconds.

### System Tray Menu

- **Microphone** — select input device (auto-detects available mics, filters duplicates)
- **English Model** — choose from Base, Small, Medium, Distil-Medium, or Distil-Large-v3
- **Dutch Model** — choose from Base, Small, Medium, or Large-v3-Turbo
- **History...** — open the transcription history window
- **Quit** — shut down ScribeVibe

### Microphone Selector

For first-time setup, run the interactive selector:

```bash
python select_mic.py
```

This lists all input devices, filters junk entries (Sound Mapper, Stereo Mix, etc.), and lets you pick your preferred mic. The selection is saved to `settings.json`.

## Supported Models

### English

| Model ID | Menu Label | Notes |
|---|---|---|
| `base.en` | Base (EN) | Fastest, lower accuracy |
| `small.en` | Small (EN) | Default — good balance |
| `medium.en` | Medium (EN) | Higher accuracy, slower |
| `Systran/faster-distil-whisper-medium.en` | Distil-Medium (EN) | Distilled from large-v3, faster than medium |
| `Systran/faster-distil-whisper-large-v3` | Distil-Large-v3 (EN) | Best English accuracy, 6x faster than large-v3 |

### Dutch

| Model ID | Menu Label | Notes |
|---|---|---|
| `base` | Base | Fastest, multilingual |
| `small` | Small | Default — good balance |
| `medium` | Medium | Higher accuracy, slower |
| `deepdml/faster-whisper-large-v3-turbo-ct2` | Large-v3-Turbo | Best Dutch accuracy, optimized for speed |

Models are downloaded automatically from Hugging Face on first use and cached locally.

## Architecture

```
main.py                     Entry point — starts tray, listener, warmup
  +-- config.py             Settings with in-memory cache
  +-- tray_app.py           System tray icon and menus
  +-- interface.py          Hotkey listener + producer-consumer worker
  |     +-- audio_capture.py    Always-on mic stream
  |     +-- transcriber.py      Whisper engine with model lock
  |     +-- output_handler.py   Clipboard paste + logging
  +-- history_ui.py         Transcription history GUI
  +-- select_mic.py         Interactive mic selector
```

### Data Flow

```
F13/F14 pressed (start)
  -> Play start sound (async, instant)
  -> Flip _capturing flag (mic stream already open)
  -> If model swap needed: pre-load in background thread

F13/F14 pressed (stop)
  -> Flip _capturing flag
  -> Play stop sound (async)
  -> Swap raw audio buffer to worker queue (instant, no processing)

Worker thread picks up task
  -> Concatenate audio chunks + resample if needed (soxr)
  -> ensure_model() — no-op if already loaded, waits for lock if swapping
  -> Whisper transcribe with VAD filter
  -> Paste text at cursor via clipboard + Ctrl+V
  -> Log to file + notify history UI
  -> Play done sound
```

### Threading Model

| Thread | Role |
|---|---|
| **Main** | Hotkey listener — only sets flags and enqueues work |
| **Tray** | System tray event loop (daemon) |
| **Worker** | Processes transcription queue — concat, resample, inference, paste |
| **Background** | Short-lived threads for model pre-loading, warmup, logging |

## Performance Optimizations

ScribeVibe is optimized to minimize the time between pressing the hotkey and seeing your text. Here's everything that's been implemented:

### Hotkey-to-Recording Latency

- **Always-open mic stream** — the `sounddevice.InputStream` stays open permanently. Starting a recording just flips a boolean flag — no stream open/close overhead.
- **Native 16 kHz capture** — the mic stream opens at Whisper's native 16 kHz sample rate, letting PortAudio handle resampling in hardware. Falls back to 48 kHz + soxr only if the device doesn't support 16 kHz.
- **Cached hotkey objects** — F13/F14 key objects are resolved once at init, not on every keypress.
- **Fast reject** — non-hotkey keypresses are rejected immediately without any config reads or lock acquisitions.
- **Debounce guard** — 250ms monotonic timestamp check prevents double-fires without using key-up tracking (which is unreliable with macro pads).
- **Async sound playback** — `winsound.SND_FILENAME | SND_ASYNC` returns instantly; sound file paths are cached and pre-warmed into the OS file cache at startup.

### Recording-to-Transcription Latency

- **Instant buffer swap** — stopping a recording flips the flag and hands off the raw chunk list by reference. No concatenation or resampling happens on the hotkey thread.
- **Producer-consumer queue** — a dedicated worker thread processes transcription tasks from a `queue.Queue`, keeping the hotkey thread free for the next recording.
- **Async model pre-fetch** — if the requested model differs from the loaded one, a background thread starts loading it during the recording phase. By the time the user stops speaking, the model is often already ready.
- **soxr resampling** — replaced `scipy.signal.resample_poly` with `soxr`, which is 5-10x faster for audio resampling.

### Transcription Speed

- **int8_float16 compute type** — mixed-precision quantization reduces VRAM usage and increases throughput on consumer GPUs.
- **Silero VAD filter** — faster-whisper's built-in voice activity detection (`vad_filter=True`) skips silent segments before decoding, reducing unnecessary inference.
- **`condition_on_previous_text=False`** — disables cross-segment conditioning, which is unnecessary for short push-to-talk clips and saves decoder passes.
- **`without_timestamps=True`** — skips timestamp token decoding since we only need the text.
- **Configurable beam size** — defaults to 2; can be set to 1 for faster greedy decoding (especially effective with distil models).
- **Distil models** — distilled Whisper variants run 2-6x faster than their standard counterparts with minimal accuracy loss.

### Cold-Start Elimination

- **Eager model preload** — the default English model loads into VRAM in a background thread immediately at startup.
- **CUDA warm-up** — a dummy 0.5s inference pass runs after model load to trigger PyTorch JIT compilation. The first real transcription is just as fast as subsequent ones.
- **Tray menu pre-loading** — switching models via the tray menu immediately starts loading the new model in the background, rather than waiting for the next recording.

### Paste Speed

- **Direct `keybd_event`** — Ctrl+V is sent via Win32 `keybd_event` through ctypes, bypassing heavyweight abstractions.
- **Clipboard polling** — instead of a fixed sleep, the clipboard is polled every 2ms until the data is confirmed set. Typical wait: <2ms instead of 50ms.
- **Hidden clipboard** — uses the `ExcludeClipboardContentFromMonitorProcessing` format to prevent entries from appearing in Windows clipboard history.
- **Paste lock** — `threading.Lock` prevents concurrent paste operations from corrupting the clipboard.

### Config Performance

- **In-memory config cache** — `config.load()` reads `settings.json` from disk only once. Subsequent calls return a cached copy. The cache updates automatically when settings are changed via the tray menu.

### UI Performance

- **Batch rendering** — the history window loads entries in batches of 20, with 10ms gaps between batches so the window appears instantly and entries stream in without blocking.
- **Thread-safe live updates** — new transcriptions are scheduled onto the tkinter thread via `root.after(0, ...)` to avoid cross-thread Tcl errors.

## Configuration

Settings are stored in `settings.json` (created automatically):

```json
{
  "device_id": null,
  "model_size_en": "small.en",
  "model_size_nl": "small",
  "beam_size": 2,
  "hotkey_english": "f13",
  "hotkey_dutch": "f14",
  "sound_start": "assets/start.wav",
  "sound_stop": "assets/stop.wav",
  "sound_done": "assets/done.wav"
}
```

| Setting | Description | Default |
|---|---|---|
| `device_id` | Microphone device index (`null` = system default) | `null` |
| `model_size_en` | Whisper model for English transcription | `small.en` |
| `model_size_nl` | Whisper model for Dutch transcription | `small` |
| `beam_size` | Beam search width (1 = greedy, higher = more accurate) | `2` |
| `hotkey_english` | Global hotkey for English recording | `f13` |
| `hotkey_dutch` | Global hotkey for Dutch recording | `f14` |
| `sound_start` | WAV file played when recording starts | `assets/start.wav` |
| `sound_stop` | WAV file played when recording stops | `assets/stop.wav` |
| `sound_done` | WAV file played when transcription completes | `assets/done.wav` |

## Dependencies

| Package | Purpose |
|---|---|
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | GPU-accelerated Whisper inference via CTranslate2 |
| [pystray](https://github.com/moses-palmer/pystray) | System tray icon and menus |
| [Pillow](https://python-pillow.org/) | Tray icon image generation |
| [pywin32](https://github.com/mhammond/pywin32) | Windows clipboard API |
| [sounddevice](https://python-sounddevice.readthedocs.io/) | Audio capture via PortAudio |
| [numpy](https://numpy.org/) | Audio array operations |
| [pynput](https://github.com/moses-palmer/pynput) | Global hotkey detection |
| [soxr](https://github.com/dofuuz/python-soxr) | High-quality audio resampling |

## Transcription Log

All transcriptions are logged to `transcription_log.txt`:

```
[2026-03-15 12:35:43] [small.en | 1.23s] This is the transcribed text.
[2026-03-15 12:36:05] [small | 0.87s] Dit is de Nederlandse tekst.
```

View and manage this log via the **History** window in the tray menu.

## License

MIT
