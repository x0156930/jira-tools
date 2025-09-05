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
        return [
            "Project Development",
            "Support",
            "Engineering & R&D",
            "Testing",
            "Code Review",
            "Unit Testing",
        ]
    return [s.strip() for s in raw.split(",") if s.strip()]

def _load_holidays():
    raw = os.getenv("HOLIDAYS", "")
    days = set()
    for tok in raw.split(","):
        s = tok.strip()
        if not s:
            continue
        try:
            days.add(datetime.date.fromisoformat(s))
        except Exception:
            d = dateparser.parse(s)
            if d:
                days.add(d.date())
    return days

load_dotenv()

JIRA_URL = os.getenv("JIRA_URL")
JIRA_USERNAME = os.getenv("JIRA_USERNAME")
JIRA_PAT = os.getenv("JIRA_PAT")

ACTIVITY_TYPE_FIELD = os.getenv("ACTIVITY_TYPE_FIELD", "customfield_22016")
PRODUCTIVE_ACTIVITY_TYPES = _load_activity_types()
WORKING_HOURS_PER_DAY = float(os.getenv("WORKING_HOURS_PER_DAY", "8"))
EXCLUDE_WEEKENDS_DEFAULT = _str2bool(os.getenv("EXCLUDE_WEEKENDS", "true"))
PAGE_SIZE = int(os.getenv("PAGE_SIZE", "100"))
HOLIDAYS = _load_holidays()
DONE_STATUSES = {s.strip().lower() for s in os.getenv("DONE_STATUSES", "Done,Closed,Resolved,Completed").split(",") if s.strip()}

# =============
# Print Helpers
# =============

def _format_percent(value):
    return f"{value:.2f}%" if value is not None else "N/A"

def _print_table(headers, rows):
    widths = [len(str(h)) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))
    def fmt_row(row):
        return "| " + " | ".join(str(cell).ljust(widths[i]) for i, cell in enumerate(row)) + " |"
    sep = "+-" + "-+-".join("-" * w for w in widths) + "-+"
    print(sep); print(fmt_row(headers)); print(sep)
    for r in rows: print(fmt_row(r))
    print(sep)

# ======================
# Jira Connection/Utils
# ======================

def connect_to_jira():
    if not all([JIRA_URL, JIRA_USERNAME, JIRA_PAT]):
        print("Error: JIRA_URL, JIRA_USERNAME, and JIRA_PAT must be set.")
        return None, None
    try:
        jira = JIRA(server=JIRA_URL, token_auth=JIRA_PAT)
        print("Connected to Jira.")
        info = jira.server_info()
        print(f"Jira Version: {info.get('version')}")
        return jira, JIRA_USERNAME
    except Exception as e:
        print(f"Error connecting to Jira: {e}")
        return None, None

def _search_all_issues(jira, jql, fields="summary,issuetype,status,timeoriginalestimate,subtasks", expand=None, batch=PAGE_SIZE):
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
    try:
        me = jira.myself()
        return {
            "accountId": me.get("accountId"),
            "name": me.get("name"),
            "displayName": me.get("displayName"),
            "emailAddress": me.get("emailAddress"),
        }
    except Exception:
        return {"accountId": None, "name": JIRA_USERNAME, "displayName": None, "emailAddress": None}

def _is_my_worklog(worklog, me):
    wl_author = getattr(worklog, "author", None)
    if not wl_author: return False
    if hasattr(wl_author, "accountId") and me.get("accountId") and wl_author.accountId == me.get("accountId"):
        return True
    if hasattr(wl_author, "name") and me.get("name") and wl_author.name and wl_author.name.lower() == me.get("name").lower():
        return True
    if hasattr(wl_author, "displayName") and me.get("displayName") and wl_author.displayName == me.get("displayName"):
        return True
    return False

def _parse_iso_date(dt_str):
    try:
        return datetime.datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except Exception:
        base = dt_str.split("+")[0].split(".")[0]
        try:
            return datetime.datetime.strptime(base, "%Y-%m-%dT%H:%M:%S")
        except Exception:
            parsed = dateparser.parse(dt_str)
            if parsed:
                return parsed
            raise ValueError(f"Unrecognized datetime: {dt_str}")

