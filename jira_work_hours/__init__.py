"""jira_work_hours package

Utilities and CLI for Jira work hours and productivity tracking.

Public API (minimal for now):
- ensure_credentials: credential helper
- connect_to_jira: establish Jira connection
- get_daily_productivity, get_weekly_productivity, etc.

CLI entrypoint exposed via pyproject as `get-work-hours`.
"""
from .login_helper import ensure_credentials  # re-export
from .cli import main  # noqa: E402 (runtime import after definitions)

__version__ = "0.3.1"

__all__ = [
    "ensure_credentials",
    "main",
    "__version__",
]
