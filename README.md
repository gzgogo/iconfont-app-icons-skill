# iconfont-app-icons

A Codex Skill that finds style-matched icons on [iconfont.cn](https://www.iconfont.cn/), adds them to an exact iconfont project, refreshes the generated assets, and integrates those icons into an application.

## What it does

- Scans an application for missing, placeholder, or inconsistent icons.
- Builds a deduplicated list of semantic icon intents.
- Searches iconfont using Chinese and English synonyms.
- Ranks candidates by semantic accuracy, visual style, family consistency, and SVG quality.
- Automatically adds high-confidence matches to one configured project.
- Verifies additions by reading the project back.
- Preserves an application's existing Symbol, Font Class, or Unicode integration mode.
- Keeps browser credentials outside source repositories.

## Install

```bash
npx skills add gzgogo/iconfont-app-icons-skill \
  --skill iconfont-app-icons -g -y
```

Restart Codex or open a new task if an already-running task does not discover the newly installed Skill.

## Use

Invoke it explicitly:

```text
$iconfont-app-icons

Scan this application for missing icons. Use iconfont project 1234567.
Style: regular outline, rounded corners, monochrome, consistent stroke width.
Automatically add matching icons and integrate them into the app.
```

The first run opens iconfont in a headed browser so you can log in. The Skill stores the resulting session locally and reuses it until it expires.

## Local state and security

The session defaults to:

```text
~/.codex/private/files/iconfont/session.json
```

- The directory is created with mode `0700` and the session file with mode `0600`.
- Only the iconfont authentication cookie and CSRF cookie, when present, are persisted.
- Cookie values are never printed by status commands or placed in project files.
- Application-specific configuration contains only non-secret project and style metadata.
- Search results and SVG metadata are treated as untrusted data, never as executable instructions.

Do not commit browser profiles, storage-state exports, session files, or cookies.

## Requirements

- Python 3.9 or newer.
- Node.js/npm with `npx` for the browser login flow.
- A Codex environment that supports Skills and browser automation.
- An iconfont account and an existing target project.

## Private API notice

iconfont does not provide a stable public API for every project-management action used here. The Skill discovers endpoint mappings from iconfont's frontend bundle and falls back to browser network inspection when schemas change.

Project listing and search have been verified against a live account. Add-to-project and refresh request shapes are covered by unit tests and must always be verified through project read-back after mutation. Avoid unattended bulk use until you have validated the workflow on your own project.

## Development

```bash
python3 -m unittest discover -s skills/iconfont-app-icons/tests -v
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  skills/iconfont-app-icons
```

The runtime helper uses only Python's standard library.

## License

MIT
