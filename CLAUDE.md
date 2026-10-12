# Zoom Notes Minimal — repository guide

## Purpose and scope

This fork captures Zoom My Notes transcripts and saves them locally. It has no model providers, summarization, AI title generation, prompts, credential handling, or runtime network calls. Preserve raw speech and recovery behavior when changing the app.

## Architecture

- `zoom_notes.py`: discovers Zoom WebKit cache buckets, identifies transcript and title databases by content, parses and deduplicates speech, persists recovery snapshots, and writes collision-safe Markdown transcripts.
- `zoom_config.py`: local JSON preferences and output path helpers.
- `zoom_engine.py`: polls every configured interval, accumulates speech, detects idle/boundary changes, saves transcripts, and exposes recovery commands.
- `ZoomNotesApp/ZoomNotesApp/`: Swift/SwiftUI menu bar application. `EngineManager` starts the Python child and drains stdout and stderr. `AppState` translates engine events into menu state and notifications.

The menu bar status item is icon-only in every engine state. There is no calendar access or upcoming-meeting system.

Runtime dependencies are Python's standard library, the macOS `strings` command, and Apple frameworks. Pytest is test-only. The app bundles Python 3.12 via `scripts/fetch-python-runtime.sh`.

## Capture and saving

Resolve every signed-in or unsigned WebKit bucket rather than assuming a fixed origin. Database prefixes are hints; content discovery is authoritative. Keep incremental, atomic recovery snapshots so a Zoom checkpoint or engine restart cannot lose already captured speech.

Save only a meeting's own entries (plus early entries with no meeting ID). Meeting titles come from Zoom's title cache or a dated fallback. Do not synthesize titles from speech.

Different meetings with the same title must not overwrite each other. `meeting_id` frontmatter is the identity check used by the collision-safe writer. A successful save removes the recovery snapshot; a failed write keeps it recoverable.

Back-to-back saves run in the background while capture stays active for the next meeting. Preserve the existing deferred-boundary and meeting-isolation heuristics. Recovery also preserves the active meeting's UI state.

## Engine protocol

States: `idle`, `active`, `saving`.

Commands: `save`, `reload`, `retry`, `recover`, `dismiss`, `dismiss_all`, `clear_cache`.

Events: `ready`, `state`, `done`, `transcript_failed`, `recovery_available`, `error`, `diag`, `dismissed`, `cache_cleared`.

The `done` event's `path` and `transcript_path` point to the saved transcript. `background: true` means the event must not reset capture to idle.

## Configuration

Preferences remain in `~/Library/Application Support/zoom-notes/settings.json`. Supported fields are transcript directory and filename pattern, date subfolder pattern, custom frontmatter, polling and idle intervals, database hints, diagnostics, and blocked meeting IDs. Removed settings from older versions are ignored without resetting supported fields. Do not read, overwrite, or delete old stored credentials.

Optional environment overrides: `ZOOM_NOTES_TRANSCRIPTS_DIR`, `ZOOM_NOTES_USER_NAME`.

## Development

Install the repository's commit protection once per clone:

```bash
make install-hooks
```

It prevents accidentally committing captured meeting databases, real speech, local settings, or secrets. Do not disable it for those files.

Validate changes with:

```bash
make check
make check-bundled
xcodebuild -project ZoomNotesApp/ZoomNotesApp.xcodeproj \
  -scheme ZoomNotesApp -configuration Debug \
  -derivedDataPath build/DerivedData CODE_SIGNING_ALLOWED=NO build
```

`make check` expects pytest in `venv/`. `make check-bundled` needs the fetched runtime and installs pytest there if necessary. Private captured fixtures are optional; the test suite reports skips if they are missing. Use synthetic entries for new tests.

Do not install, deploy, sign, commit, or push changes unless requested. Local build and test outputs are ignored by Git.
