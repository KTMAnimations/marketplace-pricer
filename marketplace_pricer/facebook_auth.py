from __future__ import annotations

from marketplace_pricer.config import Settings


def run_facebook_login(settings: Settings) -> None:
    """
    Opens a headed browser for manual Facebook login and saves Playwright storage state.

    This avoids hard-coding credentials; the saved state contains cookies/session data.
    """

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise RuntimeError(
            "Playwright is required for facebook-login. Install deps and run `playwright install`."
        ) from exc

    state_path = settings.facebook_storage_state_path
    state_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://www.facebook.com/login", wait_until="domcontentloaded")

        print("Login in the opened browser window.")
        print("After you're logged in and can access Marketplace, come back here and press Enter.")
        input()

        context.storage_state(path=str(state_path))
        context.close()
        browser.close()

    print(f"Saved Facebook storage state to {state_path}")