def is_done_status(name):
    return (name or "").lower() in DONE_STATUSES

# ===========================
# Date Range and Calculations
# ===========================

def _dates_in_range(start_date, end_date, exclude_weekends=True, holidays=HOLIDAYS):
    days = set()
    cur = start_date
    while cur <= end_date:
        if (not exclude_weekends or cur.weekday() < 5) and cur not in holidays:
            days.add(cur)
        cur += datetime.timedelta(days=1)
    return days

def calculate_productivity_score(estimated_hours, logged_hours):
    if estimated_hours == 0:
        return None
    return ((estimated_hours - logged_hours) / estimated_hours) * 100

# ==================
# Core Functionality
# ==================

def get_jira_details(date_str):
    target_dt = dateparser.parse(date_str)
    if not target_dt:
        print(f"Error: Could not parse date: {date_str}")
        return
    target_date = target_dt.date()
    print(f"Fetching Jira details for {target_date}")
    jira, jira_username = connect_to_jira()
    if not jira: return
    try:
        me = get_me(jira)
        jql_created = f"created >= '{target_date}' AND created < '{target_date + datetime.timedelta(days=1)}' AND reporter = '{jira_username}'"
        print(f"\n--- Issues Created by {jira_username} ---")
        for issue in _search_all_issues(jira, jql_created):
            print(f"- {issue.key}: {issue.fields.summary} ({issue.permalink()})")
        formatted_date = target_date.strftime("%Y/%m/%d")
        next_date = (target_date + datetime.timedelta(days=1)).strftime("%Y/%m/%d")
        jql_worklog = f'worklogDate >= "{formatted_date}" AND worklogDate < "{next_date}" AND worklogAuthor = currentUser()'
        print(f"\n--- Work Logged ({jira_username}) ---")
        total_hours = 0.0
        for issue in _search_all_issues(jira, jql_worklog, expand="worklog"):
            issue_total = 0.0
            for wl in jira.worklogs(issue.key):
                try:
                    if _parse_iso_date(wl.started).date() == target_date and _is_my_worklog(wl, me):
                        hrs = wl.timeSpentSeconds / 3600.0
                        issue_total += hrs
                        total_hours += hrs
                except Exception:
                    continue
            if issue_total > 0:
                print(f"{issue.key} - {issue_total:.2f}hrs ({issue.permalink()})")
        print(f"\nTotal hours logged: {total_hours:.2f}")
    except Exception as e:
        print(f"Error fetching details: {e}")

# -------- Story Aggregation --------

def _extract_activity_type(issue):
    field_value = getattr(issue.fields, ACTIVITY_TYPE_FIELD, None)
    if field_value is None:
        return None
    if hasattr(field_value, "value"):
        return field_value.value
    if isinstance(field_value, dict) and "value" in field_value:
        return field_value["value"]
    return str(field_value)

def _collect_logged_hours(jira, issue, me=None):
    total = 0.0
    try:
        worklogs = jira.worklogs(issue.key)
    except Exception:
        return 0.0
    for wl in worklogs:
        if me is None or _is_my_worklog(wl, me):
            total += wl.timeSpentSeconds / 3600.0
    return total

def get_story_aggregate_productivity(issue, jira):
    """
    Aggregate productivity from DONE subtasks of a Story.
    Only subtasks whose status is in DONE_STATUSES are counted.
    """
    included = []
    est_sum = 0.0
    logged_sum = 0.0
    missing_est = 0
    for sub_ref in getattr(issue.fields, "subtasks", []) or []:
        try:
            sub = jira.issue(sub_ref.key, expand="worklog")
        except Exception:
            continue
        sub_status = sub.fields.status.name
        if not is_done_status(sub_status):
            continue
        est_seconds = getattr(sub.fields, "timeoriginalestimate", None)
        if not est_seconds:
            missing_est += 1
            continue
        est_hours = est_seconds / 3600.0
        logged_hours = _collect_logged_hours(jira, sub)
        included.append({
            "key": sub.key,
            "summary": sub.fields.summary,
            "status": sub_status,
            "estimated_hours": round(est_hours, 2),
            "logged_hours": round(logged_hours, 2)
        })
        est_sum += est_hours
        logged_sum += logged_hours
    productivity = calculate_productivity_score(est_sum, logged_sum) if est_sum > 0 else None
    return {
        "story_aggregate": True,
        "issue_key": issue.key,
        "summary": issue.fields.summary,
        "story_status": issue.fields.status.name,
        "included_subtasks": included,
        "included_subtasks_count": len(included),
        "excluded_subtasks_missing_estimate": missing_est,
        "aggregated_estimated_hours": round(est_sum, 2),
        "aggregated_logged_hours": round(logged_sum, 2),
        "aggregated_productivity_score": round(productivity, 2) if productivity is not None else None,
        "link": issue.permalink()
    }

