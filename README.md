# Zoom Notes Minimal

A macOS menu bar app that automatically saves the full transcripts captured by Zoom **My Notes** as local Markdown files.

The app reads Zoom's local transcript cache while a meeting is active, preserves captured speech across cache checkpoints, and saves the transcript after an idle period. It does not generate summaries or titles with an AI model, require API keys, or send transcripts to another service. Zoom still performs the original transcription.

## Output

By default, each meeting produces one file:

```text
~/Desktop/Meeting Notes/Transcripts/
  YYYY-MM-DD/
    Meeting Title — transcript.md
```

Files contain meeting metadata, speaker names, timestamps, and the captured speech. There are no separate summary files or links to nonexistent notes. Custom YAML frontmatter applies to transcripts.

Meeting titles come from Zoom's cached meeting title or a dated fallback. Files for different meetings with the same title get separate filenames rather than overwriting each other.

## Requirements

- macOS 13 (Ventura) or later
- Zoom desktop app with My Notes transcription enabled
- No model, AI service subscription, or API key is required by this app

## Build and run

This fork changes the behavior of the original app. The upstream release installer does **not** contain these changes; build this fork locally.

```bash
git clone https://github.com/Smoooj/Zoom-Notes-Minimal.git
cd Zoom-Notes-Minimal
make install-hooks
./scripts/fetch-python-runtime.sh
xcodebuild -project ZoomNotesApp/ZoomNotesApp.xcodeproj \
  -scheme ZoomNotesApp -configuration Debug \
  -derivedDataPath build/DerivedData CODE_SIGNING_ALLOWED=NO build
```

The build contains the Swift app, the Python engine, and a bundled Python runtime. For a signed local installation, review `scripts/install-local.sh` and run `make install`.

Once running, open **Settings → Output** to choose a transcript folder and filename pattern. **Advanced** controls the polling interval, idle threshold, database hints, and blocked meetings.

The menu bar item displays only an icon. Its menu offers **Save Transcript Now**, shows the last saved transcript, and provides recovery or retry options after a crash or failed file write.

Existing transcript output preferences are preserved when loading older settings files. Removed model, prompt, and summary-output fields are ignored. Previously stored credentials are not read or modified.

## Command-line tools

```bash
python3 zoom_notes.py --list             # Inspect discovered meeting data
python3 zoom_notes.py --dump             # Print the current transcript
python3 zoom_notes.py --watch            # Follow a transcript during a meeting
python3 zoom_notes.py --save             # Save the current transcript
python3 zoom_notes.py --save --dry-run   # Preview the full Markdown without saving
```

Optional overrides are documented in `.env.example`: `ZOOM_NOTES_TRANSCRIPTS_DIR` selects the transcript folder, and `ZOOM_NOTES_USER_NAME` helps identify the meeting you attended. The engine reads environment variables; it does not automatically load a `.env` file.

## Architecture

- `zoom_notes.py`: cache discovery, transcript parsing, deduplication, local persistence, and Markdown writing.
- `zoom_config.py`: local output and capture preferences.
- `zoom_engine.py`: background capture, idle detection, meeting isolation, saving, and recovery.
- `ZoomNotesApp/`: Swift/SwiftUI menu bar app, settings and notifications.

Capture snapshots survive engine restarts. Failed saves remain recoverable in the existing cache retention flow. Recovery saves the raw transcript and can run while another meeting is being captured.

## Validation

```bash
python3 -m venv venv
./venv/bin/pip install pytest
make check
make check-bundled
```

The tests cover parsing, meeting isolation, collisions, saving without network access, short transcripts, write failures, cancellation, and recovery. Tests requiring captured Zoom WAL fixtures skip when those fixtures are absent; synthetic tests do not require Zoom or private meeting data.

## Limitations

- Zoom's cache layout is an internal implementation detail and may change with updates.
- Capture must run while My Notes writes speech to its local cache. This is not a complete export of historical cloud notes.
- Idle detection is a heuristic; long silent periods can trigger a save before the meeting has formally ended.
- Availability and accuracy of transcription depend on Zoom and the meeting's permissions.

Based on [nickybmon/Zoom-Notes](https://github.com/nickybmon/Zoom-Notes), under the MIT license.
