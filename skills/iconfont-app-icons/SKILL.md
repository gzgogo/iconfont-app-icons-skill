---
name: iconfont-app-icons
description: Automatically identify an application's icon needs, search and select style-matched icons on iconfont.cn, add them to one configured iconfont project, and integrate the refreshed assets into the application. Use when the user wants iconfont project automation rather than only downloading standalone SVG files.
---

# Iconfont App Icons

Automate the full path from application intent to a verified iconfont project and working application code. The user has authorized automatic additions to the configured project; do not ask for per-icon confirmation.

## Required state

Before mutation, establish all of the following:

- An exact iconfont project ID or project URL. Resolve it against the authenticated project list and stop if it is missing or ambiguous.
- A style contract such as outline/filled, corner shape, stroke weight, optical size, monochrome/multicolor, and preferred collection or creator.
- The target application's current icon integration convention.

Keep project-specific, non-secret choices in one authoritative application config, preferring an existing convention. If none exists, create `.codex/iconfont-app-icons.json` with the project ID, style contract, integration mode, asset locations, and intent-to-icon mapping. Never put cookies in the application repository.

## Workflow

1. Inspect the application with `rg` to find current icon components, iconfont URLs/assets, placeholder glyphs, emoji, text substitutes, and screens requiring icons.
2. Build a deduplicated list of semantic icon intents and usage locations. Reuse an existing intent mapping rather than creating a second source of truth.
3. Check the private session with `scripts/iconfont_session.py status`. If login is absent or expired, follow the first-login procedure in [references/iconfont-workflow.md](references/iconfont-workflow.md).
4. Run `discover` before the first mutation of a session. If expected endpoints changed, inspect authenticated browser network traffic and update the helper; never guess a private endpoint or payload.
5. Resolve the configured project against `projects`, then fetch its current icons to avoid duplicates.
6. Search in both Chinese and English synonyms. Prefer candidates from the same collection or creator as already selected icons.
7. Hard-reject candidates that violate the style contract. Rank the rest by semantic fit, visual/style consistency, family consistency, and SVG quality. Inspect SVG paths or browser previews when metadata is insufficient.
8. Automatically add the highest-confidence candidate for each intent. Stop only when no candidate clears a reasonable confidence threshold; report the unresolved intent instead of adding a weak match.
9. Verify every added icon by reading the target project back. Never claim success from the mutation response alone.
10. Refresh the project's generated code, preserve the application's existing Symbol, Font Class, or Unicode mode, and update the single authoritative icon mapping. If the application has no convention, default to Symbol.
11. Run relevant build/tests and visually inspect affected screens when the environment permits. Report icon IDs, names, intent mappings, code locations, and any unverified runtime behavior.

## Mutation boundaries

- Automatically adding selected icons to the exact configured project is authorized.
- Do not create an iconfont project unless the user explicitly asks; this workflow assumes the user created it.
- Never delete, rename, recolor, overwrite, transfer, or change permissions for existing project icons.
- Do not add to a project selected only by a fuzzy name match.
- Skip icon IDs already present. Make retries idempotent and verify after writes.
- On CAPTCHA, expired login, 401/403, rate limiting, or response-schema changes, stop the API path and restore the session through the browser.

## Secrets

Store browser state only under `${CODEX_HOME:-~/.codex}/private/files/iconfont/` with directory mode `0700` and file mode `0600`. Never print Cookie headers, cookie values, CSRF values, storage-state contents, or authenticated request dumps.

If the user's environment already defines a shared configuration library for reusable service accounts, update its canonical iconfont entry with a `file_refs` reference to the session file. Preserve comments and unrelated content; do not embed the cookie value. Do not create or assume a shared library when the environment has no such convention.

For exact first-login, API, recovery, and integration procedures, read [references/iconfont-workflow.md](references/iconfont-workflow.md).
