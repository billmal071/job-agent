"""Human-like interaction patterns: typing, mouse movement, scrolling."""

from __future__ import annotations

import random
import time

from playwright.sync_api import Page

from job_agent.utils.logging import get_logger

log = get_logger(__name__)


def human_delay(min_ms: int = 500, max_ms: int = 2000) -> None:
    """Wait a random human-like duration."""
    delay = random.uniform(min_ms / 1000, max_ms / 1000)
    time.sleep(delay)


def short_pause() -> None:
    """Brief pause between actions."""
    human_delay(200, 800)


def human_type(page: Page, selector: str, text: str, clear: bool = True) -> None:
    """Type text with human-like variable delays (gaussian ~120ms per char)."""
    element = page.locator(selector)
    element.click()
    short_pause()

    if clear:
        element.fill("")
        short_pause()

    for char in text:
        delay = max(30, random.gauss(120, 40))
        page.keyboard.type(char, delay=delay)

        # Occasional longer pause (thinking)
        if random.random() < 0.05:
            human_delay(300, 800)

    short_pause()


def human_click(page: Page, selector: str) -> None:
    """Click an element with human-like mouse movement."""
    element = page.locator(selector)
    box = element.bounding_box()
    if not box:
        element.click()
        return

    # Click at a random point within the element (not dead center)
    x = box["x"] + box["width"] * random.uniform(0.2, 0.8)
    y = box["y"] + box["height"] * random.uniform(0.2, 0.8)

    # Move mouse along a bezier curve to the target
    _bezier_move(page, x, y)
    short_pause()
    page.mouse.click(x, y)


def _bezier_move(page: Page, target_x: float, target_y: float, steps: int = 20) -> None:
    """Move mouse along a bezier curve to simulate natural movement."""
    # Get current position (approximate from viewport center if unknown)
    start_x = random.uniform(400, 800)
    start_y = random.uniform(300, 600)

    # Random control points for bezier curve
    cp1_x = start_x + (target_x - start_x) * random.uniform(0.2, 0.5)
    cp1_y = start_y + random.uniform(-100, 100)
    cp2_x = start_x + (target_x - start_x) * random.uniform(0.5, 0.8)
    cp2_y = target_y + random.uniform(-100, 100)

    for i in range(steps + 1):
        t = i / steps
        # Cubic bezier formula
        x = (
            (1 - t) ** 3 * start_x
            + 3 * (1 - t) ** 2 * t * cp1_x
            + 3 * (1 - t) * t**2 * cp2_x
            + t**3 * target_x
        )
        y = (
            (1 - t) ** 3 * start_y
            + 3 * (1 - t) ** 2 * t * cp1_y
            + 3 * (1 - t) * t**2 * cp2_y
            + t**3 * target_y
        )
        page.mouse.move(x, y)
        time.sleep(random.uniform(0.005, 0.02))


def human_scroll(page: Page, direction: str = "down", amount: int = 300) -> None:
    """Scroll with natural-looking increments."""
    total = 0
    while total < amount:
        increment = min(random.randint(50, 150), amount - total)
        delta = increment if direction == "down" else -increment
        page.mouse.wheel(0, delta)
        total += increment
        time.sleep(random.uniform(0.05, 0.15))

    human_delay(300, 800)


def scroll_to_bottom(page: Page, max_scrolls: int = 20) -> None:
    """Scroll to the bottom of the page naturally."""
    for _ in range(max_scrolls):
        prev_height = page.evaluate("document.body.scrollHeight")
        human_scroll(page, "down", random.randint(400, 800))
        human_delay(500, 1500)
        new_height = page.evaluate("document.body.scrollHeight")
        if new_height == prev_height:
            break
