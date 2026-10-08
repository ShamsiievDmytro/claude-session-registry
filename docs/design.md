# Session Registry: Design

## Goal

One plain Markdown file that lists every interactive Claude Code session, newest first. Each entry has a short title, a 2–3 sentence description, where the session ran, where it left off, and a ready-to-run resume command. A `/find-session` skill searches the file and hands back the resume command.

**Problems it solves:**
- **Finding sessions across projects.** `claude --resume` shows the current folder by default.
- **Weak auto titles.** They come from the first prompt and many look alike.
- **No log to read.** A file you can open, scan or grep, and that an agent can search.

## Why not an existing tool

Several tools already index sessions by scanning transcripts after the fact: [fast-resume](https://github.com/angristan/fast-resume), [resesh](https://github.com/miyago9267/resesh), [agent-sessions](https://github.com/jazzyalex/agent-sessions), [claude-code-history-viewer](https://github.com/jhlee0409/claude-code-history-viewer), [cass](https://github.com/Dicklesworthstone/coding_agent_session_search) and [aichat](https://pchalasani.github.io/claude-code-tools/tools/aichat/).

None of them:
- writes summaries (about, left off, keywords) to one greppable file;
- pushes better titles back into Claude itself;
- keeps a record after Claude's 30-day transcript cleanup.

## Registry file

Path: `~/.claude/session-registry.md`. Override it with the `SESSION_REGISTRY_FILE` environment variable.

```markdown
<!-- session:<id> created:2026-10-07T23:41 turns:7 pushed:3f9a1c2e -->
## Add rate limiting to the public API
- **When:** 2026-10-07 23:41 → last active 2026-10-08 00:30
- **Project:** ~/code/api (branch: rate-limit)
- **Model / app:** opus-5-5 · cli
- **About:** Added a token-bucket limiter to the public endpoints and covered it with integration tests. Chose Redis for shared state across instances.
- **Left off:** In progress - load-test the limiter before enabling it in production.
- **Keywords:** rate limiting, middleware.ts, redis, integration tests
- **Resume:** `cd ~/code/api && claude --resume <id>`
```

**Rules:**
- **Order:** entries are sorted by creation time, newest first. Updates change an entry in place and never move it.
- **Marker line:** an HTML comment, invisible when rendered, holding four fields:
  - `session`: the session ID.
  - `created`: the start time.
  - `turns`: prompts covered by the last summary.
  - `pushed`: hash of the last title pushed into Claude, or `user` once you have renamed the session.
- **Length limits:** title ≤ 10 words; about 2–3 sentences, ≤ 45 words; left off is one line; 3–5 keywords; every field is a single line.
- **Deleted transcripts:** once Claude deletes a transcript, the entry stays, but its Resume line becomes `⚠ transcript deleted (30-day cleanup), not resumable`.
- **Sessions with no real work** (a bare login, an error, a greeting, ≤ 3 prompts) collapse to a hidden marker.
- **Hand edits** are overwritten, because the file is regenerated on every write.

## Capture

One stdlib-only Python script, `session_registry.py`, wired to three hooks:

| Hook | Action |
|---|---|
| `Stop` | Creates the entry after the first reply, then summarizes in the background. Afterwards: updates Last active, and summarizes again once 10 more prompts have passed. |
| `SessionEnd` | Runs a final summary if there were new prompts. |
| `UserPromptSubmit` | Pushes the latest summary title into Claude's own session title, unless you used `/rename`. |

**Skipped sessions:**
- Automated sessions (entry point `sdk-*`, which covers the Agent SDK and `claude -p`).
- `claude -p` runs started from inside another Claude session. These inherit that session's entry point, so on Claude Code 2.1.205 and newer a session counts only if a person typed at least one of its prompts (`origin.kind == "human"`).
- Hook calls whose transcript was never written, such as a print-mode run killed early.
- Sessions with no prompts.
- The summarizer's own call, flagged by `SESSION_REGISTRY_CHILD=1`.

Injected system messages, such as task notifications, local command output and compaction summaries, don't count as prompts.

**Summarizer:**
- Runs detached, so hooks return in milliseconds.
- **Input:** your prompts (up to 1,500 characters each) and the assistant's text (up to 600 characters each). Sessions longer than 20,000 characters keep the first 4,000 and the last 16,000.
- **Call:**

```
claude -p --model haiku --output-format json --no-session-persistence \
  --setting-sources "" --tools "" --strict-mcp-config --disable-slash-commands \
  --system-prompt "You summarize coding-agent sessions for a searchable registry. Reply with JSON only."
```

These lean flags skip your plugins, tools and CLAUDE.md. A default `claude -p` call costs about 8× more.

**Safety:**
- **Writes:** every write holds a file lock (`fcntl` on macOS/Linux, `msvcrt` on Windows) and goes through a temp file plus `os.replace`, so parallel sessions never corrupt the file. On Windows the replace is retried briefly while another process has the file open.
- **Encoding:** every file is read and written as UTF-8, so Windows' default code page can't break the `→` and `⚠` characters.
- **Hooks never break a session:** errors go to `~/.claude/session-registry.log` and the hook exits 0.
- **Resume line:** session IDs must match `[\w-]+`.
  - macOS/Linux: folders are quoted with `shlex.quote`, giving `cd ~/'My Proj' && claude --resume <id>`.
  - Windows: `cd 'C:\path'; claude --resume <id>`, single-quoted with `'` doubled, so `$(…)` and backticks stay literal in PowerShell 5/7 and Git Bash.
  - Windows folders containing `[` or `]` get `Set-Location -LiteralPath`, because PowerShell's `cd` treats brackets as wildcards.
  - CI pastes every form into real bash, sh, PowerShell 5, PowerShell 7 and Git Bash with hostile folder names.
- **Finding `claude`:** only absolute `PATH` entries and `~/.local/bin` are searched, never the current folder. Hooks run inside the user's project, and both `shutil.which` and Windows' process search look in the current folder first.
- **Starting Python:** `hooks/run` picks `python3` on macOS/Linux, and `py -3` then `python` on Windows (where `python3` is often a Microsoft Store stub). On Windows the background summarizer starts without a console window.
- **Haiku's text** is collapsed to single lines, so it can't inject entries or fields.
- **Rename detection:** a custom title counts as your `/rename` only if it differs from every title we pushed. This survives the desktop app's own auto titles and summaries that run at the same time.

## Search

`/find-session` is a plain `SKILL.md`. With no words, it lists the 10 newest entries. With words, an `awk` paragraph search scores whole entries, so a title is never paired with a neighbour's resume command. It shows one clear match, a short list to choose from, or asks for more detail; as a last resort it searches the raw transcripts.

## Cost (measured)

| Session size | Input tokens | Output tokens | API-equivalent per summary |
|---|---|---|---|
| Small (1 prompt) | 950–1,500 | 160–535 | $0.0003–0.0006 |
| Medium (5–8 prompts) | 2,100–2,800 | 500–735 | $0.0008 |
| Large (200+ prompts, capped) | 8,200–8,800 | 700–900 | $0.002 |

About 30 interactive sessions a month comes to roughly 160 summaries, around $0.30/month API-equivalent.

## Limits and next steps

- **Platform:** Claude Code on macOS, Linux and Windows. Windows needs Git Bash, Claude Code's shell there, and is verified in CI but not yet in a live session. A Codex version could use Codex's own hooks and `codex resume <id>`.
- **Transcript retention:** Claude deletes transcripts after `cleanupPeriodDays` (default 30). Raise that setting if you want old entries to stay resumable.
