#!/usr/bin/env python3
"""Generate AI-powered release notes from git commits via GitHub Models API.

Uses the gh CLI token for authentication — no extra API keys needed.
Falls back to a formatted commit list when AI is unavailable.
"""

import json
import subprocess
import sys

GITHUB_MODELS_URL = "https://models.github.ai/inference/chat/completions"
MODEL = "openai/gpt-4.1-mini"


def get_previous_tag() -> str:
    """Find the most recent reachable tag."""
    r = subprocess.run(
        ["git", "describe", "--tags", "--abbrev=0"],
        capture_output=True,
        text=True,
    )
    return r.stdout.strip() if r.returncode == 0 else ""


def get_commits(since_tag: str) -> str:
    cmd = ["git", "log", "--pretty=format:%s"]
    if since_tag:
        cmd.insert(2, f"{since_tag}..HEAD")
    else:
        cmd.extend(["-50"])
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.stdout.strip()


def get_gh_token() -> str | None:
    try:
        r = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=5)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None


def ai_summarize(commits: str, version: str, since_tag: str) -> str | None:
    """Summarise commits using GitHub Models API (authenticated via gh token)."""
    token = get_gh_token()
    if not token:
        return None

    scope = f"{since_tag}..v{version}" if since_tag else f"up to v{version}"
    prompt = (
        f"Generate concise release notes for Zen IDE v{version} ({scope}).\n"
        "Group changes into sections: **Features**, **Fixes**, **Improvements** "
        "(omit empty sections).\n"
        "Write one short line per item. Skip merge commits, version bumps, "
        "and trivial/duplicate entries.\n"
        "Output ONLY the markdown release notes body — no title, no preamble.\n\n"
        f"Commits:\n{commits}"
    )

    payload = json.dumps(
        {
            "model": MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
        }
    )

    try:
        r = subprocess.run(
            [
                "curl",
                "-sS",
                "--max-time",
                "30",
                GITHUB_MODELS_URL,
                "-H",
                f"Authorization: Bearer {token}",
                "-H",
                "Content-Type: application/json",
                "-d",
                payload,
            ],
            capture_output=True,
            text=True,
            timeout=35,
        )
        if r.returncode == 0:
            data = json.loads(r.stdout)
            content = data["choices"][0]["message"]["content"]
            return content.strip()
    except Exception:
        pass
    return None


def format_fallback(commits: str) -> str:
    """Format raw commits as release notes (fallback)."""
    lines = []
    for line in commits.splitlines():
        s = line.strip()
        if s:
            lines.append(f"- {s}")
    return "\n".join(lines)


def main():
    version = sys.argv[1] if len(sys.argv) > 1 else "0.0.0"
    since_tag = get_previous_tag()
    commits = get_commits(since_tag)

    if not commits:
        print("No new commits since last tag.", file=sys.stderr)
        sys.exit(1)

    notes = ai_summarize(commits, version, since_tag)
    if notes:
        print(notes)
    else:
        print("⚠ AI unavailable — using raw commit log.", file=sys.stderr)
        print(format_fallback(commits))


if __name__ == "__main__":
    main()
