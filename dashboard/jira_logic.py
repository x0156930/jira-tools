import datetime
import dateparser
from jira import JIRA

# --- Helper functions from main.py ---
def connect_to_jira(jira_url, jira_username, jira_pat):
    try:
        jira = JIRA(server=jira_url, token_auth=jira_pat)
        jira.myself()
        return jira, jira_username
    except Exception:
        return None, None

def _str2bool(val, default=False):
    if val is None:
        return default
    return str(val).strip().lower() in {"1", "true", "yes", "y", "on"}

def _load_activity_types():
    # In Django version, we don't use env vars
    # Default to your previous hardcoded list
    return [
        "Project Development",
        "Support",
        "Engineering & R&D",
        "Testing",
        "Code Review",
        "Unit Testing",
    ]
    # Split by comma and strip if using env vars
    # return [s.strip() for s in raw.split(",") if s.strip()]

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

def _search_all_issues(jira, jql, fields="summary,issuetype,status,timeoriginalestimate", expand=None, batch=100):
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
        return {"accountId": None, "name": None, "displayName": None, "emailAddress": None}

def get_jira_details(jira, jira_username, date_str):
    target_dt = dateparser.parse(date_str)
    if not target_dt:
        return None, 'Could not parse the date.'
    target_date = target_dt.date()
    
    try:
        me = get_me(jira)

        # 1) Issues created by the user on that day
        jql_created = (
            f"created >= '{target_date}' AND created < '{target_date + datetime.timedelta(days=1)}' "
            f"AND reporter = '{jira_username}'"
        )
        created_issues = _search_all_issues(jira, jql_created)
        
        # 2) Issues where the user logged work on that date
        formatted_date = target_date.strftime("%Y/%m/%d")
        next_date = (target_date + datetime.timedelta(days=1)).strftime("%Y/%m/%d")
        jql_worklog = f'worklogDate >= "{formatted_date}" AND worklogDate < "{next_date}" AND worklogAuthor = currentUser()'
        logged_issues = _search_all_issues(jira, jql_worklog, expand="worklog")
        
        # Calculate hours logged
        total_hours_logged = 0.0
        issue_hours = {}
        
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
                issue_hours[issue.key] = issue_total_hours
        
        return {
            'created_issues': created_issues,
            'logged_issues': logged_issues,
            'issue_hours': issue_hours,
            'total_hours_logged': total_hours_logged,
            'target_date': target_date
        }, None

    except Exception as e:
        return None, str(e)

def calculate_productivity_score(estimated_hours, logged_hours):
    """
    Calculate productivity score based on estimated vs logged hours.
    Productivity = ((estimated time - logged time) / estimated time) * 100
    """
    if estimated_hours == 0:
        return None
    productivity = ((estimated_hours - logged_hours) / estimated_hours) * 100
    return productivity

def get_issue_productivity(jira, issue_key):
    """
    Get productivity score for a specific issue.
    Only include issues with activity types in PRODUCTIVE_ACTIVITY_TYPES for productivity calculation.
    """
    ACTIVITY_TYPE_FIELD = "customfield_22016"  # Default
    PRODUCTIVE_ACTIVITY_TYPES = _load_activity_types()
    
    try:
        issue = jira.issue(issue_key, expand="worklog")

        # Check Task/Story
        issue_type = (issue.fields.issuetype.name or "").lower()
        if "task" not in issue_type and "story" not in issue_type:
            return None, f"Issue {issue_key} is not a Task or Story (Type: {issue.fields.issuetype.name})"

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
            return None, f"Issue {issue_key} has no original time estimate"

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

        return result, None

    except Exception as e:
        return None, f"Error fetching issue {issue_key}: {e}"

