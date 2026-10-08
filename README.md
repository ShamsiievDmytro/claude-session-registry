# claude-session-registry

[![tests](https://github.com/ShamsiievDmytro/claude-session-registry/actions/workflows/test.yml/badge.svg)](https://github.com/ShamsiievDmytro/claude-session-registry/actions/workflows/test.yml)

A searchable logbook of your Claude Code sessions. Every interactive session gets an entry in one Markdown file, `~/.claude/session-registry.md`: a short title, what it was about, where you left off, and the exact command to resume it. Ask `/find-session` and get back to any session, in any project.

## Install

Requirements:
- Claude Code 2.1 or newer, on macOS, Linux or Windows.
- Python 3.9 or newer:
  - macOS and Linux: as `python3`.
  - Windows: from [python.org](https://www.python.org/downloads/windows/), which provides the `py` launcher, or from the Microsoft Store.
- Windows only: [Git for Windows](https://git-scm.com/download/win). Its Git Bash is the shell Claude Code uses on Windows, and the plugin's hooks run in it.
- The `claude` CLI, logged in. Summaries run through your own account.

In Claude Code:

```
/plugin marketplace add ShamsiievDmytro/claude-session-registry
/plugin install session-registry@claude-session-registry
```

Or from a terminal:

```bash
claude plugin marketplace add ShamsiievDmytro/claude-session-registry
claude plugin install session-registry@claude-session-registry
```

Start a new session, and the registry fills in from there.

**Optional: add the sessions you already have.** This summarizes every interactive session whose transcript is still on disk. Claude keeps transcripts for 30 days by default.

```bash
git clone https://github.com/ShamsiievDmytro/claude-session-registry
python3 claude-session-registry/session_registry.py backfill
```

On Windows (PowerShell):

```powershell
git clone https://github.com/ShamsiievDmytro/claude-session-registry
py -3 claude-session-registry\session_registry.py backfill
```

**Uninstall:**

```bash
claude plugin uninstall session-registry@claude-session-registry
```

Uninstalling leaves the registry file at `~/.claude/session-registry.md`; delete it yourself if you don't want it.

## What an entry looks like

```markdown
## Add rate limiting to the public API
- **When:** 2026-10-07 23:41 → last active 2026-10-08 00:30
- **Project:** ~/code/api (branch: rate-limit)
- **Model / app:** opus-5-5 · cli
- **About:** Added a token-bucket limiter to the public endpoints and covered it with integration tests. Chose Redis for shared state across instances.
- **Left off:** In progress - load-test the limiter before enabling it in production.
- **Keywords:** rate limiting, middleware.ts, redis, integration tests
- **Resume:** `cd ~/code/api && claude --resume 6f1c2a9e-1b7d-4c3e-9a51-0e8d2f4b7c11`
```

## Usage

Ask Claude in any session:

```
/find-session
```
Lists your 10 most recent sessions.

```
/find-session rate limiting redis
```
Finds the matching session and prints its resume command:

```bash
cd ~/code/api && claude --resume 6f1c2a9e-1b7d-4c3e-9a51-0e8d2f4b7c11
```

On Windows the command works as-is in PowerShell and Git Bash:

```powershell
cd "C:\Users\you\code\api"; claude --resume 6f1c2a9e-1b7d-4c3e-9a51-0e8d2f4b7c11
```

You don't need the slash command either. "Where did I leave off on the billing refactor?" or "which session was about the flaky login test?" work too. If nothing matches, Claude asks for more detail: the project, a rough date, or files you touched.

Or skip Claude and read the file yourself:

```bash
open ~/.claude/session-registry.md
grep -i -A8 "redis" ~/.claude/session-registry.md
```

On Windows (PowerShell):

```powershell
notepad "$HOME\.claude\session-registry.md"
Select-String -Path "$HOME\.claude\session-registry.md" -Pattern "redis" -Context 0,8
```

## How it works

- **Hooks:** the plugin adds three hooks: after each reply (`Stop`), when a session closes (`SessionEnd`), and before each prompt (`UserPromptSubmit`).
- **Entry creation:** the entry appears after your first reply, so sessions you open and never use leave nothing behind.
- **Summaries:** Haiku writes the title, About, Left off and Keywords. It runs after the first reply, then every 10 prompts, then once more when the session closes. It always runs in the background, so you never wait.
- **Titles in Claude:** the summary title also becomes the session's title in Claude's own `/resume` list. A name you set with `/rename` always wins.
- **What's skipped:** automated runs (Agent SDK, `claude -p`) are ignored, and sessions with no real work, such as a bare login or a greeting, are hidden.
- **Deleted transcripts:** when Claude deletes an old transcript (after 30 days by default), the entry stays as a log line and is marked as no longer resumable. To keep sessions resumable longer, raise `cleanupPeriodDays` in `~/.claude/settings.json`.

More detail: [docs/design.md](docs/design.md).

## Cost

Each summary is one lean Haiku call: no plugins, tools or project memory loaded. It costs about 1k–9k input tokens, roughly $0.0003–$0.002 at API prices. At about 30 interactive sessions a month, that comes to around 160 summaries, roughly $0.30/month API-equivalent, drawn from your normal Claude usage.

## Configuration and files

| File | Purpose |
|---|---|
| `~/.claude/session-registry.md` | The registry. Hand edits are overwritten. |
| `~/.claude/session-registry.log` | Errors, if any. Hooks never interrupt a session. |
| `~/.claude/session-registry.lock` | Keeps parallel sessions from writing at the same time. |

On Windows, `~` is your user folder, for example `C:\Users\you\.claude\session-registry.md`.

To keep the registry somewhere else, set `SESSION_REGISTRY_FILE` in the `env` block of `~/.claude/settings.json`.

**Privacy:** transcripts are read locally. The only thing sent anywhere is the condensed transcript, which goes to Haiku through your own Claude login.

## Limitations

- Claude Code only. Codex support would need its own hooks.
- `claude` must be on `PATH` or at `~/.local/bin/claude` (`claude.exe` on Windows), so the background summaries can run.
- Windows is covered by CI: the tests and the hook launcher run on `windows-latest` with Python 3.9 and 3.13. It hasn't yet been tried in a live Windows Claude Code session, so issue reports are welcome.

## Development

```bash
python3 -m unittest -v test_session_registry
```

The tests are stdlib-only and never call Haiku.

## License

[MIT](LICENSE)
