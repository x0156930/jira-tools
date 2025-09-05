import os
import datetime
from jira import JIRA
import dateparser
from dotenv import load_dotenv

# =========================
# Configuration and Helpers
# =========================

def _str2bool(val, default=False):
    if val is None:
        return default
    return str(val).strip().lower() in {"1", "true", "yes", "y", "on"}

def _load_activity_types():
    raw = os.getenv("PRODUCTIVE_ACTIVITY_TYPES")
    if not raw:
        # Default to your previous hardcoded list
        return [
            "Project Development",
            "Support",
            "Engineering & R&D",
            "Testing",
            "Code Review",
            "Unit Testing",
        ]
    # Split by comma and strip
    return [s.strip() for s in raw.split(",") if s.strip()]

def _load_holidays():
    raw = os.getenv("HOLIDAYS", "")
    days = set()
    for tok in raw.split(","):
        s = tok.strip()
        if not s:
            continue
        # Expect ISO-8601 YYYY-MM-DD
        try:
            days.add(datetime.date.fromisoformat(s))
        except Exception:
            # Fallback: try dateparser for leniency
            d = dateparser.parse(s)
            if d:
                days.add(d.date())
    return days

load_dotenv()

JIRA_URL = os.getenv("JIRA_URL")
JIRA_USERNAME = os.getenv("JIRA_USERNAME")
JIRA_PAT = os.getenv("JIRA_PAT")

# Data-driven config
ACTIVITY_TYPE_FIELD = os.getenv("ACTIVITY_TYPE_FIELD", "customfield_22016")
PRODUCTIVE_ACTIVITY_TYPES = _load_activity_types()
WORKING_HOURS_PER_DAY = float(os.getenv("WORKING_HOURS_PER_DAY", "8"))
EXCLUDE_WEEKENDS_DEFAULT = _str2bool(os.getenv("EXCLUDE_WEEKENDS", "true"))
PAGE_SIZE = int(os.getenv("PAGE_SIZE", "100"))
HOLIDAYS = _load_holidays()

# =============
# Print Helpers
# =============

def _format_percent(value):
    return f"{value:.2f}%" if value is not None else "N/A"

def _print_table(headers, rows):
    # Compute column widths
    widths = [len(str(h)) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))
    # Helpers
    def fmt_row(row):
        return "| " + " | ".join(str(cell).ljust(widths[i]) for i, cell in enumerate(row)) + " |"
    sep = "+-" + "-+-".join("-" * w for w in widths) + "-+"
    # Print
    print(sep)
    print(fmt_row(headers))
    print(sep)
    for r in rows:
        print(fmt_row(r))
    print(sep)

# ======================
# Jira Connection/Utils
# ======================

def connect_to_jira():
    """
    Establish connection to Jira and return jira instance and username.
    """
    if not all([JIRA_URL, JIRA_USERNAME, JIRA_PAT]):
        print("Error: JIRA_URL, JIRA_USERNAME, and JIRA_PAT must be set in the .env file.")
        return None, None

    try:
        jira = JIRA(server=JIRA_URL, token_auth=JIRA_PAT)
        print("Successfully connected to Jira using token_auth.")
        server_info = jira.server_info()
        print(f"Jira Version: {server_info.get('version')}")
        return jira, JIRA_USERNAME
    except Exception as e:
        print(f"Error connecting to Jira: {e}")
        return None, None

def _search_all_issues(jira, jql, fields="summary,issuetype,status,timeoriginalestimate", expand=None, batch=PAGE_SIZE):
    """
    Paginate through search_issues results to avoid default 50-item cap.
    """
    start_at = 0
    issues = []
    while True:
        chunk = jira.search_issues(jql, startAt=start_at, maxResults=batch, fields=fields, expand=expand)
        issues.extend(chunk)
        if len(chunk) < batch:
            break
        start_at += batch
    return issues

def get_me(jira):
    """
    Return a dict with the current user identifiers for author matching.
    """
    try:
        me = jira.myself()
        return {
            "accountId": me.get("accountId"),
            "name": me.get("name"),
            "displayName": me.get("displayName"),
            "emailAddress": me.get("emailAddress"),
        }
    except Exception:
        # Fallback to env username only
        return {"accountId": None, "name": JIRA_USERNAME, "displayName": None, "emailAddress": None}

