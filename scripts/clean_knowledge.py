"""
Clean knowledge/ directory: remove unreadable/failed content, deduplicate, reformat.
"""
from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path

KNOWLEDGE = Path(__file__).resolve().parent.parent / "knowledge"
SUBDIRS = ["web", "sources", "reports", "papers"]


def _real_text(content: str) -> str:
    lines = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("- 生成时间") and not stripped.startswith("- 来源") and not stripped.startswith("#"):
            lines.append(stripped)
    return "\n".join(lines)


def _is_js_error(content: str) -> bool:
    low = content.lower()
    js_signals = [
        "javascript is disabled",
        "please enable javascript",
        "a required part of this site couldn't load",
    ]
    return any(s in low for s in js_signals)


def _is_github_session_error(content: str) -> bool:
    low = content.lower()
    return (
        "there was an error while loading" in low
        and "reload" in low
        and "you signed in" in low
    )


def _is_boilerplate_only(content: str) -> bool:
    low = content.lower()
    gitlab_patterns = ["skip to content", "you signed in", "reload to refresh"]
    if sum(1 for p in gitlab_patterns if p in low) >= 2:
        real = _real_text(content)
        effective = sum(1 for line in real.splitlines() if len(line) > 15)
        return effective < 5
    return False


def _content_hash(content: str) -> str:
    real = _real_text(content)
    return hashlib.md5(real.encode("utf-8")).hexdigest()


def _clean_github_boilerplate(text: str) -> str:
    lines = text.splitlines()
    kill_patterns = [
        re.compile(r"^You signed in with another tab", re.I),
        re.compile(r"^Reload$", re.I),
        re.compile(r"^to refresh your session\.?$", re.I),
        re.compile(r"^You switched accounts on another tab", re.I),
        re.compile(r"^Dismiss alert", re.I),
        re.compile(r"^Uh oh!$", re.I),
        re.compile(r"^There was an error while loading\.?$", re.I),
        re.compile(r"^Please reload this page\.?$", re.I),
        re.compile(r"^You must be signed in", re.I),
        re.compile(r"^Notifications$", re.I),
        re.compile(r"^Fork$", re.I),
        re.compile(r"^Star$", re.I),
        re.compile(r"^Go to file$", re.I),
        re.compile(r"^Code$"),
        re.compile(r"^Open more actions menu", re.I),
        re.compile(r"^Folders? and files?$", re.I),
    ]
    result = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if any(p.search(stripped) for p in kill_patterns):
            continue
        result.append(line)
    return "\n".join(result)


def _clean_steam_boilerplate(text: str) -> str:
    lines = text.splitlines()
    kill_phrases = [
        "sign in", "store", "home", "discovery queue", "wishlist",
        "points shop", "news", "charts", "community", "workshop",
        "market", "broadcasts", "about", "support", "change language",
        "get the steam mobile app", "view desktop website",
        "privacy policy", "legal", "accessibility",
        "steam subscriber agreement", "refunds", "cookies",
        "© valve corporation", "all rights reserved",
        "all trademarks are property",
    ]
    result = []
    for line in lines:
        stripped = line.strip().rstrip(".")
        if not stripped:
            continue
        if any(p.lower() in stripped.lower() for p in kill_phrases):
            continue
        result.append(line)
    return "\n".join(result)


def _normalize_filename(name: str) -> str:
    new = name.replace(" ", "_")
    new = re.sub(r"[<>:\"|?*\x00-\x1f]", "_", new)
    if new != name:
        print(f"    Rename: {name} -> {new}")
    return new


def clean():
    print("=" * 60)
    print("Knowledge Directory Cleanup")
    print("=" * 60)

    deletions = 0
    cleaned_files = 0

    seen_hashes: dict[str, Path] = {}

    for subdir in SUBDIRS:
        d = KNOWLEDGE / subdir
        if not d.is_dir():
            continue
        for fp in sorted(d.iterdir()):
            if not fp.is_file() or fp.suffix.lower() not in (".md", ".txt"):
                continue

            content = fp.read_text(encoding="utf-8", errors="replace")
            real = _real_text(content)
            real_len = len(real.strip())

            # 1. JS error pages
            if _is_js_error(content):
                print(f"DELETE [JS error] {fp.relative_to(KNOWLEDGE)} ({real_len}c)")
                fp.unlink()
                deletions += 1
                continue

            # 2. GitHub session error
            if _is_github_session_error(content):
                print(f"DELETE [GitHub error] {fp.relative_to(KNOWLEDGE)} ({real_len}c)")
                fp.unlink()
                deletions += 1
                continue

            # 3. Too short / no real content
            if real_len < 50:
                print(f"DELETE [too short] {fp.relative_to(KNOWLEDGE)} ({real_len}c)")
                fp.unlink()
                deletions += 1
                continue

            # 4. Boilerplate only
            if _is_boilerplate_only(content):
                print(f"DELETE [boilerplate] {fp.relative_to(KNOWLEDGE)} ({real_len}c)")
                fp.unlink()
                deletions += 1
                continue

            # 5. Duplicate detection
            h = _content_hash(content)
            if h in seen_hashes:
                existing = seen_hashes[h]
                print(f"DELETE [duplicate] {fp.relative_to(KNOWLEDGE)} == {existing.relative_to(KNOWLEDGE)}")
                fp.unlink()
                deletions += 1
                continue
            seen_hashes[h] = fp

            # 6. Clean GitHub boilerplate
            cleaned = _clean_github_boilerplate(content)
            # 7. Clean Steam boilerplate
            cleaned = _clean_steam_boilerplate(cleaned)

            if cleaned != content:
                fp.write_text(cleaned, encoding="utf-8")
                cleaned_files += 1
                print(f"CLEAN  {fp.relative_to(KNOWLEDGE)} (removed UI boilerplate)")

            # 8. Normalize filename
            new_name = _normalize_filename(fp.name)
            if new_name != fp.name:
                new_path = fp.parent / new_name
                if not new_path.is_file():
                    fp.rename(new_path)

    # Remove empty subdirs
    for subdir in SUBDIRS:
        d = KNOWLEDGE / subdir
        if d.is_dir() and not any(d.iterdir()):
            shutil.rmtree(d)
            print(f"REMOVED empty directory: {subdir}/")

    print(f"\nDone: {deletions} deleted, {cleaned_files} cleaned, {len(seen_hashes)} unique files remaining.")


if __name__ == "__main__":
    clean()
