# Subtra

A desktop subtitle app for Windows 10/11 that runs **entirely on CPU — no GPU
required**. Pick a video and Subtra detects the spoken language by itself,
transcribes it, translates it into one of 21 languages, writes an `.srt`, and
optionally burns the subtitles into the video.

Everything is **local and free**: no paid services, no API keys, no sign-up.
The network is used only for the **first** model/FFmpeg download.

**Languages:** English (this file) · [Türkçe](docs/README.tr.md)

> **About this repository:** only source code lives here. Model files
> (`models/`), FFmpeg (`ffmpeg/`), videos and subtitle files are **not**
> committed — they are downloaded automatically on first run, or by you.
> See [Models](#5-models-automatic-one-time).

---

## Version policy

| Branch | Contents |
|---|---|
| `main` | **Stable releases only.** Every release is tagged (`v2.0.1`). |
| `development` | Active development. May be unstable. |

`main` never receives direct commits. Work happens on `development`, and once
it is stable it is fast-forwarded into `main` and tagged.

```bash
git checkout development     # development
git checkout main            # stable release
```

---

## What's new in 2.0

**Distribution and reliability**
- FFmpeg is no longer a manual install: it is used from the exe folder if
  present, otherwise **downloaded automatically on first use**
  (`%LOCALAPPDATA%\Subtra\tools\ffmpeg`). Two mirrors (gyan.dev + BtbN),
  with progress and cancel support.
- All writable data lives under `%LOCALAPPDATA%\Subtra` — no permission
  problems even when installed into Program Files. A legacy `models\` folder
  is detected automatically, and an old `VideoCeviri` data folder is migrated
  so models are not re-downloaded.
- Rotating log file (`logs\subtra.log`, 2 MB × 3) plus **"Copy error report"**
  and **"Save report…"** buttons.
- CPU thread count is derived from **physical cores** (hyper-threading is not
  counted).

**Subtitle quality**
- **Word-level timestamps** (`word_timestamps=True`): cues are no longer cut
  through the middle of a word.
- Split decisions use punctuation + silence + duration limits; character count
  is only used for line wrapping.
- Sentence merging plus proportional time distribution after translation.
- **CPS (characters per second) rule**, default 18. Offending cues are fixed by
  extending their duration; splitting is not used because it cannot lower CPS
  (same characters over the same span).
- **Subtitle scaling**: `font_size` is defined against a 640 px reference
  height and scaled to the real video size. libass's default `PlayResY=288`
  box made text **6.7×** larger on a 1918 px tall video, covering the screen;
  `PlayResX/PlayResY` now match the video dimensions.
- **Burn-in encoder**: `crf 18` + `preset slow` + `ref=5` + `aq-mode=3` +
  `deblock=1,1` + the correct H.264 level. The old `crf 20 / medium / ref=3 /
  level 4.0` combination produced measurable blocking in dark scenes (see the
  diagnostics note below).

**Performance**
- Long videos are processed in **10-minute chunks**: memory stays flat and
  cancellation is much faster. Word repeats at chunk boundaries are removed.
- Transcription and translation can run **in parallel (pipeline)**. Enabled
  automatically on 6+ physical cores; kept off below that, where two models
  fight over the same threads.

**Productivity**
- **Queue tab**: add multiple videos and process them in order. Models load
  once and stay in memory for the whole queue. **Each queue row has its own
  target language** — one video can be translated into several languages in a
  single run, and transcription runs only once.
- **Transcript cache**: the Whisper result is written to
  `cache/transcripts/` and reused. Translating the same video into a second
  language skips transcription entirely — measured **2.32×** faster on the
  test clip (24.6s → 10.6s). The cache key includes file size, mtime, model
  size and word-timestamp mode, so an edited video or a different model
  invalidates it. Can be disabled and cleared from Settings.
- **Whisper batch mode** (Settings): `BatchedInferencePipeline` for faster CPU
  inference — measured 1.82× on `tiny`, 1.17–1.34× on `small`. Off by default.
- **Translate SRT tab**: translate an existing `.srt` — transcription is
  skipped, and an optional video enables burn-in/soft-sub. This tab has its
  **own target language and output selection**, independent of the Video tab.
- **No filename collisions**: the output name carries the target language
  (`film_tr.srt`, `film_de.srt`). Translating one video into several languages
  never overwrites a previous result.
- **Cache management**: see models with their sizes in Settings, and delete
  them. Transcript cache size, count and a clear button live next to it.

---

## Features

- Automatic language detection (Whisper) with a confidence readout
- Timestamped transcription (faster-whisper, CPU, `int8`, VAD)
- Sentence-based, context-preserving translation (NLLB-200 distilled 600M via CTranslate2)
- Target language: **21 languages** (Turkish, English, German, French, Spanish,
  Russian, Arabic, Chinese, Japanese, Korean, Hindi, Portuguese, Italian,
  Persian, Indonesian, Urdu, Bengali, Vietnamese, Tamil, Telugu, Marathi)
- Translation is skipped automatically when source and target match
- Three output modes: burn-in (`libx264`, audio copied), soft subtitles
  (no re-encoding), or `.srt` only
- Subtitle styling for burn-in: size, colour, position (Arial — Turkish
  characters render correctly)
- ≈42 characters per line, at most 2 lines; very short cues are merged
- Staged progress bar, live log panel, **Cancel** button
- All heavy work runs in a `QThread` — the UI never freezes
- Spaces and non-ASCII characters in paths are fine (UTF-8, never `shell=True`)
- Temporary files are removed on completion or cancellation
- Turkish error messages in the UI

---

## Project layout

| File | Purpose |
|---|---|
| `main.py` | Entry point; DPI, dependency check, logging setup |
| `gui.py` | PySide6 UI: 4 tabs (Video / Queue / SRT / Settings) |
| `worker.py` | `ModelCache`, `JobRunner`, `VideoWorker`, `BatchWorker` |
| `transcriber.py` | Whisper download/load, **chunked** transcription, word timestamps |
| `translator.py` | NLLB download/load, batch translation, `TranslationPipeline` |
| `subtitles.py` | Word-based cue building, wrapping, CPS, SRT read/write |
| `transcript_cache.py` | Transcript cache (JSON, atomic, keyed by file+model) |
| `ffmpeg_utils.py` | Audio extraction, burn-in, soft-sub, path escaping, disk checks |
| `ffmpeg_bootstrap.py` | FFmpeg discovery + **automatic download** |
| `app_paths.py` | `%LOCALAPPDATA%` paths, legacy folder migration |
| `hardware.py` | Physical cores/RAM, thread budget, model recommendation |
| `logging_setup.py` | Rotating file log + UI queue |
| `error_report.py` | Copyable error report |
| `errors.py` | Shared exception types |
| `languages.py` | Whisper → NLLB mapping, 21 target languages, filename suffixes |
| `Subtra.spec` / `build.ps1` | PyInstaller packaging |
| `requirements.txt` | Python dependencies |
| `test/` | Verification scripts |

---

## 1. Python

Python 3.10 – 3.14 is supported (tested on 3.13 and 3.14).

```powershell
py --version
```

Virtual environment (recommended):

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks scripts:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

## 2. Dependencies

```powershell
py -m pip install --upgrade pip
py -m pip install -r requirements.txt
```

## 3. Visual C++ Redistributable (critical)

The translation engine **CTranslate2** is a native C++ library. On Windows, an
old `MSVCP140.dll` (e.g. 14.29) makes the app **exit silently** while a model
loads — no error message. This machine hit exactly that problem.

```powershell
winget install --id Microsoft.VCRedist.2015+.x64 -e
```

Or manually: <https://aka.ms/vs/17/release/vc_redist.x64.exe> → **reboot**.

Verify:

```powershell
(Get-Item C:\Windows\System32\MSVCP140.dll).VersionInfo.FileVersion
```

It must be **14.30 or newer**. The app checks this itself via
Settings → *Translation engine* → **Check**, probing in a separate process, and
shows a Turkish explanation if something is wrong.

## 4. FFmpeg

**You do not need to install it manually.** The app looks in this order:

1. The path chosen in Settings
2. `ffmpeg\bin\` next to the exe
3. `%LOCALAPPDATA%\Subtra\tools\ffmpeg\bin` (previously downloaded)
4. `PATH`

If none is found, use Settings → **Download FFmpeg** (~90 MB) or point at
`ffmpeg.exe` manually. The download runs in the background; the UI stays
responsive.

> `ffmpeg.exe` and `ffprobe.exe` must be in the **same folder**.

## 5. Models (automatic, one-time)

Downloaded on first use into `%LOCALAPPDATA%\Subtra\models` (a legacy `models\`
folder is used if present):

| Model | Size | When |
|---|---|---|
| `faster-whisper-tiny` | ~75 MB | if `tiny` is selected |
| `faster-whisper-base` | ~145 MB | if `base` is selected |
| `faster-whisper-small` | ~484 MB | `small` |
| `faster-whisper-medium` | ~1.5 GB | `medium` |
| `nllb-200-distilled-600M-ct2-int8` | ~615 MB | on first translation |

Once downloaded, the app works **fully offline**. Models can be inspected and
deleted from the Settings tab.

---

## Usage

```powershell
py main.py
```

or double-click `calistir.bat`.

### Video tab
1. Drag and drop a video, or use **Choose file…**
2. **Whisper model** (the recommendation is picked from your hardware)
3. **Target language**: one of 21
4. **Output**: burn-in / soft subtitles / `.srt` only
5. Adjust burn-in styling if needed → **Start**

### Queue tab
Drag in several videos → **Start queue**. Status and output name appear per
file; on error the queue continues and prints a summary at the end.

### Translate SRT tab
Drop an existing `.srt`. Optionally pick a video (for burn-in or soft
subtitles). If **source language** is left on auto, it is guessed from the text.

**Target language** and **output type** are set separately in this tab — they
do not follow the Video tab.

### Settings tab
- **CPU thread** / **num_workers** — blank means physical core count
- **Transcription + translation in parallel** — Auto / On / Off
- **CPS limit** — 0 disables it; 17–20 recommended
- **Word-level timestamps** — more accurate splitting, ~15% slower
- **FFmpeg**, **translation engine**, **model cache** management

### Output files

Written next to the source file:

```
video.mp4
video_tr.srt      ← when the target language is Turkish
video_de.srt      ← when the target language is German
video_de.mp4      ← when burn-in or soft subtitles were selected
```

The suffix in the filename shows the target language, so translating the same
video into several languages never overwrites an earlier result.

---

## Testing (step by step)

### A. Environment

```powershell
py --version
py -c "import PySide6, faster_whisper, ctranslate2, tokenizers, requests, psutil; print('dependencies ok')"
```

### B. Syntax

```powershell
py -m py_compile main.py gui.py worker.py transcriber.py translator.py subtitles.py ffmpeg_utils.py languages.py app_paths.py hardware.py logging_setup.py error_report.py ffmpeg_bootstrap.py errors.py version.py transcript_cache.py
```

### C. Unit tests (no network, no models)

```powershell
py test/test_subtitles.py        # subtitle engine
py test/test_cache_and_batch.py  # transcript cache + batch (~80s)
py test/test_version.py          # single source of version truth
py test/test_download_resume.py  # HTTP Range resume, local server
py test/test_logging.py          # log file + no duplicate UI lines
```

`test_download_resume.py` spins up a local HTTP server that cuts the transfer
mid-stream, then verifies that `.part` is kept, `Range` is sent, and the final
SHA256 matches. No internet needed.

### D. Engine and FFmpeg

```powershell
py -c "from translator import check_ctranslate2_runtime; print(check_ctranslate2_runtime())"
py -c "import ffmpeg_bootstrap as b; print(b.describe_ffmpeg())"
```

Expected: `None` and an FFmpeg version line.

### E. End to end (real video)

The test video is **not in the repo** (media is git-ignored). It is generated
automatically on first use:

```powershell
py test/make_fixture.py          # generate test/konusma ingilizce.mp4
py test/make_fixture.py --check  # just report what exists
```

Generation uses Windows SAPI for English speech plus FFmpeg for the video.
Without an English SAPI voice the video cannot be produced, and the
model-dependent tests report `SKIP` instead of failing.

```powershell
py test/test_transcribe.py     # chunking + word timestamps
py test/test_runner.py         # srt / burn / pipeline / SRT import
py test/test_queue.py          # queue + model reuse
py test/run_cancel_test.py 2500   # cancel + temp cleanup
```

### F. UI

```powershell
py test/gui_screenshot.py "test\konusma ingilizce.mp4"
```

Writes `test/gui_tab_*.png`.

### G. Full suite

```powershell
py test/run_all.py            # SKIP is not a failure
py test/run_all.py --strict   # SKIP counts as failure (for CI with models)
```

Exit codes: `0` all passed (or skipped), `1` a test failed, `77` nothing ran.

Tests never download models: `SUBTRA_NO_DOWNLOAD=1` is set by
`test/fixtures.py`, so a missing model produces `SKIP`, not a silent
multi-hundred-MB download.

### H. Failure scenarios

| Scenario | Expected |
|---|---|
| Silent video | "Bu videoda ses kanalı bulunamadı." |
| Corrupt file | "Video dosyası çözümlenemedi veya bozuk." |
| No FFmpeg | Offer to download automatically |
| No internet (first download) | "FFmpeg otomatik olarak indirilemedi…" |
| No speech | "Videoda konuşma bulunamadı." |
| Disk full | "Disk dolu… boş alan açıp tekrar deneyin." |
| Old VC++ | "ÇALIŞMIYOR" in Settings plus a Turkish explanation |

### I. Video quality diagnostics

If a video shows pixelation, tearing, or oversized subtitles:

```powershell
py test/diagnose_quality_report.py "C:\path\video.mp4"
```

The report covers subtitle area ratio, dark-region blocking delta, SSIM, H.264
level and bitrate. The `ORTALAMA` line rates the result `İYİ / KABUL
EDİLEBİLİR / KÖTÜ`.

To check H.264 level conformance (MaxFS / MaxMBPS / MaxDPB):

```powershell
py test/check_h264_level.py
```

---

## Building an exe

```powershell
powershell -ExecutionPolicy Bypass -File build.ps1
```

The script installs dependencies, runs the tests, packages with PyInstaller,
copies the local FFmpeg into `dist`, and produces `Subtra-portable.zip`.

Packaging only:

```powershell
py -m PyInstaller Subtra.spec --noconfirm --clean
```

Result:

```
dist\Subtra\
    Subtra.exe
    ffmpeg\bin\ffmpeg.exe      ← no PATH needed
    ffmpeg\bin\ffprobe.exe
    _internal\...
```

- **Folder mode** is used (not `--onefile`): fast startup, persistent models.
- If you prefer not to bundle FFmpeg, delete the folder and the app will
  download it on first launch.
- If antivirus flags the exe, add the folder to its exclusions.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError` | `py -m pip install -r requirements.txt` |
| App closes silently during translation | Update the VC++ Redistributable (section 3) |
| "Translation engine is not working" | `winget install --id Microsoft.VCRedist.2015+.x64 -e` |
| FFmpeg not found | Settings → Download FFmpeg |
| Model download fails | Check internet/proxy and disk space |
| Translation is slow | Try `tiny`/`base`, close other programs |
| Subtitles flash by too quickly | Lower the CPS limit (e.g. 15) |
| **Subtitles cover the screen / huge text** | Use the current version (scaling fix); Settings → burn-in quality |
| **Blocking/pixelation in dark scenes** | Set burn-in CRF to 16–18; older builds used 20 |
| Blurry UI | Windows scaling between 100-150% |
| **Black console window stays open, Qt DPI warning** | Launch with `calistir.bat` (uses `pyw`, no console) — fixed in 2.1.2 |
| Out of memory | Smaller model, `num_workers=1` |

When reporting a problem, use **Copy error report**; it includes version, OS,
hardware, FFmpeg, model inventory, settings and the last 200 log lines.

### Developer notes (real bugs encountered)

1. **CTranslate2 access violation (0xC0000005)** — an old `MSVCP140.dll` (14.29)
   made `ctranslate2.Translator(...)` crash the whole process; Python
   `try/except` cannot catch it. Fixed with the VC++ update plus a preflight
   check in a separate process (`translator.check_ctranslate2_runtime`).

2. **Missing EOS token in NLLB** — the source sequence was
   `[src_lang] + tokens` and the model repeated "Kat Kat Kat…". NLLB expects
   `</s>` at the end of the source sequence. Also, `sentencepiece` IDs do not
   match NLLB order; the `tokenizer.json` + `shared_vocabulary.txt` mapping is
   required.

3. **PyAV / faster-whisper incompatibility** — `av` 19 raised
   `metadata_errors` when given a file path. Fixed by reading the WAV into a
   float32 array with `wave` + numpy and giving Whisper the **array**.

4. **Word repeats at chunk boundaries** — 10-minute chunks duplicated the last
   words. Fixed with `_duplicate_prefix_len`, comparing normalised word
   prefixes.

5. **CPS splitting destroyed meaning** — splitting by character count cut
   sentences in half, and it cannot lower CPS anyway. Fixed with word
   timestamps + punctuation boundaries, and CPS handled by extending duration.

6. **Subtitles covered the screen (huge text)** — reported on a 1080x1918
   vertical video. Cause: libass scales `FontSize` against the default
   `PlayResY=288` box, so `FontSize=18` × (1918/288) = **120 px** text, which
   pushed 2 lines into 4 and covered half the frame. Fix: `PlayResX/PlayResY`
   match the video size and the point size is converted to pixels. Measured:
   subtitle area dropped from 2.58% to 0.57% of the frame (**78% smaller**).

7. **Blocking / pixelation in dark scenes** — the second issue reported on the
   same video. Diagnosis: per-frame SSIM plus a purpose-built **blocking
   metric** (ratio of pixel differences across 8×8 block boundaries to
   differences inside blocks).

   | Measurement | Old settings | New settings |
   |---|---|---|
   | SSIM, subtitle-free region | 0.9972 | 0.9978 |
   | Blocking delta, dark region | **+0.209** | **+0.038** |
   | H.264 level | 4.0 | 5.0 |
   | Bitrate | 3066 kbps | 4186 kbps |

   The culprit was **encoder settings**, not bitrate: `ref=3`, `aq-mode=1`,
   `deblock=1,0` and level 4.0. `aq-mode=3` allocates more bits to dark scenes,
   `deblock=1,1` smooths block edges, `ref=5` improves prediction. Blocking
   dropped **82%**. Level 4.0 was also sitting exactly on the DPB limit for
   1080x1918@30 (ref=5 cannot store 6 frames); the level is now computed from
   `width/height/fps`.

   Trying `crf 14` on the same video did **not** fix blocking (+0.189) —
   higher bitrate alone is not the answer; the right `x264-params` are.

---

## Technical notes

- **Audio**: FFmpeg produces 16 kHz mono `pcm_s16le` WAV.
- **Chunking**: the WAV is split into 10-minute chunks with `wave` (no extra
  ffmpeg pass, ~38 MB per chunk). 1 s overlap, duplicate cleanup at chunk
  start. Language is detected on the first chunk and then pinned; context is
  carried via `initial_prompt`.
- **Thread budget**: all physical cores for a single model; 60% Whisper / 40%
  NLLB when pipelining.
- **Pipeline**: `queue.Queue(maxsize=8)` producer-consumer; the producer blocks
  when the queue is full, keeping memory bounded.
- **Ordering guarantee**: pipeline results are stored by index, so `finish()`
  returns them in order.
- **Burn-in**: `subtitles` filter + `force_style`
  (`FontName=Arial`, colour in BGR order as `&HAABBGGRR`).
  `PlayResX/PlayResY` match the video size and the point size is scaled to
  pixels, otherwise text becomes huge on high-resolution video.
  Encoder: `crf 18`, `preset slow`, `ref=5:aq-mode=3:deblock=1,1:
  psy-rd=1.0,0.15`, level computed by `h264_level_for(w, h, fps)`.
  Path escaping is two-layered: `C\:/...`, and a relative name + `cwd` fallback.
- **Soft subtitles**: `.mp4` → `mov_text`, `.mkv` → `srt`, `-c copy`.
- **SRT**: UTF-8 without BOM, LF, `HH:MM:SS,mmm`.
- **Cancellation**: `threading.Event`; the FFmpeg process is terminated, the
  chunk loop checks every step, temporary files are removed.

---

## License

Subtra is released under the **MIT License** — see [LICENSE](LICENSE).

Downloaded models keep their own licences:

- faster-whisper / Whisper: MIT
- NLLB-200: CC-BY-NC-4.0 (check your licence needs for commercial use)
- FFmpeg: LGPL/GPL
