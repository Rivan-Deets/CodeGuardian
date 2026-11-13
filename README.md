# CodeGuardian

CodeGuardian is a precommit code review and ownership platform.

This project is a small, dependency-free Python tool that checks staged
changes before they are committed to Git. It helps teams enforce code
ownership, peer review, readability review, and review-comment tracking.

The tool is inspired by software engineering practices such as:

- Requiring an explicit **LGTM** ("Looks Good To Me") approval
- Assigning reviewers through directory-level `OWNERS` files
- Using language experts as readability approvers
- Warning about possible duplicate functions and classes
- Tracking required review comments and response time

## Requirements

- Python 3.10 or newer
- Git
- A Git repository

The tool uses only Python's standard library. No packages need to be installed.

## Installation

Copy `CodeGuardian.py` into your project, or run it directly from this directory.
From inside the Git repository that you want to protect, install the Git hook:

```bash
python CodeGuardian.py install
```

This creates a hook at:

```text
.git/hooks/pre-commit
```

The hook automatically runs the review check before each commit.

## How It Works

1. The tool finds the current Git repository.
2. It finds files staged for the next commit.
3. It reads `OWNERS` files for the changed files.
4. It checks that all required owners recorded an LGTM approval.
5. It checks whether a readability approver signed off.
6. It warns about possible duplicate function and class names.
7. It reports overdue required review comments.
8. It returns an exit code that Git uses to allow or block the commit.

An error blocks the commit. A warning is reported but does not block the
commit.

## `OWNERS` Files

An `OWNERS` file contains one username per line:

```text
alice
bob
```

Comments and blank lines are allowed:

```text
# Python code owners
alice

bob
```

The tool searches the directory containing a changed file and its parent
directories. Owners found in those files are required to approve the change.

## Commands

### Check staged changes

```bash
python CodeGuardian.py check
```

This is the main review command. It checks the files currently staged with
`git add`.

Example failure:

```text
[ERROR] Missing LGTM approval from: alice
```

### Record an LGTM approval

```bash
python CodeGuardian.py approve alice
```

This records Alice's approval in `.precommit-review.json`.

LGTM means **Looks Good To Me**. It indicates that a reviewer examined the
change and approves it.

### Configure readability approvers

```bash
python CodeGuardian.py readability bob carol
```

At least one configured readability approver must record an approval:

```bash
python CodeGuardian.py approve bob
```

### Add an informational comment

```bash
python CodeGuardian.py comment alice "This could be simplified."
```

Informational comments do not need to be resolved.

### Add a required comment

```bash
python CodeGuardian.py comment alice "Please add a test." --required
```

Required comments remain unresolved until someone resolves them. The tool
reports a warning when a required comment has waited longer than the configured
24-hour response target.

### Resolve a comment

Comments are numbered starting at zero. To resolve the first comment:

```bash
python CodeGuardian.py resolve 0
```

### Install the Git hook

```bash
python CodeGuardian.py install
```

## Example Workflow

Create an `OWNERS` file:

```bash
echo alice > OWNERS
```

Create or change a source file and stage the changes:

```bash
git add OWNERS example.py
```

Run the check:

```bash
python CodeGuardian.py check
```

If approval is missing, the tool reports an error:

```text
[ERROR] Missing LGTM approval from: alice
```

Record the approval and check again:

```bash
python CodeGuardian.py approve alice
python CodeGuardian.py check
```

The check passes when all required review conditions are satisfied.

## Review State

The tool stores local review information in:

```text
.precommit-review.json
```

The file may contain:

- LGTM approvals
- Approval timestamps
- Review comments
- Comment resolution status
- The response-time target
- Readability approvers

Because this file contains local review state, teams should decide whether it
belongs in version control or should be managed separately.

## Exit Codes

The command returns these exit codes:

- `0` — all required checks passed
- `1` — a review requirement failed
- `2` — the command was used incorrectly or outside a Git repository

Git uses a nonzero exit code from the precommit hook to block a commit.

## What the Tool Checks

### Required checks

- At least one file is staged
- Each changed file has an `OWNERS` file
- All required owners have approved
- A configured readability approver has approved
