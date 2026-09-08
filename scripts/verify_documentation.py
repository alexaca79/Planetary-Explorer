"""Validate local Markdown links and heading anchors without network calls."""

from __future__ import annotations

import argparse
from html.parser import HTMLParser
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt


ROOT = Path(__file__).resolve().parents[1]
PARSER = MarkdownIt("commonmark", {"html": True}).enable("table")


class HtmlReferences(HTMLParser):
    """Collect link targets, images and explicit anchors from embedded HTML."""

    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.anchors: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if attributes.get("id"):
            self.anchors.add(str(attributes["id"]))
        if tag == "a" and attributes.get("name"):
            self.anchors.add(str(attributes["name"]))
        target = attributes.get("href") if tag == "a" else attributes.get("src") if tag == "img" else None
        if target:
            self.links.append(target)


def document_references(path: Path) -> tuple[list[str], set[str]]:
    """Parse links and GitHub-style heading anchors from a Markdown file."""
    source = path.read_text(encoding="utf-8-sig")
    if source.startswith("---\n"):
        source = source.split("\n---", 1)[-1]
    tokens = PARSER.parse(source)
    links: list[str] = []
    anchors: set[str] = set()
    heading_counts: dict[str, int] = {}
    html = HtmlReferences()
    for index, token in enumerate(tokens):
        if token.type == "heading_open":
            heading = tokens[index + 1]
            text = "".join(child.content for child in heading.children or [] if child.type in {"text", "code_inline"})
            slug = re.sub(r"[^\w\- ]", "", text.lower()).replace(" ", "-")
            count = heading_counts.get(slug, 0)
            heading_counts[slug] = count + 1
            anchors.add(f"{slug}-{count}" if count else slug)
        for child in [token, *(token.children or [])]:
            if child.type == "link_open":
                links.append(child.attrGet("href") or "")
            elif child.type == "image":
                links.append(child.attrGet("src") or "")
            elif child.type in {"html_block", "html_inline"}:
                html.feed(child.content)
    return [*links, *html.links], anchors | html.anchors


def validate_documents(paths: list[Path], root: Path = ROOT) -> list[str]:
    """Return missing local targets and unknown Markdown heading anchors."""
    failures: list[str] = []
    cache: dict[Path, tuple[list[str], set[str]]] = {}
    for path in paths:
        if path not in cache:
            cache[path] = document_references(path)
        for target in cache[path][0]:
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc:
                continue
            relative = unquote(parsed.path)
            destination = (
                root / relative.lstrip("/") if relative.startswith("/")
                else path.parent / relative if relative else path
            ).resolve()
            if not destination.exists():
                failures.append(f"{path.relative_to(root)}: missing target {target}")
            elif parsed.fragment and destination.suffix.lower() == ".md":
                fragment = unquote(parsed.fragment)
                if re.fullmatch(r"L\d+(?:-L\d+)?", fragment):
                    continue
                if destination not in cache:
                    cache[destination] = document_references(destination)
                if fragment not in cache[destination][1]:
                    failures.append(f"{path.relative_to(root)}: unknown heading {target}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path)
    arguments = parser.parse_args()
    paths = arguments.paths
    if not paths:
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "--", "*.md"],
            cwd=ROOT, check=True, capture_output=True, text=True,
        )
        paths = [ROOT / name for name in result.stdout.splitlines() if not name.startswith(".copilot-tracking/")]
    paths = [path.resolve() for path in paths if path.is_file()]
    failures = validate_documents(paths)
    for failure in failures:
        print(failure)
    print(f"Checked {len(paths)} Markdown files; {len(failures)} local reference errors.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())