def _is_my_worklog(worklog, me):
    """
    Jira Cloud uses accountId; DC/Server often uses name/displayName. Match robustly.
    """
    wl_author = getattr(worklog, "author", None)
    if not wl_author:
        return False
    # Try accountId first
    if hasattr(wl_author, "accountId") and me.get("accountId") and wl_author.accountId == me.get("accountId"):
        return True
    # Fall back to name/displayName
    if hasattr(wl_author, "name") and me.get("name") and wl_author.name and wl_author.name.lower() == me.get("name").lower():
        return True
    if hasattr(wl_author, "displayName") and me.get("displayName") and wl_author.displayName == me.get("displayName"):
        return True
    return False

def _parse_iso_date(dt_str):
    """
    Robust parse for Jira ISO timestamps with/without fractional seconds and 'Z'.
    Returns a timezone-aware datetime where possible; falls back to naive.
    """
    try:
        return datetime.datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except Exception:
        # Strip fractional seconds and timezone to try a simpler parse
        base = dt_str.split("+")[0].split(".")[0]
        try:
            return datetime.datetime.strptime(base, "%Y-%m-%dT%H:%M:%S")
        except Exception:
            # Final fallback
            parsed = dateparser.parse(dt_str)
            if parsed:
                return parsed
            raise ValueError(f"Unrecognized datetime format: {dt_str}")

# ===========================
# Date Range and Calculations
# ===========================

def _dates_in_range(start_date, end_date, exclude_weekends=True, holidays=HOLIDAYS):
    """Return a set of date objects between start_date and end_date inclusive, honoring weekends/holidays."""
    days = set()
    cur = start_date
    while cur <= end_date:
        is_weekday = cur.weekday() < 5  # 0=Mon..4=Fri
        if (not exclude_weekends or is_weekday) and (cur not in holidays):
            days.add(cur)
        cur += datetime.timedelta(days=1)
    return days

def calculate_productivity_score(estimated_hours, logged_hours):
    """
    Calculate productivity score based on estimated vs logged hours.
    Productivity = ((estimated time - logged time) / estimated time) * 100
    """
    if estimated_hours == 0:
        return None
    productivity = ((estimated_hours - logged_hours) / estimated_hours) * 100
    return productivity

# ==================
# Core Functionality
# ==================

def get_jira_details(date_str):
    """
    Connects to Jira, parses a natural language date, and fetches issue details.
    Args:
        date_str (str): A date in natural language (e.g., "24th Aug", "yesterday").
    """
    # --- Date Parsing ---
    target_dt = dateparser.parse(date_str)
    if not target_dt:
        print(f"Error: Could not parse the date: {date_str}")
        return
    target_date = target_dt.date()
    print(f"Fetching Jira details for date: {target_date.strftime('%Y-%m-%d')}")

    # --- Jira Connection ---
    jira, jira_username = connect_to_jira()
    if not jira:
        return

    try:
        me = get_me(jira)

        # 1) Issues created by the user on that day
        print(f"\n--- Issues Created by {jira_username} On {target_date.strftime('%Y-%m-%d')} ---")
        jql_created = (
            f"created >= '{target_date}' AND created < '{target_date + datetime.timedelta(days=1)}' "
            f"AND reporter = '{jira_username}'"
        )
        created_issues = _search_all_issues(jira, jql_created)
        if created_issues:
            for issue in created_issues:
                print(f"- {issue.key}: {issue.fields.summary} ({issue.permalink()})")
        else:
            print(f"No issues were created by {jira_username} on this date.")

        # 2) Issues where the user logged work on that date
        print(f"\n--- Work Logged by {jira_username} On {target_date.strftime('%Y-%m-%d')} ---")
        total_hours_logged = 0.0
        issue_hours = {}

        formatted_date = target_date.strftime("%Y/%m/%d")
        next_date = (target_date + datetime.timedelta(days=1)).strftime("%Y/%m/%d")
        jql_worklog = f'worklogDate >= "{formatted_date}" AND worklogDate < "{next_date}" AND worklogAuthor = currentUser()'
        logged_issues = _search_all_issues(jira, jql_worklog, expand="worklog")

        if logged_issues:
            for issue in logged_issues:
                issue_total_hours = 0.0
                worklogs = jira.worklogs(issue.key)
                for worklog in worklogs:
                    try:
                        worklog_date = _parse_iso_date(worklog.started).date()
                    except Exception:
                        continue
                    if worklog_date == target_date and _is_my_worklog(worklog, me):
                        hours_logged = worklog.timeSpentSeconds / 3600.0
                        issue_total_hours += hours_logged
                        total_hours_logged += hours_logged

                if issue_total_hours > 0:
                    print(f"{issue.key} - {issue_total_hours:.2f}hrs ({issue.permalink()})")
                    issue_hours[issue.key] = issue_total_hours
        else:
            print(f"No issues with work logged by {jira_username} on this date.")

        # 3) Total
        print("\n--- Total Work Hours ---")
        print(f"Total hours logged on {target_date}: {total_hours_logged:.2f} hours")

    except Exception as e:
        print(f"Error fetching Jira details: {e}")

