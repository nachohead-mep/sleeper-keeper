"""Shared Selenium plumbing.

Uses Selenium Manager (built into Selenium 4.6+) so no driver paths or
webdriver-manager are needed — the driver binary is fetched on demand.

Lazy-imported by the source modules that need it, so installs that only use
FantasyPros/Sleeper don't require selenium or a browser.
"""

from __future__ import annotations

from contextlib import contextmanager


@contextmanager
def chrome_driver(headless: bool = True):
    """Yield a Selenium Chrome driver. Closes on exit."""
    from selenium import webdriver  # local import — optional dependency
    from selenium.webdriver.chrome.options import Options

    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")

    driver = webdriver.Chrome(options=opts)
    try:
        yield driver
    finally:
        driver.quit()