def get_daily_productivity(jira, jira_username, date_str):
    """
    Get productivity scores for all tasks worked on a specific date.
    Only include issues with activity types in PRODUCTIVE_ACTIVITY_TYPES for productivity calculation.
    """
    target_dt = dateparser.parse(date_str)
    if not target_dt:
        return None, f"Could not parse the date: {date_str}"
    target_date = target_dt.date()
    
    try:
        me = get_me(jira)
        formatted_date = target_date.strftime("%Y/%m/%d")
        next_date = (target_date + datetime.timedelta(days=1)).strftime("%Y/%m/%d")
        jql_worklog = f'worklogDate >= "{formatted_date}" AND worklogDate < "{next_date}" AND worklogAuthor = currentUser()'
        logged_issues = _search_all_issues(jira, jql_worklog, expand="worklog")
        
        if not logged_issues:
            return {"daily_productivity_scores": [], "issues_without_productivity": [], "productive_issues_only": [], 
                   "productive_total_estimated": 0, "productive_total_logged": 0, "total_estimated": 0, "total_logged": 0, 
                   "target_date": target_date}, None
        
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
                productivity_data, error = get_issue_productivity(jira, issue.key)
                if productivity_data:
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
                            "reason": error,
                            "link": issue_info.permalink(),
                        }
                    )
        
        productive_overall = None
        if productive_total_estimated > 0:
            productive_overall = calculate_productivity_score(
                productive_total_estimated, productive_total_logged
            )
            
        return {
            "daily_productivity_scores": daily_productivity_scores,
            "issues_without_productivity": issues_without_productivity,
            "productive_issues_only": productive_issues_only,
            "total_estimated": total_estimated,
            "total_logged": total_logged,
            "productive_total_estimated": productive_total_estimated,
            "productive_total_logged": productive_total_logged,
            "productive_overall": productive_overall,
            "target_date": target_date,
            "activity_types": _load_activity_types()
        }, None
        
    except Exception as e:
        return None, f"Error calculating daily productivity: {e}"

def _dates_in_range(start_date, end_date, exclude_weekends=True, holidays=None):
    """Return a set of date objects between start_date and end_date inclusive, honoring weekends/holidays."""
    if holidays is None:
        holidays = set()
        
    days = set()
    cur = start_date
    while cur <= end_date:
        is_weekday = cur.weekday() < 5  # 0=Mon..4=Fri
        if (not exclude_weekends or is_weekday) and (cur not in holidays):
            days.add(cur)
        cur += datetime.timedelta(days=1)
    return days

def get_range_productivity(jira, jira_username, start_date_str, end_date_str, period_label, exclude_weekends=True):
    """
    Calculate productivity for a date range (inclusive), optionally excluding weekends and holidays.
    """
    start_dt = dateparser.parse(start_date_str)
    end_dt = dateparser.parse(end_date_str)
    
    if not start_dt or not end_dt:
        return None, "Could not parse date range"
        
    start_date = start_dt.date()
    end_date = end_dt.date()
    
    included_dates = _dates_in_range(start_date, end_date, exclude_weekends=exclude_weekends)
    if not included_dates:
        return None, f"No working days found in range {start_date} to {end_date}."
    
    try:
        me = get_me(jira)
        formatted_start = start_date.strftime("%Y/%m/%d")
        formatted_end_plus_1 = (end_date + datetime.timedelta(days=1)).strftime("%Y/%m/%d")
        jql_worklog = f'worklogDate >= "{formatted_start}" AND worklogDate < "{formatted_end_plus_1}" AND worklogAuthor = currentUser()'
        logged_issues = _search_all_issues(jira, jql_worklog, expand="worklog")
        
        if not logged_issues:
            return {"range_productivity": [], "issues_without_productivity": [], "productive_issues_only": [],
                  "total_estimated": 0, "total_logged_in_range": 0, 
                  "productive_total_estimated": 0, "productive_total_logged_in_range": 0,
                  "start_date": start_date, "end_date": end_date, "period_label": period_label,
                  "exclude_weekends": exclude_weekends}, None
        
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
                productivity_data, error = get_issue_productivity(jira, issue.key)
                
                if productivity_data:
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
                            "reason": error,
                            "link": issue_info.permalink(),
                        }
                    )
        
        productive_overall = None
        if productive_total_estimated > 0:
            productive_overall = calculate_productivity_score(
                productive_total_estimated, productive_total_logged_in_range
            )
            
        return {
            "range_productivity": range_productivity,
            "issues_without_productivity": issues_without_productivity,
            "productive_issues_only": productive_issues_only,
            "total_estimated": total_estimated,
            "total_logged_in_range": total_logged_in_range,
            "productive_total_estimated": productive_total_estimated,
            "productive_total_logged_in_range": productive_total_logged_in_range,
            "productive_overall": productive_overall,
            "period_label": period_label,
            "start_date": start_date,
            "end_date": end_date,
            "exclude_weekends": exclude_weekends,
            "activity_types": _load_activity_types()
        }, None
        
    except Exception as e:
        return None, f"Error calculating {period_label.lower()} productivity: {e}"