def get_issue_productivity(issue_key, jira, strict_task_status=False, aggregate_story=False):
    """
    Base productivity:
    - Tasks/Stories (original logic).
    Enhancements (if strict_task_status=True / aggregate_story=True for single-issue view):
      * Task: only if status in DONE_STATUSES.
      * Story: if aggregate_story True (or story has no estimate), aggregate DONE subtasks.
    """
    try:
        issue = jira.issue(issue_key, expand="worklog")
        issue_type_name = (issue.fields.issuetype.name or "").lower()
        status_name = issue.fields.status.name

        # Story aggregation logic
        if "story" in issue_type_name:
            est_seconds = getattr(issue.fields, "timeoriginalestimate", None)
            if aggregate_story or not est_seconds:
                # Aggregate even if story has its own estimate when user asks
                return get_story_aggregate_productivity(issue, jira)

        # Task-level gating
        if ("task" in issue_type_name) and strict_task_status and not is_done_status(status_name):
            return f"Issue {issue_key} status '{status_name}' not in DONE statuses ({', '.join(sorted(DONE_STATUSES))})"

        # Original per-issue calculation
        if "task" not in issue_type_name and "story" not in issue_type_name:
            return f"Issue {issue_key} is not a Task or Story (Type: {issue.fields.issuetype.name})"

        activity_type = _extract_activity_type(issue)
        est_seconds = getattr(issue.fields, "timeoriginalestimate", None)
        if not est_seconds:
            return f"Issue {issue_key} has no original time estimate"

        est_hours = est_seconds / 3600.0
        total_logged_hours = _collect_logged_hours(jira, issue)
        is_productive = activity_type in PRODUCTIVE_ACTIVITY_TYPES
        productivity_score = None
        if is_productive:
            productivity_score = calculate_productivity_score(est_hours, total_logged_hours)
            if productivity_score is not None:
                productivity_score = round(productivity_score, 2)

        return {
            "issue_key": issue_key,
            "summary": issue.fields.summary,
            "type": issue.fields.issuetype.name,
            "status": status_name,
            "activity_type": activity_type,
            "estimated_hours": round(est_hours, 2),
            "logged_hours": round(total_logged_hours, 2),
            "productivity_score": productivity_score,
            "is_productive_activity": is_productive,
            "link": issue.permalink(),
            "story_aggregate": False
        }
    except Exception as e:
        return f"Error fetching issue {issue_key}: {e}"

# (Existing daily/range productivity functions unchanged; they call get_issue_productivity without strict flags)

