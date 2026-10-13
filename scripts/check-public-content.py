#!/usr/bin/env python3
"""Check public source or the exact Git index; report locations, never matched values."""
import argparse
import hashlib
import json
import posixpath
import re
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
POLICY = "docs/public-documents.json"
PRIVATE_PARTS = {".local", ".agents", ".codex", "node_modules", ".venv", "__pycache__"}
DOCUMENT_SUFFIXES = {".md", ".mdx", ".markdown", ".rst", ".adoc", ".txt", ".pdf", ".doc", ".docx", ".odt", ".rtf"}
PROCESS_SUFFIXES = DOCUMENT_SUFFIXES | {".csv", ".xls", ".xlsx", ".json", ".yaml", ".yml", ".html"}
PROCESS_NAME = re.compile(
    r"(?i)(?:^|[-_/])(handoff|progress|verification|dispatch|research|process-log|"
    r"session-notes|conversation|repository-consolidation)(?:[-_/.]|$)"
)
CONTENT_RULES = {
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "access-token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|sk-[A-Za-z0-9_-]{25,}|AKIA[A-Z0-9]{16})\b"),
    "literal-jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{15,}\.eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{12,}"),
    "personal-path": re.compile(r"/(?:Users|home)/[A-Za-z0-9_.-]+/|/root/(?:projects|backups)/"),
}
PROCESS_HEADING = re.compile(
    r"(?m)^#{1,6}[^\n]*(?:进度台账|交接记录|执行记录|验收记录|协作记录|研究分工|任务领取)"
)
PROCESS_NARRATIVE = re.compile(r"(?:本轮|本批)(?:已完成|交付|验证|授权)|用户(?:已授权|要求暂停)|另一\s*Agent")


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args])


def snapshot(root, staged=False):
    entries = {}
    if staged:
        for item in git(root, "ls-files", "--stage", "-z").split(b"\0"):
            if not item:
                continue
            metadata, path = item.split(b"\t", 1)
            mode, oid, stage = metadata.split()
            if stage != b"0":
                raise ValueError("Resolve index conflicts before checking public content")
            entries[path.decode()] = (mode.decode(), git(root, "cat-file", "blob", oid.decode()))
    else:
        names = set(git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z").split(b"\0"))
        for name in names:
            if not name:
                continue
            path = root / name.decode()
            if path.is_symlink():
                entries[name.decode()] = ("120000", b"")
            elif path.is_file():
                entries[name.decode()] = ("100644", path.read_bytes())
    return entries


def inspect(entries):
    errors = []
    if POLICY not in entries:
        return [(POLICY, 0, "missing-public-document-policy")]
    try:
        policy = json.loads(entries[POLICY][1])
        documents = policy["documents"]
        forbidden_hashes = set(policy["restricted_identifier_sha256"])
        assert isinstance(documents, dict) and isinstance(forbidden_hashes, set)
    except (ValueError, KeyError, TypeError, AssertionError):
        return [(POLICY, 0, "invalid-public-document-policy")]

    for name, (mode, data) in sorted(entries.items()):
        parts = Path(name).parts
        basename = parts[-1]
        if mode == "120000":
            errors.append((name, 0, "symlink-not-reviewed"))
            continue
        if (set(parts) & PRIVATE_PARTS or
            (basename.startswith(".env") and basename != ".env.example") or
            name.endswith((".dump", ".bundle", ".sqlite", ".sqlite3", ".log"))):
            errors.append((name, 0, "private-or-generated-file"))
        suffix = Path(name).suffix.lower()
        markdown = suffix in {".md", ".mdx", ".markdown"}
        document = suffix in DOCUMENT_SUFFIXES or (name.startswith("docs/") and name != POLICY)
        if suffix in PROCESS_SUFFIXES and PROCESS_NAME.search(name):
            errors.append((name, 0, "collaboration-process-document"))
        if document and name not in documents:
            errors.append((name, 0, "unregistered-public-document"))
        try:
            content = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(content.splitlines(), 1):
            for label, regex in CONTENT_RULES.items():
                if regex.search(line):
                    errors.append((name, line_number, label))
            tokens = re.findall(r"[A-Za-z0-9_.-]+|[\u4e00-\u9fff]{2,}", line)
            candidates = set(tokens)
            for token in tokens:
                candidates.update(re.split(r"[_.-]", token))
                candidates.add(re.sub(r"[_.-]", "", token))
            if any(hashlib.sha256(t.lower().encode()).hexdigest() in forbidden_hashes for t in candidates):
                errors.append((name, line_number, "restricted-deployment-identifier"))
            if document and PROCESS_NARRATIVE.search(line):
                errors.append((name, line_number, "collaboration-narrative"))
        if document:
            if PROCESS_HEADING.search(content):
                errors.append((name, 0, "collaboration-heading"))
        if markdown:
            # Strip fences: examples may contain deliberately nonexistent paths.
            prose = re.sub(r"(?ms)^```[^\n]*\n.*?^```[^\n]*$", "", content)
            links = re.findall(r"\]\(([^)\s]+)(?:\s+[^)]*)?\)", prose)
            links += re.findall(r'\bsrc="([^"]+)"', prose)
            for link in links:
                parsed = urlsplit(link)
                if parsed.scheme or parsed.netloc or not parsed.path:
                    continue
                target = posixpath.normpath(posixpath.join(posixpath.dirname(name), unquote(parsed.path)))
                if target not in entries and not any(p.startswith(target.rstrip("/") + "/") for p in entries):
                    errors.append((name, 0, "broken-relative-link"))
    for name in documents:
        if name not in entries:
            errors.append((name, 0, "stale-document-registration"))
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", action="store_true", help="Read index blobs, not working-tree files")
    args = parser.parse_args()
    try:
        entries = snapshot(ROOT, args.staged)
        errors = inspect(entries)
    except (ValueError, subprocess.CalledProcessError) as error:
        parser.exit(2, f"Public content check failed: {type(error).__name__}\n")
    for path, line, rule in errors:
        print(f"{path}:{line}: {rule}")
    if errors:
        parser.exit(1, f"Public content check: {len(errors)} violation(s)\n")
    print(f"Public content check passed: {len(entries)} files ({'index' if args.staged else 'working tree'})")


if __name__ == "__main__":
    main()