def get_timesheet_completeness(jira, days_back=7, exclude_weekends=True):
    """
    Summarize per-day logged hours vs target (WORKING_HOURS_PER_DAY) across the last N days.
    Honors weekends/holidays.
    """
    WORKING_HOURS_PER_DAY = 8.0  # Default
    
    me = get_me(jira)
    today = datetime.date.today()
    start_date = today - datetime.timedelta(days=days_back - 1)
    included = _dates_in_range(start_date, today, exclude_weekends=exclude_weekends)
    
    fmt_start = start_date.strftime("%Y/%m/%d")
    fmt_end_plus_1 = (today + datetime.timedelta(days=1)).strftime("%Y/%m/%d")
    jql = f'worklogDate >= "{fmt_start}" AND worklogDate < "{fmt_end_plus_1}" AND worklogAuthor = currentUser()'
    
    try:
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
        
        days_data = []
        total_gap = 0.0
        for d in sorted(included):
            hours = round(logs_by_day.get(d, 0.0), 2)
            gap = max(0.0, WORKING_HOURS_PER_DAY - hours)
            total_gap += gap
            days_data.append({
                "date": d.isoformat(),
                "logged_hours": hours,
                "target_hours": WORKING_HOURS_PER_DAY,
                "gap_hours": gap
            })
            
        return {
            "days_data": days_data,
            "total_gap": total_gap,
            "days_back": days_back,
            "target_hours_per_day": WORKING_HOURS_PER_DAY,
            "exclude_weekends": exclude_weekends
        }, None
        
    except Exception as e:
        return None, f"Error calculating timesheet completeness: {e}"

def get_timesheet_completeness(jira, jira_username, start_date_str, end_date_str, exclude_weekends=True):
    """
    Analyze timesheet completeness for a specific date range.
    Returns which days have time logged and which are missing.
    """
    try:
        # Parse dates
        start_date = dateparser.parse(start_date_str).date()
        end_date = dateparser.parse(end_date_str).date()
        
        # Ensure start_date <= end_date
        if start_date > end_date:
            start_date, end_date = end_date, start_date
            
        # Get all business days in range
        current_date = start_date
        business_days = []
        while current_date <= end_date:
            if not exclude_weekends or current_date.weekday() < 5:  # 0-4 are Monday to Friday
                business_days.append(current_date)
            current_date += datetime.timedelta(days=1)
        
        if not business_days:
            return None, "No working days in selected period"
        
        # Get me dict for worklog matching
        me = get_me(jira)
        
        # Get worklog dates for date range
        jql = (
            f'worklogDate >= "{start_date.strftime("%Y/%m/%d")}" AND '
            f'worklogDate <= "{end_date.strftime("%Y/%m/%d")}" AND '
            f'worklogAuthor = currentUser()'
        )
        logged_issues = _search_all_issues(jira, jql, expand="worklog")
        
        worklog_dates = set()
        for issue in logged_issues:
            worklogs = jira.worklogs(issue.key)
            for worklog in worklogs:
                try:
                    worklog_date = _parse_iso_date(worklog.started).date()
                    if _is_my_worklog(worklog, me) and start_date <= worklog_date <= end_date:
                        # Only count business days based on exclude_weekends
                        if not exclude_weekends or worklog_date.weekday() < 5:
                            worklog_dates.add(worklog_date)
                except Exception:
                    continue
        
        # Calculate completeness metrics
        total_days = len(business_days)
        days_with_logs = len(worklog_dates)
        days_missing = total_days - days_with_logs
        
        # Missing dates (business days without logs)
        missing_dates = [d.strftime("%Y-%m-%d") for d in business_days if d not in worklog_dates]
        
        # Calculate percentage
        percentage_complete = round((days_with_logs / total_days) * 100) if total_days > 0 else 0
        
        return {
            'start_date': start_date.strftime("%Y-%m-%d"),
            'end_date': end_date.strftime("%Y-%m-%d"),
            'total_days': total_days,
            'days_with_logs': days_with_logs,
            'days_missing': days_missing,
            'missing_dates': missing_dates,
            'percentage_complete': percentage_complete
        }, None
    
    except Exception as e:
        return None, f"Error calculating timesheet completeness: {e}"
