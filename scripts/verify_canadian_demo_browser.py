"""Verify Canadian 2026 examples and chat legends in the running web app."""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import Page, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
SCREENSHOT_DIR = ROOT / "documentation" / "images" / "maps"
APP_URL = "http://127.0.0.1:5173"
TORONTO_QUERY = (
    "Show Sentinel-2 imagery over Toronto, Canada "
    "from 2026-06-01 to 2026-08-26"
)
LEGACY_LOCATIONS = ("California", "Texas", "New Orleans", "Washington, DC")


def _capture_examples(page: Page) -> None:
    page.locator(".get-started-button").click()
    modal = page.locator(".get-started-modal-content")
    modal.wait_for(state="visible")
    page.locator(".vision-selector").click()
    modal.get_by_text(TORONTO_QUERY, exact=True).wait_for(state="visible")

    modal_text = modal.inner_text()
    if any(location in modal_text for location in LEGACY_LOCATIONS):
        raise AssertionError("Get Started modal contains a legacy non-Canadian location")
    modal.screenshot(path=str(SCREENSHOT_DIR / "canadian_examples_2026.png"))


def _run_stac_query(page: Page) -> None:
    card = page.locator(".stac-card").filter(has_text=TORONTO_QUERY).first
    card.get_by_role("button", name="Go").click()
    page.locator(".row.user").filter(has_text=TORONTO_QUERY).wait_for(
        state="visible",
        timeout=30_000,
    )
    legend = page.locator(".chat-legend").last
    legend.wait_for(state="visible", timeout=120_000)
    if "Natural-colour imagery" not in legend.inner_text():
        raise AssertionError("Toronto STAC response did not render its colour legend")
    page.locator(".chat.chat-container").screenshot(
        path=str(SCREENSHOT_DIR / "canadian_stac_chat_legend_2026.png"),
    )


def main() -> int:
    """Run the browser validation against local backend and frontend servers."""
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    page_errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.goto(APP_URL, wait_until="networkidle", timeout=60_000)
        page.locator(".get-started-button").wait_for(state="visible")
        _capture_examples(page)
        _run_stac_query(page)
        browser.close()

    if page_errors:
        print("Browser page errors:", file=sys.stderr)
        for error in page_errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Canadian 2026 modal, STAC query, and chat legend verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())