def get_issue_productivity(issue_key, jira):
    """
    Get productivity score for a specific issue.
    Only include issues with activity types in PRODUCTIVE_ACTIVITY_TYPES for productivity calculation.
    """
    try:
        issue = jira.issue(issue_key, expand="worklog")

        # Check Task/Story
        issue_type = (issue.fields.issuetype.name or "").lower()
        if "task" not in issue_type and "story" not in issue_type:
            return f"Issue {issue_key} is not a Task or Story (Type: {issue.fields.issuetype.name})"

        # Activity type from configured field
        activity_type = None
        field_value = getattr(issue.fields, ACTIVITY_TYPE_FIELD, None)
        if field_value is None:
            activity_type = None
        elif hasattr(field_value, "value"):
            activity_type = field_value.value
        elif isinstance(field_value, dict) and "value" in field_value:
            activity_type = field_value["value"]
        else:
            activity_type = str(field_value)

        # Estimate hours
        estimated_seconds = getattr(issue.fields, "timeoriginalestimate", None)
        if not estimated_seconds:
            return f"Issue {issue_key} has no original time estimate"

        estimated_hours = estimated_seconds / 3600.0

        # Total logged hours
        worklogs = jira.worklogs(issue_key)
        total_logged_hours = 0.0
        for wl in worklogs:
            total_logged_hours += wl.timeSpentSeconds / 3600.0

        status = issue.fields.status.name
        is_productive = activity_type in PRODUCTIVE_ACTIVITY_TYPES

        result = {
            "issue_key": issue_key,
            "summary": issue.fields.summary,
            "type": issue.fields.issuetype.name,
            "status": status,
            "activity_type": activity_type,
            "estimated_hours": round(estimated_hours, 2),
            "logged_hours": round(total_logged_hours, 2),
            "productivity_score": None,
            "is_productive_activity": is_productive,
            "link": issue.permalink(),
        }

        if is_productive:
            result["productivity_score"] = round(
                calculate_productivity_score(estimated_hours, total_logged_hours), 2
            )

        return result

    except Exception as e:
        return f"Error fetching issue {issue_key}: {e}"

