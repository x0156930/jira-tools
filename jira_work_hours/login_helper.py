"""login_helper

Provides a single function `ensure_credentials(force_login=False)` which:
- Reads credentials from OS keyring (`jira-work-hours`) if available.
- If missing or `force_login` is True, prompts user for JIRA_URL, JIRA_USERNAME, and JIRA_PAT (visible input by design).
- Saves values back to OS keyring (best-effort) and sets them into `os.environ` for the running session.

This keeps secret handling centralized.
"""

from __future__ import annotations

import os

try:
    import keyring  # type: ignore
except Exception:  # pragma: no cover - optional dependency failures
    keyring = None  # type: ignore


def prompt_visible(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except Exception:  # pragma: no cover - defensive
        return ""


SERVICE = "jira-work-hours"
DEFAULT_JIRA_URL = "https://amatjira.amat.com"  # fixed common URL per user request


def clear_stored_credentials() -> None:
    """Clear stored credentials from keyring. Useful for testing or switching accounts."""
    if keyring:  # pragma: no branch - simple gate
        try:
            keyring.delete_password(SERVICE, "JIRA_USERNAME")
            keyring.delete_password(SERVICE, "JIRA_PAT")
            keyring.delete_password(SERVICE, "JIRA_URL")
            print("Stored credentials cleared from keyring.")
        except Exception as e:  # pragma: no cover - keyring backend specifics
            print(f"Could not clear credentials: {e}")
    else:
        print("Keyring not available.")


def ensure_credentials(force_login: bool = False):
    """Ensure JIRA_URL, JIRA_USERNAME, and JIRA_PAT are available in os.environ.
    If force_login is True, prompt and overwrite stored values.
    First tries to load from keyring, then prompts if missing.
    Returns tuple (url, username, pat).
    """
    url = DEFAULT_JIRA_URL  # Always use the fixed URL
    user = os.environ.get("JIRA_USERNAME")
    pat = os.environ.get("JIRA_PAT")

    # Try to load from keyring first (unless force_login)
    if not force_login and keyring:
        try:
            kr_user = keyring.get_password(SERVICE, "JIRA_USERNAME")
            kr_pat = keyring.get_password(SERVICE, "JIRA_PAT")

            if kr_user and kr_pat:
                # Found stored credentials, use them
                print("Using stored credentials from keyring.")
                os.environ["JIRA_USERNAME"] = kr_user
                os.environ["JIRA_PAT"] = kr_pat
                os.environ["JIRA_URL"] = DEFAULT_JIRA_URL
                return DEFAULT_JIRA_URL, kr_user, kr_pat
        except Exception as e:  # pragma: no cover - backend specific
            # Keyring access failed, continue to prompt
            print(f"Could not access keyring: {e}")

    # If force_login or credentials not in keyring, prompt user
    if force_login or not (user and pat):
        print("Please enter your Jira credentials:")

        # Prompt for username
        u = prompt_visible("your-id: ")
        if u:
            user = u
            os.environ["JIRA_USERNAME"] = u
            # Save to keyring
            try:
                if keyring:
                    keyring.set_password(SERVICE, "JIRA_USERNAME", u)
                    print("Username saved to keyring.")
            except Exception as e:  # pragma: no cover
                print(f"Could not save username to keyring: {e}")

        # Prompt for PAT
        p = prompt_visible("jira-pat-token: ")
        if p:
            pat = p
            os.environ["JIRA_PAT"] = p
            # Save to keyring
            try:
                if keyring:
                    keyring.set_password(SERVICE, "JIRA_PAT", p)
                    print("PAT token saved to keyring.")
            except Exception as e:  # pragma: no cover
                print(f"Could not save PAT to keyring: {e}")

    # Always set the URL
    os.environ["JIRA_URL"] = DEFAULT_JIRA_URL
    try:
        if keyring:
            keyring.set_password(SERVICE, "JIRA_URL", DEFAULT_JIRA_URL)
    except Exception:  # pragma: no cover
        pass

    return DEFAULT_JIRA_URL, user, pat