def get_daily_productivity(date_str, jira, jira_username):
    target_dt = dateparser.parse(date_str)
    if not target_dt:
        print(f"Error: Could not parse date: {date_str}")
        return
    target_date = target_dt.date()
    print(f"\n--- Daily Productivity Report for {target_date} (DONE issues only) ---")
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
        productive_total_estimated = productive_total_logged = 0.0

        for issue in logged_issues:
            date_logged_hours = 0.0
            for wl in jira.worklogs(issue.key):
                try:
                    wl_date = _parse_iso_date(wl.started).date()
                except Exception:
                    continue
                if wl_date == target_date and _is_my_worklog(wl, me):
                    date_logged_hours += wl.timeSpentSeconds / 3600.0
            if date_logged_hours > 0:
                status_name = issue.fields.status.name
                if not is_done_status(status_name):
                    issues_without_productivity.append({
                        "issue_key": issue.key,
                        "reason": f"Issue status '{status_name}' not in DONE statuses ({', '.join(sorted(DONE_STATUSES))})"
                    })
                    continue
                pdata = get_issue_productivity(issue.key, jira)
                if isinstance(pdata, dict):
                    pdata["date_logged_hours"] = round(date_logged_hours, 2)
                    daily_productivity_scores.append(pdata)
                    if pdata.get("is_productive_activity"):
                        productive_total_estimated += pdata["estimated_hours"]
                        productive_total_logged += date_logged_hours
                else:
                    issues_without_productivity.append({"issue_key": issue.key, "reason": pdata})

        if daily_productivity_scores:
            print("\n=== DONE Issues (Details) ===")
            for item in daily_productivity_scores:
                print(f"\n{item['issue_key']}: {item['summary']}")
                print(f"  Type: {item['type']} | Status: {item['status']} | Activity Type: {item['activity_type']}")
                print(f"  Estimated: {item['estimated_hours']}hrs | Logged (total): {item['logged_hours']}hrs | Logged today: {item['date_logged_hours']}hrs")
                if not item["is_productive_activity"]:
                    print("  Activity type not in calculation list")

        if issues_without_productivity:
            print("\n=== Issues Excluded from Productivity (Not DONE or other) ===")
            for item in issues_without_productivity:
                print(f"{item['issue_key']}: {item['reason']}")

        if productive_total_estimated > 0:
            score = calculate_productivity_score(productive_total_estimated, productive_total_logged)
            print(f"\nDaily Productivity (Selected Activity Types, DONE only): {score:.2f}%")
        else:
            print("\nNo productive DONE issues found for this day.")

        # Tabular summary first
        rows = []
        for item in daily_productivity_scores:
            prod_str = _format_percent(item["productivity_score"]) if item["is_productive_activity"] else "N/A"
            rows.append([
                item["issue_key"],
                item.get("activity_type") or "-",
                f"{item['estimated_hours']:.2f}",
                f"{item['logged_hours']:.2f}",
                prod_str, ""
            ])
        final_score = calculate_productivity_score(productive_total_estimated, productive_total_logged) if productive_total_estimated > 0 else None
        rows.append(["Final", "Selected Activity Types (DONE)", "", "", "", _format_percent(final_score)])
        print("\n=== Tabular Summary ===")
        _print_table(["Issue", "Activity Type", "Estimated (hrs)", "Logged (hrs)", "Productivity", "Final Productivity"], rows)

        # Classification AFTER table
        TARGET_MIN = 30.0
        TARGET_MAX = 45.0
        print("\n=== Productivity Classification (After Summary) ===")
        for item in daily_productivity_scores:
            if not item["is_productive_activity"]:
                continue
            ps = item["productivity_score"]
            if ps is None:
                continue
            msg_prefix = f"{item['issue_key']} -> {ps}% : "
            if TARGET_MIN <= ps <= TARGET_MAX:
                print(msg_prefix + "✅ Good productivity (within 30–45% target range). Great work.")
            elif ps > TARGET_MAX:
                print(msg_prefix + "ℹ️ Productivity above target range (>45%). Recheck if estimate was too high or if time is under‑logged.")
            elif ps >= 0:
                print(msg_prefix + "⚠️ Below target range (<30%). Add remaining work logs or validate the original estimate.")
            else:
                print(msg_prefix + "❌ Over estimate (logged more time than estimated). Review estimate or scope changes.")

        if final_score is not None:
            print("\nFinal Daily Aggregate Classification:")
            if TARGET_MIN <= final_score <= TARGET_MAX:
                print(f"{final_score:.2f}% ✅ Good productivity (within 30–45% target range). Great work.")
            elif final_score > TARGET_MAX:
                print(f"{final_score:.2f}% ℹ️ Above target range (>45%). Recheck estimates or under‑logging.")
            elif final_score >= 0:
                print(f"{final_score:.2f}% ⚠️ Below target range (<30%). Review estimates or missing work logs.")
            else:
                print(f"{final_score:.2f}% ❌ Over estimate (more time logged than estimated).")

    except Exception as e:
        print(f"Error calculating daily productivity: {e}")