def get_daily_productivity(date_str, jira, jira_username):
    """
    Get productivity scores for all tasks worked on a specific date.
    Only include issues with activity types in PRODUCTIVE_ACTIVITY_TYPES for productivity calculation.
    """
    target_dt = dateparser.parse(date_str)
    if not target_dt:
        print(f"Error: Could not parse the date: {date_str}")
        return
    target_date = target_dt.date()

    print(f"\n--- Daily Productivity Report for {target_date.strftime('%Y-%m-%d')} ---")
    try:
        me = get_me(jira)
        formatted_date = target_date.strftime("%Y/%m/%d")
        next_date = (target_date + datetime.timedelta(days=1)).strftime("%Y/%m/%d")
        jql_worklog = f'worklogDate >= "{formatted_date}" AND worklogDate < "{next_date}" AND worklogAuthor = currentUser()'
        logged_issues = _search_all_issues(jira, jql_worklog, expand="worklog")

        if not logged_issues:
            print("No issues worked on this date.")
            return

        daily_productivity_scores = []
        issues_without_productivity = []
        productive_issues_only = []

        total_estimated = 0.0
        total_logged = 0.0
        productive_total_estimated = 0.0
        productive_total_logged = 0.0

        for issue in logged_issues:
            worklogs = jira.worklogs(issue.key)
            date_logged_hours = 0.0
            for worklog in worklogs:
                try:
                    wl_date = _parse_iso_date(worklog.started).date()
                except Exception:
                    continue
                if wl_date == target_date and _is_my_worklog(worklog, me):
                    date_logged_hours += worklog.timeSpentSeconds / 3600.0

            if date_logged_hours > 0:
                productivity_data = get_issue_productivity(issue.key, jira)
                if isinstance(productivity_data, dict):
                    productivity_data["date_logged_hours"] = round(date_logged_hours, 2)
                    daily_productivity_scores.append(productivity_data)

                    total_estimated += productivity_data["estimated_hours"]
                    total_logged += date_logged_hours

                    if productivity_data["is_productive_activity"]:
                        productive_issues_only.append(productivity_data)
                        productive_total_estimated += productivity_data["estimated_hours"]
                        productive_total_logged += date_logged_hours
                else:
                    issue_info = jira.issue(issue.key)
                    issues_without_productivity.append(
                        {
                            "issue_key": issue.key,
                            "summary": issue_info.fields.summary,
                            "type": issue_info.fields.issuetype.name,
                            "status": issue_info.fields.status.name,
                            "date_logged_hours": round(date_logged_hours, 2),
                            "reason": productivity_data,
                            "link": issue_info.permalink(),
                        }
                    )

        if daily_productivity_scores:
            print("\n=== Issues with Productivity Scores ===")
            for item in daily_productivity_scores:
                print(f"\n{item['issue_key']}: {item['summary']}")
                print(f"  Type: {item['type']} | Status: {item['status']} | Activity Type: {item['activity_type']}")
                print(
                    f"  Estimated: {item['estimated_hours']}hrs | Total Logged: {item['logged_hours']}hrs | Logged on {target_date}: {item['date_logged_hours']}hrs"
                )
                if item["is_productive_activity"]:
                    print(
                        f"  Overall Productivity Score: {item['productivity_score']}% (Included in productivity calculation)"
                    )
                else:
                    print("  Activity type not in productivity calculation list")
                print(f"  Link: {item['link']}")

        if issues_without_productivity:
            print("\n=== Issues without Productivity Calculation ===")
            for item in issues_without_productivity:
                print(f"\n{item['issue_key']}: {item['summary']}")
                print(f"  Type: {item['type']} | Status: {item['status']}")
                print(f"  Logged on {target_date}: {item['date_logged_hours']}hrs")
                print(f"  Reason: {item['reason']}")
                print(f"  Link: {item['link']}")

        if productive_total_estimated > 0:
            productive_overall = calculate_productivity_score(
                productive_total_estimated, productive_total_logged
            )
            print(f"\n--- Productivity Based on Selected Activity Types ---")
            print(f"Activity Types Included: {', '.join(PRODUCTIVE_ACTIVITY_TYPES)}")
            print(
                f"Productive Issues Estimated: {productive_total_estimated:.2f}hrs | Logged: {productive_total_logged:.2f}hrs"
            )
            print(f"Daily Productivity Score (Based on Activity Types): {productive_overall:.2f}%")
        else:
            print(f"\n--- No Issues with Selected Activity Types Found ---")
            print(f"Activity Types Included: {', '.join(PRODUCTIVE_ACTIVITY_TYPES)}")

        table_rows = []
        for item in daily_productivity_scores:
            prod_str = _format_percent(item["productivity_score"]) if item["is_productive_activity"] else "N/A"
            activity = item["activity_type"] if item["activity_type"] else "-"
            est = item["estimated_hours"]
            logged_total = item["logged_hours"]
            table_rows.append([item["issue_key"], activity, f"{est:.2f}", f"{logged_total:.2f}", prod_str, ""])
        final_score = (
            calculate_productivity_score(productive_total_estimated, productive_total_logged)
            if productive_total_estimated > 0
            else None
        )
        table_rows.append(["Final", "Selected Activity Types", "", "", "", _format_percent(final_score)])

        print("\n=== Tabular Summary ===")
        _print_table(
            ["Issue", "Activity Type", "Estimated (hrs)", "Logged (hrs)", "Productivity", "Final Productivity"],
            table_rows,
        )
    except Exception as e:
        print(f"Error calculating daily productivity: {e}")

