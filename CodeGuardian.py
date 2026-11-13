"""CodeGuardian: a precommit code review and ownership platform.

This is a small, dependency-free local review gate. It stores review state in
``.precommit-review.json`` and can be installed as a Git pre-commit hook with:

    python CodeGuardian.py install

The gate checks staged files, hierarchical OWNERS files, readability approval,
duplicate utility names, required LGTM approvals, and review response age.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


STATE_FILE = ".precommit-review.json"
OWNERS_FILE = "OWNERS"
DEFAULT_RESPONSE_HOURS = 24
SOURCE_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rs"}


@dataclass(frozen=True)
class Finding:
    level: str
    message: str


def repository_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(result.stdout.strip())


def load_state(root: Path) -> dict:
    path = root / STATE_FILE
    if not path.exists():
        return {
            "approvals": [],
            "comments": [],
            "response_hours": DEFAULT_RESPONSE_HOURS,
            "readability_approvers": [],
        }
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise SystemExit(f"Cannot read {path}: invalid JSON ({error})") from error
    if not isinstance(state, dict):
        raise SystemExit(f"Cannot read {path}: the top-level value must be an object")
    return state


def save_state(root: Path, state: dict) -> None:
    (root / STATE_FILE).write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def staged_files(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return [root / line for line in result.stdout.splitlines() if line]


def owners_for(path: Path, root: Path) -> set[str]:
    """Return owners from the nearest OWNERS files, from root to the file."""
    relative = path.relative_to(root)
    directories = [root]
    directories.extend(root / part for part in relative.parts[:-1])
    owners: set[str] = set()
    for directory in directories:
        owners_path = directory / OWNERS_FILE
        if not owners_path.exists():
            continue
        for line in owners_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                owners.add(line)
    return owners


def changed_source_symbols(path: Path) -> set[str]:
    if path.suffix not in SOURCE_EXTENSIONS or not path.exists():
        return set()
    symbols = set()
    pattern = re.compile(
        r"^\s*(?:def|function|func|class|async\s+def)\s+([A-Za-z_]\w*)"
    )
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = pattern.match(line)
        if match:
            symbols.add(match.group(1))
    return symbols


def repository_symbols(root: Path, excluded: set[Path]) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for path in root.rglob("*"):
        if (
            path.is_file()
            and path not in excluded
            and path.suffix in SOURCE_EXTENSIONS
            and ".git" not in path.parts
        ):
            for symbol in changed_source_symbols(path):
                found.setdefault(symbol, path)
    return found


def review_findings(root: Path, state: dict, reviewer: str | None) -> list[Finding]:
    files = staged_files(root)
    if not files:
        return [Finding("error", "No staged files were found.")]

    findings: list[Finding] = []
    now = datetime.now(timezone.utc)
    response_hours = state.get("response_hours", DEFAULT_RESPONSE_HOURS)
    for comment in state.get("comments", []):
        if not isinstance(comment, dict) or not comment.get("required"):
            continue
        if comment.get("resolved"):
            continue
        try:
            created = datetime.fromisoformat(comment["created_at"])
        except (KeyError, TypeError, ValueError):
            findings.append(Finding("error", "A required comment has an invalid timestamp."))
            continue
        age_hours = (now - created).total_seconds() / 3600
        if age_hours > response_hours:
            findings.append(
                Finding(
                    "warning",
                    f"Required comment from {comment.get('author', 'unknown')} "
                    f"has waited {age_hours:.1f} hours (target: {response_hours} hours).",
                )
            )
    required_owners: set[str] = set()
    for path in files:
        owners = owners_for(path, root)
        if not owners:
            findings.append(
                Finding("error", f"{path.relative_to(root)} has no OWNERS file.")
            )
        required_owners.update(owners)

    approved = {
        item.get("reviewer")
        for item in state.get("approvals", [])
        if isinstance(item, dict) and item.get("lgtm") is True
    }
    missing_owners = sorted(required_owners - approved)
    if missing_owners:
        findings.append(
            Finding("error", "Missing LGTM approval from: " + ", ".join(missing_owners))
        )

    readability = set(state.get("readability_approvers", []))
    if readability and not readability.intersection(approved):
        findings.append(
            Finding("error", "A readability approver must sign off: "
                   + ", ".join(sorted(readability)))
        )

    changed_symbols = {
        symbol
        for path in files
        for symbol in changed_source_symbols(path)
    }
    existing = repository_symbols(root, set(files))
    duplicates = sorted(symbol for symbol in changed_symbols if symbol in existing)
    if duplicates:
        findings.append(
            Finding(
                "warning",
                "Possible duplicate symbols: "
                + ", ".join(f"{symbol} ({existing[symbol].relative_to(root)})"
                            for symbol in duplicates),
            )
        )

    if reviewer:
        findings.append(
            Finding("info", f"Review requested from {reviewer} for {len(files)} file(s).")
        )
    return findings


def print_findings(findings: Iterable[Finding]) -> bool:
    failed = False
    for finding in findings:
        print(f"[{finding.level.upper()}] {finding.message}")
        failed |= finding.level == "error"
    return failed


def add_approval(root: Path, reviewer: str) -> None:
    state = load_state(root)
    approvals = state.setdefault("approvals", [])
    approvals[:] = [
        item for item in approvals
        if not (isinstance(item, dict) and item.get("reviewer") == reviewer)
    ]
    approvals.append(
        {
            "reviewer": reviewer,
            "lgtm": True,
            "approved_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    save_state(root, state)
    print(f"LGTM recorded for {reviewer}.")


def add_comment(root: Path, author: str, message: str, required: bool) -> None:
    state = load_state(root)
    state.setdefault("comments", []).append(
        {
            "author": author,
            "message": message,
            "required": required,
            "resolved": not required,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    save_state(root, state)
    print("Comment recorded.")


def resolve_comment(root: Path, index: int) -> None:
    state = load_state(root)
    comments = state.get("comments", [])
    if index < 0 or index >= len(comments):
        raise SystemExit(f"Comment index must be between 0 and {len(comments) - 1}.")
    if not isinstance(comments[index], dict):
        raise SystemExit(f"Comment {index} is not valid review data.")
    comments[index]["resolved"] = True
    comments[index]["resolved_at"] = datetime.now(timezone.utc).isoformat()
    save_state(root, state)
    print(f"Comment {index} resolved.")


def configure_readability(root: Path, approvers: list[str]) -> None:
    state = load_state(root)
    state["readability_approvers"] = sorted(set(approvers))
    save_state(root, state)
    print("Readability approvers: " + ", ".join(state["readability_approvers"]))


def install_hook(root: Path) -> None:
    hook = root / ".git" / "hooks" / "pre-commit"
    hook.write_text(
        "#!/bin/sh\n"
        f'python "{Path(__file__).resolve()}" check\n',
        encoding="utf-8",
    )
    print(f"Installed pre-commit hook at {hook}.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("check", help="gate the staged changes")
    subparsers.add_parser("install", help="install the Git pre-commit hook")

    approve = subparsers.add_parser("approve", help="record a peer LGTM")
    approve.add_argument("reviewer", help="reviewer's username")

    comment = subparsers.add_parser("comment", help="add a review comment")
    comment.add_argument("author")
    comment.add_argument("message")
    comment.add_argument("--required", action="store_true")

    resolve = subparsers.add_parser("resolve", help="resolve a review comment")
    resolve.add_argument("index", type=int, help="zero-based comment index")

    readability = subparsers.add_parser(
        "readability", help="configure language readability approvers"
    )
    readability.add_argument("approvers", nargs="+", help="approved usernames")

    args = parser.parse_args()
    try:
        root = repository_root()
    except subprocess.CalledProcessError:
        print("This command must be run inside a Git repository.", file=sys.stderr)
        return 2

    if args.command == "install":
        install_hook(root)
        return 0
    if args.command == "approve":
        add_approval(root, args.reviewer)
        return 0
    if args.command == "comment":
        add_comment(root, args.author, args.message, args.required)
        return 0
    if args.command == "resolve":
        resolve_comment(root, args.index)
        return 0
    if args.command == "readability":
        configure_readability(root, args.approvers)
        return 0

    failed = print_findings(review_findings(root, load_state(root), None))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())