def get_range_productivity(start_date, end_date, jira, jira_username, period_label, exclude_weekends=EXCLUDE_WEEKENDS_DEFAULT):
    included_dates = _dates_in_range(start_date, end_date, exclude_weekends=exclude_weekends, holidays=HOLIDAYS)
    if not included_dates:
        print("No working days in range.")
        return
    print(f"\n--- {period_label} Productivity Report ({start_date} to {end_date}) (DONE issues only) ---")
    print("Excluding weekends" if exclude_weekends else "Including weekends")
    if HOLIDAYS: print(f"Holidays excluded: {', '.join(sorted(d.isoformat() for d in HOLIDAYS))}")
    try:
        me = get_me(jira)
        start_fmt = start_date.strftime("%Y/%m/%d")
        end_plus_1 = (end_date + datetime.timedelta(days=1)).strftime("%Y/%m/%d")
        jql = f'worklogDate >= "{start_fmt}" AND worklogDate < "{end_plus_1}" AND worklogAuthor = currentUser()'
        logged_issues = _search_all_issues(jira, jql, expand="worklog")
        if not logged_issues:
            print("No issues worked in this period.")
            return
        range_productivity = []
        issues_without = []
        prod_est = prod_log = 0.0
        for issue in logged_issues:
            range_hours = 0.0
            for wl in jira.worklogs(issue.key):
                try:
                    wl_date = _parse_iso_date(wl.started).date()
                except Exception:
                    continue
                if wl_date in included_dates and _is_my_worklog(wl, me):
                    range_hours += wl.timeSpentSeconds / 3600.0
            if range_hours > 0:
                status_name = issue.fields.status.name
                if not is_done_status(status_name):
                    issues_without.append({
                        "issue_key": issue.key,
                        "reason": f"Issue status '{status_name}' not in DONE statuses ({', '.join(sorted(DONE_STATUSES))})"
                    })
                    continue
                pdata = get_issue_productivity(issue.key, jira)
                if isinstance(pdata, dict):
                    pdata["range_logged_hours"] = round(range_hours, 2)
                    range_productivity.append(pdata)
                    if pdata.get("is_productive_activity"):
                        prod_est += pdata["estimated_hours"]
                        prod_log += range_hours
                else:
                    issues_without.append({"issue_key": issue.key, "reason": pdata})

        if range_productivity:
            print("\n=== DONE Issues with Productivity Scores ===")
            TARGET_MIN = 30.0
            TARGET_MAX = 45.0
            for item in range_productivity:
                print(f"\n{item['issue_key']}: {item['summary']}")
                print(f"  Type: {item['type']} | Status: {item['status']} | Activity: {item['activity_type']}")
                print(f"  Estimated: {item['estimated_hours']}hrs | Total Logged: {item['logged_hours']}hrs | Logged in Period: {item['range_logged_hours']}hrs")
                if item["is_productive_activity"]:
                    print(f"  Productivity Score: {item['productivity_score']}%")
                    ps = item["productivity_score"]
                    if ps is not None:
                        if TARGET_MIN <= ps <= TARGET_MAX:
                            print("  ✅ Good productivity (within 30–45% target range). Great work.")
                        elif ps > TARGET_MAX:
                            print("  ℹ️ Productivity above target range (>45%). Recheck if estimate was too high or if time is under‑logged.")
                        elif ps >= 0:  # 0 <= ps < TARGET_MIN
                            print("  ⚠️ Below target range (<30%). Add remaining work logs or validate the original estimate.")
                        else:  # ps < 0
                            print("  ❌ Over estimate (logged more time than estimated). Review estimate or scope changes.")
                    print("  Activity type counted.")
                else:
                    print("  Activity type not counted for productivity list.")
                    print(f"  Included types: {', '.join(PRODUCTIVE_ACTIVITY_TYPES)}")
                    print(f"  Link: {item['link']}")

        if issues_without:
            print("\n=== Issues Excluded from Productivity (Not DONE or other) ===")
            for item in issues_without:
                print(f"{item['issue_key']}: {item['reason']}")
        if prod_est > 0:
            score = calculate_productivity_score(prod_est, prod_log)
            print(f"\n{period_label} Productivity (Selected Activity Types, DONE only): {score:.2f}%")
        else:
            print(f"\nNo productive DONE issues found for this period.")
        rows = []
        for item in range_productivity:
            prod_str = _format_percent(item["productivity_score"]) if item["is_productive_activity"] else "N/A"
            rows.append([item["issue_key"], item.get("activity_type") or "-", f"{item['estimated_hours']:.2f}",
                         f"{item['logged_hours']:.2f}", prod_str, ""])
        final_score = calculate_productivity_score(prod_est, prod_log) if prod_est > 0 else None
        rows.append(["Final", "Selected Activity Types (DONE)", "", "", "", _format_percent(final_score)])
        print("\n=== Tabular Summary ===")
        _print_table(["Issue", "Activity Type", "Estimated (hrs)", "Logged (hrs)", "Productivity", "Final Productivity"], rows)

        # Final aggregate classification
        if final_score is not None:
            TARGET_MIN = 30.0
            TARGET_MAX = 45.0
            print("\nFinal Aggregate Classification:")
            if TARGET_MIN <= final_score <= TARGET_MAX:
                print(f"{final_score:.2f}% ✅ Good productivity (within 30–45% target range). Great work.")
            elif final_score > TARGET_MAX:
                print(f"{final_score:.2f}% ℹ️ Above target range (>45%). Recheck estimates or under‑logging.")
            elif final_score >= 0:
                print(f"{final_score:.2f}% ⚠️ Below target range (<30%). Review estimates or missing work logs.")
            else:
                print(f"{final_score:.2f}% ❌ Over estimate (more time logged than estimated).")

    except Exception as e:
        print(f"Error calculating {period_label.lower()} productivity: {e}")