def get_range_productivity(start_date, end_date, jira, jira_username, period_label, exclude_weekends=EXCLUDE_WEEKENDS_DEFAULT):
    """
    Calculate productivity for a date range (inclusive), optionally excluding weekends and holidays.
    """
    included_dates = _dates_in_range(start_date, end_date, exclude_weekends=exclude_weekends, holidays=HOLIDAYS)
    if not included_dates:
        print(f"No working days found in range {start_date} to {end_date}.")
        return

    print(
        f"\n--- {period_label} Productivity Report ({start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}) ---"
    )
    print("Excluding weekends" if exclude_weekends else "Including weekends")
    if HOLIDAYS:
        print(f"Holidays excluded: {', '.join(sorted(d.isoformat() for d in HOLIDAYS))}")

    try:
        me = get_me(jira)
        formatted_start = start_date.strftime("%Y/%m/%d")
        formatted_end_plus_1 = (end_date + datetime.timedelta(days=1)).strftime("%Y/%m/%d")
        jql_worklog = f'worklogDate >= "{formatted_start}" AND worklogDate < "{formatted_end_plus_1}" AND worklogAuthor = currentUser()'
        logged_issues = _search_all_issues(jira, jql_worklog, expand="worklog")

        if not logged_issues:
            print("No issues worked in this period.")
            return

        range_productivity = []
        issues_without_productivity = []
        productive_issues_only = []

        total_estimated = 0.0
        total_logged_in_range = 0.0
        productive_total_estimated = 0.0
        productive_total_logged_in_range = 0.0

        for issue in logged_issues:
            worklogs = jira.worklogs(issue.key)
            range_logged_hours = 0.0

            for worklog in worklogs:
                try:
                    wl_date = _parse_iso_date(worklog.started).date()
                except Exception:
                    continue
                if (wl_date in included_dates) and _is_my_worklog(worklog, me):
                    range_logged_hours += worklog.timeSpentSeconds / 3600.0

            if range_logged_hours > 0:
                productivity_data = get_issue_productivity(issue.key, jira)

                if isinstance(productivity_data, dict):
                    productivity_data["range_logged_hours"] = round(range_logged_hours, 2)
                    range_productivity.append(productivity_data)

                    total_estimated += productivity_data["estimated_hours"]
                    total_logged_in_range += range_logged_hours

                    if productivity_data["is_productive_activity"]:
                        productive_issues_only.append(productivity_data)
                        productive_total_estimated += productivity_data["estimated_hours"]
                        productive_total_logged_in_range += range_logged_hours
                else:
                    issue_info = jira.issue(issue.key)
                    issues_without_productivity.append(
                        {
                            "issue_key": issue.key,
                            "summary": issue_info.fields.summary,
                            "type": issue_info.fields.issuetype.name,
                            "status": issue_info.fields.status.name,
                            "range_logged_hours": round(range_logged_hours, 2),
                            "reason": productivity_data,
                            "link": issue_info.permalink(),
                        }
                    )

        if range_productivity:
            print("\n=== Issues with Productivity Scores ===")
            for item in range_productivity:
                print(f"\n{item['issue_key']}: {item['summary']}")
                print(f"  Type: {item['type']} | Status: {item['status']} | Activity Type: {item['activity_type']}")
                print(
                    f"  Estimated: {item['estimated_hours']}hrs | Total Logged: {item['logged_hours']}hrs | Logged in Period: {item['range_logged_hours']}hrs"
                )
                if item["is_productive_activity"]:
                    print(f"  Overall Productivity Score: {item['productivity_score']}% (Included in productivity calculation)")
                else:
                    print("  Activity type not in productivity calculation list")
                print(f"  Link: {item['link']}")

        if issues_without_productivity:
            print("\n=== Issues without Productivity Calculation ===")
            for item in issues_without_productivity:
                print(f"\n{item['issue_key']}: {item['summary']}")
                print(f"  Type: {item['type']} | Status: {item['status']}")
                print(f"  Logged in Period: {item['range_logged_hours']}hrs")
                print(f"  Reason: {item['reason']}")
                print(f"  Link: {item['link']}")

        if productive_total_estimated > 0:
            productive_overall = calculate_productivity_score(
                productive_total_estimated, productive_total_logged_in_range
            )
            print(f"\n--- Productivity Based on Selected Activity Types ---")
            print(f"Activity Types Included: {', '.join(PRODUCTIVE_ACTIVITY_TYPES)}")
            print(
                f"Productive Issues Estimated: {productive_total_estimated:.2f}hrs | Logged in Period: {productive_total_logged_in_range:.2f}hrs"
            )
            print(f"{period_label} Productivity Score (Based on Activity Types): {productive_overall:.2f}%")
        else:
            print(f"\n--- No Issues with Selected Activity Types Found ---")
            print(f"Activity Types Included: {', '.join(PRODUCTIVE_ACTIVITY_TYPES)}")

        table_rows = []
        for item in range_productivity:
            prod_str = _format_percent(item["productivity_score"]) if item["is_productive_activity"] else "N/A"
            activity = item["activity_type"] if item["activity_type"] else "-"
            est = item["estimated_hours"]
            logged_total = item["logged_hours"]
            table_rows.append([item["issue_key"], activity, f"{est:.2f}", f"{logged_total:.2f}", prod_str, ""])
        final_score = (
            calculate_productivity_score(productive_total_estimated, productive_total_logged_in_range)
            if productive_total_estimated > 0
            else None
        )
        table_rows.append(["Final", "Selected Activity Types", "", "", "", _format_percent(final_score)])

        print("\n=== Tabular Summary ===")
        _print_table(
            ["Issue", "Activity Type", "Estimated (hrs)", "Logged (hrs)", "Productivity", "Final Productivity"],
            table_rows,
        )

    except Exception as e:
        print(f"Error calculating {period_label.lower()} productivity: {e}")

