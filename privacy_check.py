"""Fail if personal or secret-looking data reaches tracked files.

Scope is ``git ls-files`` by default -- untracked and ignored files such as
``.env`` are deliberately skipped. Use ``--all`` to sweep the working tree
before a first commit.

    python privacy_check.py
    python privacy_check.py --all
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

PATTERNS = {
    "windows home path": re.compile(r"[A-Za-z]:[\\/]{1,2}Users[\\/]+[A-Za-z0-9._-]+"),
    "posix home path": re.compile(r"/(?:home|Users)/[A-Za-z0-9._-]{2,}"),
    "email address": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.[A-Za-z]{2,}"),
    "aws access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "github token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    "api key literal": re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    "private key block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
}

SKIP_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf",
    ".zip", ".gz", ".woff", ".woff2", ".pyc",
}
SKIP_NAMES = {".env"}


def tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, check=True
    )
    return [Path(line) for line in out.stdout.splitlines() if line.strip()]


def working_tree() -> list[Path]:
    root = Path.cwd()
    files = []
    for path in root.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        files.append(path.relative_to(root))
    return files


def scan(files: list[Path]) -> int:
    hits = 0
    for rel in files:
        if rel.suffix.lower() in SKIP_SUFFIXES or rel.name in SKIP_NAMES:
            continue
        try:
            text = rel.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for label, pattern in PATTERNS.items():
                match = pattern.search(line)
                if match:
                    hits += 1
                    print(f"{rel}:{lineno}: {label}: {match.group(0)}")
    return hits


def main(argv: list[str]) -> int:
    files = working_tree() if "--all" in argv else tracked_files()
    hits = scan(files)
    if hits:
        print(f"\n{hits} finding(s). Remove them or amend the pattern before publishing.")
        return 1
    print(f"clean: {len(files)} file(s) scanned, no matches")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