def get_weekly_productivity(jira, jira_username):
    end_date = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=6)
    get_range_productivity(start_date, end_date, jira, jira_username, "Weekly")

def get_last_15_days_productivity(jira, jira_username):
    end_date = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=14)
    get_range_productivity(start_date, end_date, jira, jira_username, "Last 15 Days")

def get_monthly_productivity(jira, jira_username):
    end_date = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=29)
    get_range_productivity(start_date, end_date, jira, jira_username, "Monthly")

# Timesheet completeness (unchanged from previous enhancement)

def get_timesheet_completeness(jira, days_back=7, exclude_weekends=EXCLUDE_WEEKENDS_DEFAULT):
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
        hrs = round(logs_by_day.get(d, 0.0), 2)
        gap = max(0.0, WORKING_HOURS_PER_DAY - hrs)
        total_gap += gap
        rows.append([d.isoformat(), f"{hrs:.2f}", f"{WORKING_HOURS_PER_DAY:.2f}", f"{gap:.2f}"])
    print(f"\n--- Timesheet Completeness (last {days_back} days) ---")
    print(f"Target/day: {WORKING_HOURS_PER_DAY:.2f} | Excl weekends: {exclude_weekends} | Holidays: {len(HOLIDAYS)}")
    _print_table(["Date", "Logged (hrs)", "Target (hrs)", "Gap (hrs)"], rows)
    print(f"Total gap: {total_gap:.2f} hrs")

# ===========
# Entry Point
# ===========