def get_weekly_productivity(jira, jira_username):
    """Last 7 days (inclusive), excluding weekends/holidays by default."""
    end_date = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=6)
    get_range_productivity(start_date, end_date, jira, jira_username, "Weekly", exclude_weekends=EXCLUDE_WEEKENDS_DEFAULT)

def get_last_15_days_productivity(jira, jira_username):
    """Last 15 days (inclusive), excluding weekends/holidays by default."""
    end_date = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=14)
    get_range_productivity(start_date, end_date, jira, jira_username, "Last 15 Days", exclude_weekends=EXCLUDE_WEEKENDS_DEFAULT)

def get_monthly_productivity(jira, jira_username):
    """Last 30 days (inclusive), excluding weekends/holidays by default."""
    end_date = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=29)
    get_range_productivity(start_date, end_date, jira, jira_username, "Monthly", exclude_weekends=EXCLUDE_WEEKENDS_DEFAULT)

# ============================
# Timesheet Completeness (New)
# ============================

def get_timesheet_completeness(jira, days_back=7, exclude_weekends=EXCLUDE_WEEKENDS_DEFAULT):
    """
    Summarize per-day logged hours vs target (WORKING_HOURS_PER_DAY) across the last N days.
    Honors weekends/holidays.
    """
    me = get_me(jira)
    today = datetime.date.today()
    start_date = today - datetime.timedelta(days=days_back - 1)
    included = _dates_in_range(start_date, today, exclude_weekends=exclude_weekends, holidays=HOLIDAYS)

    fmt_start = start_date.strftime("%Y/%m/%d")
    fmt_end_plus_1 = (today + datetime.timedelta(days=1)).strftime("%Y/%m/%d")
    jql = f'worklogDate >= "{fmt_start}" AND worklogDate < "{fmt_end_plus_1}" AND worklogAuthor = currentUser()'

    issues = _search_all_issues(jira, jql, expand="worklog")
    logs_by_day = {d: 0.0 for d in included}

    for issue in issues:
        for wl in jira.worklogs(issue.key):
            try:
                wl_date = _parse_iso_date(wl.started).date()
            except Exception:
                continue
            if wl_date in included and _is_my_worklog(wl, me):
                logs_by_day[wl_date] += wl.timeSpentSeconds / 3600.0

    rows = []
    total_gap = 0.0
    for d in sorted(included):
        hours = round(logs_by_day.get(d, 0.0), 2)
        gap = max(0.0, WORKING_HOURS_PER_DAY - hours)
        total_gap += gap
        rows.append([d.isoformat(), f"{hours:.2f}", f"{WORKING_HOURS_PER_DAY:.2f}", f"{gap:.2f}"])

    print(f"\n--- Timesheet Completeness (last {days_back} days) ---")
    print(f"Target hours/day: {WORKING_HOURS_PER_DAY:.2f} | Exclude weekends: {exclude_weekends} | Holidays excluded: {len(HOLIDAYS)}")
    _print_table(["Date", "Logged (hrs)", "Target (hrs)", "Gap (hrs)"], rows)
    print(f"Total gap over period: {total_gap:.2f} hrs")

