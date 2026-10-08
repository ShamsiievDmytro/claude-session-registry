"""Tests for session_registry.py. Run: python3 -m unittest -v test_session_registry"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

TMP = Path(tempfile.mkdtemp())
os.environ["SESSION_REGISTRY_FILE"] = str(TMP / "registry.md")
os.environ["SESSION_REGISTRY_PROJECTS"] = str(TMP / "projects")
os.environ.pop("SESSION_REGISTRY_CHILD", None)
os.environ["TZ"] = "UTC"
if hasattr(time, "tzset"):  # not on Windows; CI runners there use UTC anyway
    time.tzset()
sys.path.insert(0, str(Path(__file__).parent))
import session_registry as sr  # noqa: E402

PROJECT_DIR = TMP / "projects" / "-tmp-proj"
SUMMARY = {"title": "Fix the login flow.", "about": "Fixed\nthe login flow.", "left_off": "Done - nothing",
           "keywords": ["login", "auth"], "trivial": False}


def row(kind, sid, ts, entrypoint="cli", cwd="/tmp/proj", **msg):
    return {"type": kind, "sessionId": sid, "cwd": cwd, "gitBranch": "main",
            "entrypoint": entrypoint, "timestamp": ts, "message": msg}


def make_transcript(sid, prompts, day=1, entrypoint="cli", start=0, cwd="/tmp/proj"):
    """Append `prompts` prompt/reply pairs dated 2026-10-<day> 10:<i>; return the transcript path."""
    PROJECT_DIR.mkdir(parents=True, exist_ok=True)
    path = PROJECT_DIR / f"{sid}.jsonl"
    with open(path, "a") as fh:
        for i in range(start, start + prompts):
            ts = f"2026-10-{day:02d}T10:{i:02d}:00Z"
            fh.write(json.dumps(row("user", sid, ts, entrypoint, cwd, role="user", content=f"prompt {i}")) + "\n")
            fh.write(json.dumps(row("assistant", sid, ts, entrypoint, cwd, role="assistant", model="claude-opus-5-5",
                                    content=[{"type": "text", "text": f"reply {i}"}])) + "\n")
    return str(path)


def add_line(path, obj):
    with open(path, "a") as fh:
        fh.write((obj if isinstance(obj, str) else json.dumps(obj)) + "\n")


class Base(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(TMP / "projects", ignore_errors=True)
        for p in (sr.REGISTRY, sr.LOG):
            p.unlink(missing_ok=True)
        self.summary = dict(SUMMARY)
        self.spawned = []
        for name, fake in (("call_haiku", lambda text: dict(self.summary)),
                           ("spawn", lambda sid, path: self.spawned.append(sid)),
                           ("WINDOWS", False)):
            patcher = mock.patch.object(sr, name, fake, create=True)
            patcher.start()
            self.addCleanup(patcher.stop)


class TranscriptTest(Base):
    def test_reads_prompts_model_and_metadata(self):
        p = make_transcript("s1", 3)
        add_line(p, "not json")
        add_line(p, row("assistant", "s1", "2026-10-01T10:05:00Z", role="assistant", model="<synthetic>",
                        content=[{"type": "text", "text": "Session limit reached"}]))
        add_line(p, row("user", "s1", "2026-10-01T10:06:00Z", role="user",
                        content=[{"type": "tool_result", "content": "ok"}]))
        add_line(p, {"type": "custom-title", "customTitle": "Desktop auto title", "sessionId": "s1"})
        t = sr.read_transcript(p)
        self.assertEqual(t["prompts"], 3)
        self.assertEqual(t["model"], "claude-opus-5-5")
        self.assertEqual((t["cwd"], t["branch"], t["entrypoint"]), ("/tmp/proj", "main", "cli"))
        self.assertEqual((t["first_ts"], t["last_ts"]), ("2026-10-01T10:00:00Z", "2026-10-01T10:06:00Z"))
        self.assertEqual(t["custom_title"], "Desktop auto title")

    def test_injected_notifications_are_not_prompts(self):
        p = make_transcript("n", 2)
        add_line(p, row("user", "n", "2026-10-01T10:05:00Z", role="user", content="<task-notification>\n<task-id>x</task-id>"))
        add_line(p, row("user", "n", "2026-10-01T10:06:00Z", role="user", content="<local-command-stdout>ok</local-command-stdout>"))
        compact = row("user", "n", "2026-10-01T10:07:00Z", role="user", content="This session is being continued...")
        compact["isCompactSummary"] = True
        add_line(p, compact)
        t = sr.read_transcript(p)
        self.assertEqual(t["prompts"], 2)
        self.assertNotIn("task-notification", "\n".join(t["lines"]))

    def test_skip_sdk_and_empty_sessions(self):
        self.assertTrue(sr.skip(sr.read_transcript(make_transcript("sdk", 2, entrypoint="sdk-py"))))
        empty = PROJECT_DIR / "empty.jsonl"
        empty.write_text("")
        self.assertTrue(sr.skip(sr.read_transcript(empty)))
        self.assertFalse(sr.skip(sr.read_transcript(make_transcript("cli", 1))))

    def test_condense_keeps_start_and_end_of_long_sessions(self):
        p = make_transcript("big", 1)
        for i in range(40):
            add_line(p, row("user", "big", f"2026-10-01T11:{i:02d}:00Z", role="user", content=f"END{i} " + "y" * 1400))
        text = sr.condense(sr.read_transcript(p))
        self.assertTrue(text.startswith("Project: /tmp/proj\nBranch: main\n"))
        self.assertIn("USER: prompt 0", text)
        self.assertIn("END39", text)
        self.assertIn("\n[...]\n", text)
        self.assertLess(len(text), sr.CAP + 100)


class RegistryFileTest(Base):
    def entry(self, sid, day, **kw):
        return sr.new_entry(sid, sr.read_transcript(make_transcript(sid, 1, day=day, **kw)))

    def test_round_trip_and_newest_first(self):
        with sr.locked() as entries:
            entries += [self.entry("old", 1), self.entry("new", 3)]
        with sr.locked() as entries:
            entries.append(self.entry("mid", 2))  # a backfilled entry lands in its sorted position
        loaded = sr.load()
        self.assertEqual([e["id"] for e in loaded], ["new", "mid", "old"])
        self.assertEqual(loaded[0]["title"], sr.PENDING)
        self.assertEqual(loaded[0]["f"]["When"], "2026-10-03 10:00 → last active 2026-10-03 10:00")
        self.assertEqual(loaded[0]["f"]["Project"], "/tmp/proj (branch: main)")
        self.assertEqual(loaded[0]["f"]["Model / app"], "opus-5-5 · cli")
        self.assertEqual(loaded[0]["f"]["Resume"], "`cd /tmp/proj && claude --resume new`")
        self.assertTrue(sr.REGISTRY.read_text(encoding="utf-8").startswith(sr.HEADER))

    def test_refresh_updates_last_active_but_keeps_summary(self):
        p = make_transcript("a", 1, day=1)
        with sr.locked() as entries:
            e = sr.new_entry("a", sr.read_transcript(p))
            e["f"]["About"] = "Kept."
            entries.append(e)
        make_transcript("a", 1, day=4, start=1)
        with sr.locked() as entries:
            sr.refresh(sr.find(entries, "a"), sr.read_transcript(p))
        e = sr.find(sr.load(), "a")
        self.assertEqual(e["f"]["When"], "2026-10-01 10:00 → last active 2026-10-04 10:01")
        self.assertEqual(e["f"]["About"], "Kept.")

    def test_windows_resume_command_works_in_powershell(self):
        with mock.patch.object(sr, "WINDOWS", True):
            e = self.entry("win", 1, cwd="C:\\Users\\me\\My Proj")
        self.assertEqual(e["f"]["Resume"], '`cd "C:\\Users\\me\\My Proj"; claude --resume win`')

    @unittest.skipIf(os.name == "nt", "POSIX home-directory paths")
    def test_resume_command_quotes_paths_with_spaces(self):
        e = self.entry("sp", 1, cwd=str(sr.HOME / "My Proj"))
        self.assertEqual(e["f"]["Resume"], "`cd ~/'My Proj' && claude --resume sp`")
        self.assertEqual(e["f"]["Project"], "~/My Proj (branch: main)")

    def test_deleted_transcript_is_flagged_stale(self):
        with sr.locked() as entries:
            entries += [self.entry("gone", 1), self.entry("here", 2)]
        os.remove(PROJECT_DIR / "gone.jsonl")
        with sr.locked():
            pass
        loaded = {e["id"]: e for e in sr.load()}
        self.assertEqual(loaded["gone"]["f"]["Resume"], sr.STALE)
        self.assertIn("claude --resume here", loaded["here"]["f"]["Resume"])

    def test_missing_projects_dir_never_flags_everything(self):
        with sr.locked() as entries:
            entries.append(self.entry("x", 1))
        shutil.rmtree(TMP / "projects")
        with sr.locked():
            pass
        self.assertIn("claude --resume x", sr.load()[0]["f"]["Resume"])

    def test_parallel_writers_lose_nothing(self):
        for i in range(6):
            make_transcript(f"p{i}", 1, day=1 + i)
        code = ("import sys, session_registry as sr\n"
                "with sr.locked() as es:\n"
                "    es.append(sr.new_entry(sys.argv[1], sr.read_transcript(sys.argv[2])))\n")
        procs = [subprocess.Popen([sys.executable, "-c", code, f"p{i}", str(PROJECT_DIR / f"p{i}.jsonl")],
                                  cwd=Path(__file__).parent) for i in range(6)]
        for proc in procs:
            self.assertEqual(proc.wait(), 0)
        self.assertEqual(sorted(e["id"] for e in sr.load()), [f"p{i}" for i in range(6)])


class SummaryTest(Base):
    def test_parse_summary_strips_fences_and_requires_keys(self):
        self.assertEqual(sr.parse_summary("```json\n" + json.dumps(SUMMARY) + "\n```"), SUMMARY)
        with self.assertRaises(ValueError):
            sr.parse_summary('{"title": "x"}')
        with self.assertRaises(ValueError):
            sr.parse_summary("not json")

    def test_summary_fills_entry_as_single_lines(self):
        p = make_transcript("s", 1)
        sr.summarize("s", p)
        e = sr.find(sr.load(), "s")
        self.assertEqual(e["title"], "Fix the login flow")          # trailing period dropped
        self.assertEqual(e["f"]["About"], "Fixed the login flow.")   # newline collapsed
        self.assertEqual(e["f"]["Left off"], "Done - nothing")
        self.assertEqual(e["f"]["Keywords"], "login, auth")
        self.assertEqual(e["turns"], 1)

    def test_failed_summary_leaves_registry_unchanged(self):
        p = make_transcript("s", 1)
        with sr.locked() as entries:
            entries.append(sr.new_entry("s", sr.read_transcript(p)))
        before = sr.REGISTRY.read_text(encoding="utf-8")
        with mock.patch.object(sr, "call_haiku", side_effect=ValueError("bad json")):
            with self.assertRaises(ValueError):
                sr.summarize("s", p)
        self.assertEqual(sr.REGISTRY.read_text(encoding="utf-8"), before)

    def test_trivial_collapses_then_restores(self):
        p = make_transcript("t", 1)
        self.summary["trivial"] = True
        sr.summarize("t", p)
        body = sr.REGISTRY.read_text(encoding="utf-8")[len(sr.HEADER):]
        self.assertIn("turns:1 pushed:- trivial -->", body)
        self.assertNotIn("## ", body)
        self.summary["trivial"] = False
        make_transcript("t", 1, start=1)
        sr.summarize("t", p)
        e = sr.find(sr.load(), "t")
        self.assertFalse(e["trivial"])
        self.assertEqual(e["title"], "Fix the login flow")
        self.assertIn("claude --resume t", e["f"]["Resume"])

    def test_trivial_verdict_ignored_for_long_sessions_and_logged(self):
        sr.summarize("long", make_transcript("long", 5))
        self.summary["trivial"] = True
        sr.summarize("long", PROJECT_DIR / "long.jsonl")
        e = sr.find(sr.load(), "long")
        self.assertFalse(e["trivial"])
        self.assertEqual(e["title"], "Fix the login flow")
        sr.summarize("short", make_transcript("short", 2))
        self.assertTrue(sr.find(sr.load(), "short")["trivial"])
        self.assertIn("collapsed trivial session short", sr.LOG.read_text(encoding="utf-8"))

    def test_overlapping_summary_does_not_fake_a_rename(self):
        p = make_transcript("o", 1)
        add_line(p, {"type": "custom-title", "customTitle": "Desktop auto title", "sessionId": "o"})
        sr.summarize("o", p)  # entry exists, nothing pushed yet

        def slow_haiku(text):  # while this summary runs, another one lands and its title gets pushed
            with sr.locked() as entries:
                sr.find(entries, "o")["pushed"] = sr.digest("Fix the login flow")
            return dict(self.summary)

        with mock.patch.object(sr, "call_haiku", slow_haiku):
            sr.summarize("o", p)
        e = sr.find(sr.load(), "o")
        self.assertNotEqual(e["pushed"], "user")
        self.assertEqual(e["title"], "Fix the login flow")

    def test_user_rename_wins_but_desktop_auto_title_does_not(self):
        p = make_transcript("r", 1)
        add_line(p, {"type": "custom-title", "customTitle": "Desktop auto title", "sessionId": "r"})
        sr.summarize("r", p)
        self.assertEqual(sr.find(sr.load(), "r")["title"], "Fix the login flow")  # nothing pushed yet
        with sr.locked() as entries:  # simulate the prompt hook having pushed our title
            sr.find(entries, "r")["pushed"] = sr.digest("Fix the login flow")
        add_line(p, {"type": "custom-title", "customTitle": "Fix the login flow", "sessionId": "r"})
        self.summary["title"] = "Fix login and logout"
        sr.summarize("r", p)
        self.assertEqual(sr.find(sr.load(), "r")["title"], "Fix login and logout")  # our own title is no rename
        add_line(p, {"type": "custom-title", "customTitle": "My auth work", "sessionId": "r"})
        sr.summarize("r", p)
        e = sr.find(sr.load(), "r")
        self.assertEqual((e["title"], e["pushed"]), ("My auth work", "user"))


def hook(sid, path):
    return {"session_id": sid, "transcript_path": path, "cwd": "/tmp/proj", "hook_event_name": "Stop"}


def run_main(args, payload=None):
    """Run main() with a hook payload on stdin; return what it printed."""
    out = io.StringIO()
    with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload or {}))), redirect_stdout(out):
        sr.main(["session_registry.py", *args])
    return out.getvalue()


class HookTest(Base):
    def test_first_reply_creates_entry_and_starts_summary(self):
        p = make_transcript("h", 1)
        self.assertEqual(run_main(["stop"], hook("h", p)), "")
        self.assertEqual(sr.find(sr.load(), "h")["title"], sr.PENDING)
        self.assertEqual(self.spawned, ["h"])

    def test_summary_cadence_every_10_prompts_and_on_close(self):
        p = make_transcript("c", 1)
        run_main(["stop"], hook("c", p))
        sr.summarize("c", p)                     # turns = 1
        self.spawned.clear()
        make_transcript("c", 9, start=1)         # 10 prompts: 9 since the summary
        run_main(["stop"], hook("c", p))
        self.assertEqual(self.spawned, [])
        make_transcript("c", 1, start=10)        # 11 prompts: 10 since the summary
        run_main(["stop"], hook("c", p))
        self.assertEqual(self.spawned, ["c"])
        sr.summarize("c", p)                     # turns = 11
        self.spawned.clear()
        run_main(["session-end"], hook("c", p))
        self.assertEqual(self.spawned, [])       # nothing new since the last summary
        make_transcript("c", 1, start=11)
        run_main(["session-end"], hook("c", p))
        self.assertEqual(self.spawned, ["c"])

    def test_failed_first_summary_retries_on_next_reply(self):
        p = make_transcript("f", 1)
        run_main(["stop"], hook("f", p))
        make_transcript("f", 1, start=1)
        run_main(["stop"], hook("f", p))         # turns still 0: retry
        self.assertEqual(self.spawned, ["f", "f"])

    def test_trivial_session_is_not_resummarized_every_reply(self):
        p = make_transcript("tv", 1)
        self.summary["trivial"] = True
        run_main(["stop"], hook("tv", p))
        sr.summarize("tv", p)
        self.spawned.clear()
        make_transcript("tv", 1, start=1)
        run_main(["stop"], hook("tv", p))
        self.assertEqual(self.spawned, [])

    def test_sdk_sessions_and_summarizer_child_are_ignored(self):
        run_main(["stop"], hook("sdk", make_transcript("sdk", 1, entrypoint="sdk-py")))
        q = make_transcript("kid", 1)
        with mock.patch.dict(os.environ, {"SESSION_REGISTRY_CHILD": "1"}):
            run_main(["stop"], hook("kid", q))
        self.assertEqual(sr.load(), [])
        self.assertEqual(self.spawned, [])

    def test_title_pushed_once_per_new_title_and_never_after_rename(self):
        p = make_transcript("t", 1)
        self.assertEqual(run_main(["prompt"], hook("t", p)), "")     # unknown session: no output
        run_main(["stop"], hook("t", p))
        self.assertEqual(run_main(["prompt"], hook("t", p)), "")     # pending title: no output
        sr.summarize("t", p)
        out = json.loads(run_main(["prompt"], hook("t", p)))
        self.assertEqual(out, {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                                      "sessionTitle": "Fix the login flow"}})
        self.assertEqual(run_main(["prompt"], hook("t", p)), "")     # same title: not pushed again
        add_line(p, {"type": "custom-title", "customTitle": "My own name", "sessionId": "t"})
        sr.summarize("t", p)
        self.assertEqual(run_main(["prompt"], hook("t", p)), "")     # user renamed: never push again

    def test_errors_are_logged_never_printed(self):
        p = make_transcript("s", 1)
        with sr.locked() as entries:
            entries.append(sr.new_entry("s", sr.read_transcript(p)))
        before = sr.REGISTRY.read_text(encoding="utf-8")
        with mock.patch.object(sr, "call_haiku", side_effect=ValueError("bad json")):
            self.assertEqual(run_main(["summarize", "s", p]), "")
        self.assertEqual(sr.REGISTRY.read_text(encoding="utf-8"), before)
        self.assertIn("bad json", sr.LOG.read_text(encoding="utf-8"))
        self.assertEqual(run_main(["prompt"], {"no": "session_id"}), "")   # malformed hook input
        self.assertIn("KeyError", sr.LOG.read_text(encoding="utf-8"))

    def test_unsafe_session_id_never_reaches_a_resume_command(self):
        p = make_transcript("ok", 1)
        with self.assertRaises(ValueError):
            sr.base_fields("x; rm -rf ~", sr.read_transcript(p))
        run_main(["stop"], hook("$(touch pwned)", p))
        self.assertEqual(sr.load(), [])
        self.assertEqual(self.spawned, [])
        self.assertIn("unsafe session id", sr.LOG.read_text(encoding="utf-8"))

    def test_backfill_adds_interactive_sessions_only(self):
        make_transcript("b1", 2, day=1)
        make_transcript("b2", 1, day=2)
        make_transcript("bot", 3, entrypoint="sdk-cli")
        out = run_main(["backfill"])
        self.assertEqual([e["id"] for e in sr.load()], ["b2", "b1"])
        self.assertIn("added b1", out)
        run_main(["backfill"])
        self.assertEqual(len(sr.load()), 2)


if __name__ == "__main__":
    unittest.main()
