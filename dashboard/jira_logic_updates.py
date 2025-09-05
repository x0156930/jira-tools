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