# ===========
# Entry Point
# ===========

def main():
    print("=== Jira Productivity & Work Hours Tracker ===")
    print("1. Check daily work hours")
    print("2. Check daily productivity")
    print("3. Check Weekly Productivity")
    print("4. Check last 15 days Productivity")
    print("5. Check Monthly Productivity")
    print("6. Check specific issue productivity")
    print("7. Timesheet completeness (last 7 days)")

    choice = input("\nEnter your choice (1/2/3/4/5/6/7): ").strip()

    if choice == "1":
        date_input = input("Enter a date (e.g., '24th Aug', 'yesterday', 'today', '2025-08-27'): ")
        get_jira_details(date_input)

    elif choice == "2":
        jira, jira_username = connect_to_jira()
        if jira and jira_username:
            date_input = input("Enter a date (e.g., '24th Aug', 'yesterday', 'today', '2025-08-27'): ")
            get_daily_productivity(date_input, jira, jira_username)

    elif choice == "3":
        jira, jira_username = connect_to_jira()
        if jira and jira_username:
            get_weekly_productivity(jira, jira_username)

    elif choice == "4":
        jira, jira_username = connect_to_jira()
        if jira and jira_username:
            get_last_15_days_productivity(jira, jira_username)

    elif choice == "5":
        jira, jira_username = connect_to_jira()
        if jira and jira_username:
            get_monthly_productivity(jira, jira_username)

    elif choice == "6":
        jira, jira_username = connect_to_jira()
        if jira and jira_username:
            issue_key = input("Enter the Jira issue key (e.g., 'PROJ-123'): ").strip().upper()
            print(f"\n--- Productivity Report for {issue_key} ---")

            result = get_issue_productivity(issue_key, jira)

            if isinstance(result, dict):
                print(f"\nIssue: {result['issue_key']} - {result['summary']}")
                print(f"Type: {result['type']}")
                print(f"Status: {result['status']}")
                print(f"Activity Type: {result['activity_type']}")
                print(f"Estimated Hours: {result['estimated_hours']}")
                print(f"Total Logged Hours: {result['logged_hours']}")

                if result["is_productive_activity"]:
                    print(f"Productivity Score: {result['productivity_score']}%")
                    if result["productivity_score"] > 0:
                        print("✅ Good! Completed under estimated time")
                    elif result["productivity_score"] == 0:
                        print("⚠️ Exactly on estimate")
                    else:
                        print("❌ Over estimated time - consider reviewing estimates")
                    print("Activity type is included in productivity calculations")
                else:
                    print("❌ Activity type not included in productivity calculations")
                    print(f"Only these activity types are included: {', '.join(PRODUCTIVE_ACTIVITY_TYPES)}")

                print(f"Link: {result['link']}")
            else:
                print(result)  # Error message

    elif choice == "7":
        jira, jira_username = connect_to_jira()
        if jira and jira_username:
            try:
                days = int(input("Days back (default 7): ").strip() or "7")
            except Exception:
                days = 7
            ex_we = input(f"Exclude weekends? (Y/N, default {'Y' if EXCLUDE_WEEKENDS_DEFAULT else 'N'}): ").strip().lower()
            exclude_weekends = EXCLUDE_WEEKENDS_DEFAULT if ex_we == "" else (ex_we in {"y", "yes"})
            get_timesheet_completeness(jira, days_back=days, exclude_weekends=exclude_weekends)

    else:
        print("Invalid choice. Please run the script again and select 1-7.")


if __name__ == "__main__":
    main()