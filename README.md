# jira-tools

CLI utilities for Jira work hours, productivity, and timesheet completeness tracking.

## Install (editable dev mode)

```powershell
python -m venv venv
venv\Scripts\Activate.ps1
pip install -e .
```

## Environment Variables (.env)
Create a `.env` file in the project root:

```
JIRA_URL=https://your-jira-server
JIRA_USERNAME=your_username
JIRA_PAT=your_personal_access_token
WORKING_HOURS_PER_DAY=8
EXCLUDE_WEEKENDS=true
PRODUCTIVE_ACTIVITY_TYPES=Project Development,Support,Engineering & R&D,Testing,Code Review,Unit Testing
ACTIVITY_TYPE_FIELD=customfield_22016
HOLIDAYS=2025-01-01,2025-12-25
```

Optional:
* `PRODUCTIVE_ACTIVITY_TYPES` – Comma list of activity types counted toward productivity.
* `HOLIDAYS` – Comma list of YYYY-MM-DD dates excluded from timesheet completeness and range reports.

## Usage

After installation you get a console script:

```powershell
get-work-hours
```

Menu options:
1. Daily work hours
2. Daily productivity (selected date)
3. Weekly productivity (last 7 days)
4. Last 15 days productivity
5. Monthly productivity (last 30 days)
6. Specific issue productivity report
7. Timesheet completeness summary

You can also run the module directly:

```powershell
python -m main
```

## Build distribution

```powershell
python -m build  # if build is installed; else: pip install build
# or legacy:
python setup.py sdist bdist_wheel
```
Artifacts appear in `dist/`.

## Publish (example)

```powershell
pip install twine
twine upload dist/*
```

## Notes
* Productivity score = ((estimated - logged) / estimated) * 100.
* Only issues whose activity type is in `PRODUCTIVE_ACTIVITY_TYPES` count toward final productivity.
* Date inputs accept natural language (e.g. "yesterday", "2025-09-05").

