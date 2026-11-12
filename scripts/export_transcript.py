"""Turn the app's raw session export into a readable, redacted conversation history.

Usage:
  uv run python scripts/export_transcript.py <path to transcript.jsonl from the session export>
  -> submission/conversation-history.md

What is kept, verbatim and in order: every message Archi sent, every reply the assistant wrote,
and one line per tool action the assistant took (which tool, and its own one-line description).
What is left out: tool outputs (file contents, logs), the assistant's hidden reasoning, and the
app's system context blocks; none of these are part of the conversation as it was seen.
What is redacted: the Groq organisation ID, any API key, and Archi's email address.
Nothing else is edited: typos and mistakes stay, including the assistant's.
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "submission" / "conversation-history.md"

REDACT = [
    (re.compile(r"gsk_[A-Za-z0-9]{10,}"), "gsk_REDACTED"),
    (re.compile(r"org_[a-z0-9]{10,}"), "org_REDACTED"),
    (re.compile(r"n?archi\.?kanungo2004@gmail\.com", re.I), "[email redacted]"),
]
SYSTEM_BLOCK = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
PASTE_TAG = re.compile(r"</?pasted_content[^>]*>")


def clean(text: str) -> str:
    text = SYSTEM_BLOCK.sub("", text)
    text = PASTE_TAG.sub("", text)
    for rx, rep in REDACT:
        text = rx.sub(rep, text)
    return text.strip()


def when(ts: str | None) -> str:
    if not ts:
        return ""
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%d %b %H:%M UTC")
    except ValueError:
        return ts


def tool_line(block: dict) -> str:
    inp = block.get("input") or {}
    name = block.get("name", "tool").split("__")[-1]
    what = inp.get("description") or inp.get("file_path") or inp.get("pattern") or inp.get("query") or ""
    if not what and name in ("update_plan", "wrap_up", "mark_chapter"):
        return ""  # app bookkeeping, not an action on the project
    return f"- *[{name}]* {clean(str(what))[:160]}"


def main(path: str) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    out = ["# The Relay: conversation history with the assistant", "",
           "Exported from the Claude desktop app (Claude Code) session for this project, unedited except that the "
           "Groq organisation ID, API keys and my email address are redacted. Kept: every message I sent, every "
           "reply the assistant wrote, and one line per tool action it took. Not shown: tool outputs and the "
           "assistant's hidden reasoning (not visible in the conversation). Long sessions were auto-summarised by "
           "the app when context ran out; those summaries appear as they were inserted.", ""]
    n_user = n_asst = n_tools = 0
    pending_tools: list[str] = []

    def flush_tools():
        nonlocal pending_tools
        if pending_tools:
            out.extend(pending_tools + [""])
            pending_tools = []

    for line in open(path, encoding="utf-8"):
        r = json.loads(line)
        t = r.get("type")
        if t not in ("user", "assistant") or r.get("isSidechain"):
            continue
        content = (r.get("message") or {}).get("content")
        blocks = [{"type": "text", "text": content}] if isinstance(content, str) else (content or [])
        if t == "user":
            texts = [clean(b.get("text", "")) for b in blocks if b.get("type") == "text"]
            texts = [x for x in texts if x and not x.startswith("[Request interrupted")]
            if not texts:
                continue  # tool results only
            flush_tools()
            body = "\n\n".join(texts)
            # Not everything in the user role was typed by Archi: label app events honestly.
            m = re.search(r"<summary>(.*?)</summary>", body, re.S)
            if "<task-notification>" in body:
                summary = clean(m.group(1)) if m else "background task finished"
                out += [f"*[App event · {when(r.get('timestamp'))}] {summary}*", ""]
                continue
            if body.startswith("This session is being continued from a previous conversation"):
                out += [f"## App: automatic context summary · {when(r.get('timestamp'))}", "",
                        "*(The app ran out of context and inserted this summary of the conversation so far. "
                        "It is reproduced as inserted.)*", "", body, ""]
                continue
            n_user += 1
            out += [f"## Archi · {when(r.get('timestamp'))}", "", body, ""]
        else:
            for b in blocks:
                if b.get("type") == "text" and clean(b.get("text", "")):
                    flush_tools()
                    n_asst += 1
                    out += [f"### Assistant · {when(r.get('timestamp'))}", "", clean(b["text"]), ""]
                elif b.get("type") == "tool_use":
                    tl = tool_line(b)
                    if tl:
                        n_tools += 1
                        pending_tools.append(tl)
    flush_tools()
    text = "\n".join(out)
    for rx, _ in REDACT:  # belt and braces
        assert not rx.search(text), rx.pattern
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(f"{OUT}: {n_user} messages from Archi, {n_asst} assistant replies, {n_tools} tool actions, "
          f"{len(text.split()):,} words")


if __name__ == "__main__":
    main(sys.argv[1])
