# claude-session-registry

[![tests](https://github.com/ShamsiievDmytro/claude-session-registry/actions/workflows/test.yml/badge.svg)](https://github.com/ShamsiievDmytro/claude-session-registry/actions/workflows/test.yml)

A logbook of your Claude Code sessions, kept in one file: `~/.claude/session-registry.md`. Every session gets a short title, a few sentences on what you did, where you left off, and the command that resumes it. When you need an old session back, ask `/find-session`.

## Install

You need:
- Claude Code 2.1 or newer, with the `claude` CLI logged in.
- Python 3.9 or newer: `python3` on macOS and Linux; on Windows, the `py` launcher from [python.org](https://www.python.org/downloads/windows/).
- On Windows only, [Git for Windows](https://git-scm.com/download/win), because the hooks run in Git Bash.

In Claude Code:

```
/plugin marketplace add ShamsiievDmytro/claude-session-registry
/plugin install session-registry@claude-session-registry
```

From a terminal, the same commands are `claude plugin marketplace add ShamsiievDmytro/claude-session-registry` and `claude plugin install session-registry@claude-session-registry`.

Then start a new session. Its entry appears after Claude's first reply.

To add the sessions you already have (Claude keeps transcripts for 30 days):

```bash
git clone https://github.com/ShamsiievDmytro/claude-session-registry
python3 claude-session-registry/session_registry.py backfill
```

On Windows, run the second line as `py -3 claude-session-registry\session_registry.py backfill`.

## Find and resume a session

`/find-session` on its own lists your 10 most recent sessions. Add a few words you remember, like `/find-session rate limiting redis`, and Claude finds the session and gives you the command to resume it. A plain question works too: "where did I leave off on the billing refactor?" If nothing matches, Claude asks for the project, a rough date or a file you touched.

Paste the command into a terminal. It's already written for the system the session ran on:

| System | Resume command |
|---|---|
| macOS, Linux | `cd ~/code/api && claude --resume <id>` |
| Windows PowerShell | `cd 'C:\Users\you\code\api'; claude --resume <id>` |

In `cmd.exe`, type it as `cd /d "C:\Users\you\code\api" && claude --resume <id>`.

## Open the registry

The file is plain Markdown, newest session first:

| System | Command |
|---|---|
| macOS | `open ~/.claude/session-registry.md` |
| Linux | `xdg-open ~/.claude/session-registry.md` |
| Windows PowerShell | `Invoke-Item "$HOME\.claude\session-registry.md"` |

If Windows asks which app to use, `notepad "$HOME\.claude\session-registry.md"` works.

An entry looks like this:

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

## Good to know

- Entries keep updating in the background while you work, so you never wait on them.
- The title also shows in Claude's own `/resume` list. If you `/rename` a session, your name wins.
- Runs of `claude -p` and the Agent SDK are skipped, and sessions where nothing happened are hidden.
- Claude deletes transcripts after 30 days by default. The entry stays, but that session can no longer be resumed. Raise `cleanupPeriodDays` in `~/.claude/settings.json` to keep them longer.
- Summaries are written by Haiku through your own login. That's roughly $0.30 a month at API prices for 30 sessions. Nothing else leaves your machine.
- If something goes wrong, look in `~/.claude/session-registry.log`. To keep the registry somewhere else, set `SESSION_REGISTRY_FILE` in the `env` block of `~/.claude/settings.json`.
- Windows is tested in CI but hasn't yet been tried in a live session. Issue reports are welcome.

## Uninstall

```bash
claude plugin uninstall session-registry@claude-session-registry
```

This leaves `~/.claude/session-registry.md` in place; delete it if you don't want it.

## More

How it works: [docs/design.md](docs/design.md). Tests: `python3 -m unittest -v test_session_registry`. License: [MIT](LICENSE).
