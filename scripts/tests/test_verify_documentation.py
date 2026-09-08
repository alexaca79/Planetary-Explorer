"""Tests for offline documentation reference validation."""

import importlib.util
from pathlib import Path
import sys


SPEC = importlib.util.spec_from_file_location("verify_documentation", Path(__file__).parents[1] / "verify_documentation.py")
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_given_markdown_and_html_links_when_validating_then_existing_targets_pass(tmp_path: Path) -> None:
    destination = tmp_path / "Other Page.md"
    destination.write_text("# Deployment\n\n## CPU Setup\n\n## CPU Setup\n<a id=\"explicit\"></a>\n", encoding="utf-8")
    source = tmp_path / "README.md"
    source.write_text(
        '[CPU](Other%20Page.md#cpu-setup) [Repeat](Other%20Page.md#cpu-setup-1)\n'
        '<a href="Other%20Page.md#explicit">Details</a>\n[External](https://example.com)\n'
        '```text\n[Not a link](missing.md)\n```\n', encoding="utf-8",
    )

    assert MODULE.validate_documents([source], tmp_path) == []


def test_given_missing_file_or_heading_when_validating_then_errors_are_reported(tmp_path: Path) -> None:
    source = tmp_path / "README.md"
    source.write_text('# Title\n[Missing](missing.md)\n[Wrong](#unknown)\n<img src="missing.png">\n', encoding="utf-8")

    failures = MODULE.validate_documents([source], tmp_path)

    assert len(failures) == 3
    assert any("missing target missing.md" in failure for failure in failures)
    assert any("unknown heading #unknown" in failure for failure in failures)
    assert any("missing target missing.png" in failure for failure in failures)