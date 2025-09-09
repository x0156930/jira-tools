"""Backward compatible wrapper.

The project has been packaged. Use the console script `get-work-hours` now.
Running this module directly delegates to `jira_work_hours.cli.main`.

New features in packaged version:
- Menu options 8 (Edit login details) and 9 (Exit)
- Recursive menu until user chooses to exit
"""

from jira_work_hours.cli import main

if __name__ == "__main__":  # pragma: no cover
    main()