if __name__ == "__main__":
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
        if jira:
            date_input = input("Enter a date: ")
            get_daily_productivity(date_input, jira, jira_username)

    elif choice == "3":
        jira, jira_username = connect_to_jira()
        if jira: get_weekly_productivity(jira, jira_username)

    elif choice == "4":
        jira, jira_username = connect_to_jira()
        if jira: get_last_15_days_productivity(jira, jira_username)

    elif choice == "5":
        jira, jira_username = connect_to_jira()
        if jira: get_monthly_productivity(jira, jira_username)

    elif choice == "6":
        jira, jira_username = connect_to_jira()
        if jira:
            issue_key = input("Enter the Jira issue key (e.g., 'PROJ-123'): ").strip().upper()
            strict = input("Strict task status (Done only)? (y/N): ").strip().lower() in {"y","yes"}
            aggregate_story = False
            # Peek type to decide prompt default
            try:
                tmp_issue = jira.issue(issue_key)
                if (tmp_issue.fields.issuetype.name or "").lower().find("story") >= 0:
                    has_est = bool(getattr(tmp_issue.fields, "timeoriginalestimate", None))
                    default_yes = "Y" if not has_est else "N"
                    aggregate_story = input(f"Aggregate story subtasks? (y/N) [default {default_yes}]: ").strip().lower()
                    if aggregate_story == "":
                        aggregate_story = (default_yes == "Y")
                    else:
                        aggregate_story = aggregate_story in {"y","yes"}
                else:
                    aggregate_story = False
            except Exception:
                pass

            print(f"\n--- Productivity Report for {issue_key} ---")
            result = get_issue_productivity(issue_key, jira, strict_task_status=strict, aggregate_story=aggregate_story)

            if isinstance(result, dict):
                if result.get("story_aggregate"):
                    print(f"\nStory: {result['issue_key']} - {result['summary']} (Status: {result['story_status']})")
                    print(f"Included Done subtasks: {result['included_subtasks_count']} | Missing est excluded: {result['excluded_subtasks_missing_estimate']}")
                    print(f"Aggregated Estimated Hours: {result['aggregated_estimated_hours']}")
                    print(f"Aggregated Logged Hours: {result['aggregated_logged_hours']}")
                    agg_score = result['aggregated_productivity_score']
                    if agg_score is not None:
                        print(f"Aggregated Productivity Score: {agg_score}%")
                    else:
                        print("Aggregated Productivity Score: N/A (no estimates)")
                    print("Subtasks:")
                    for st in result['included_subtasks']:
                        print(f"  - {st['key']} [{st['status']}] Est {st['estimated_hours']}h Logged {st['logged_hours']}h")
                    print(f"Link: {result['link']}")
                else:
                    print(f"\nIssue: {result['issue_key']} - {result['summary']}")
                    print(f"Type: {result['type']} | Status: {result['status']}")
                    print(f"Activity Type: {result['activity_type']}")
                    print(f"Estimated Hours: {result['estimated_hours']}")
                    print(f"Total Logged Hours: {result['logged_hours']}")
                if result['is_productive_activity']:
                        print(f"Productivity Score: {result['productivity_score']}%")
                        ps = result['productivity_score']
                        if ps is not None:
                            TARGET_MIN = 30.0
                            TARGET_MAX = 45.0
                            if TARGET_MIN <= ps <= TARGET_MAX:
                                print("✅ Good productivity (within 30–45% target range). Great work.")
                            elif ps > TARGET_MAX:
                                print("ℹ️ Productivity above target range (>45%). Recheck if estimate was too high or if time is under‑logged.")
                            elif ps >= 0:  # 0 <= ps < TARGET_MIN
                                print("⚠️ Below target range (<30%). Add remaining work logs or validate the original estimate.")
                            else:  # ps < 0
                                print("❌ Over estimate (logged more time than estimated). Review estimate or scope changes.")
                        print("Activity type counted.")
                else:
                        print("Activity type not counted for productivity list.")
                        print(f"Included types: {', '.join(PRODUCTIVE_ACTIVITY_TYPES)}")
                        print(f"Link: {result['link']}")
            else:
                print(result)

    elif choice == "7":
        jira, jira_username = connect_to_jira()
        if jira:
            try:
                days = int(input("Days back (default 7): ").strip() or "7")
            except Exception:
                days = 7
            ex_we = input(f"Exclude weekends? (y/N, default {'Y' if EXCLUDE_WEEKENDS_DEFAULT else 'N'}): ").strip().lower()
            exclude_weekends = EXCLUDE_WEEKENDS_DEFAULT if ex_we == "" else (ex_we in {"y", "yes"})
            get_timesheet_completeness(jira, days_back=days, exclude_weekends=exclude_weekends)
    else:
        print("Invalid choice.")