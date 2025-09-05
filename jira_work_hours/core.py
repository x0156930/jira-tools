import os
import datetime
from jira import JIRA
import dateparser
from dotenv import load_dotenv

def get_jira_details(date_str):
    load_dotenv()
    jira_url = os.getenv("JIRA_URL")
    jira_username = os.getenv("JIRA_USERNAME")
    jira_pat = os.getenv("JIRA_PAT")
    if not all([jira_url, jira_username, jira_pat]):
        print("Error: JIRA_URL, JIRA_USERNAME, and JIRA_PAT must be set in the .env file.")
        return
    target_date = dateparser.parse(date_str).date()
    if not target_date:
        print(f"Error: Could not parse the date: {date_str}")
        return
    print(f"Fetching Jira details for date: {target_date.strftime('%Y-%m-%d')}")
    try:
        jira = JIRA(server=jira_url, token_auth=jira_pat)
        print("Successfully connected to Jira using token_auth.")
        server_info = jira.server_info()
        print(f"Jira Version: {server_info['version']}")
    except Exception as e:
        print(f"Error connecting to Jira with token_auth. Please check your PAT and VPN connection.")
        print(f"Details: {e}")
        return
    # Issues created
    print(f"\n--- Issues Created by {jira_username} On {target_date.strftime('%Y-%m-%d')} ---")
    try:
        jql_created = f"created >= '{target_date}' AND created < '{target_date + datetime.timedelta(days=1)}' AND reporter = '{jira_username}'"
        created_issues = jira.search_issues(jql_created)
        if created_issues:
            for issue in created_issues:
                print(f"- {issue.key}: {issue.fields.summary} ({issue.permalink()})")
        else:
            print(f"No issues were created by {jira_username} on this date.")
    except Exception as e:
        print(f"Error fetching created issues: {e}")
    # Work logged
    print(f"\n--- Work Logged by {jira_username} On {target_date.strftime('%Y-%m-%d')} ---")
    total_hours_logged = 0
    issue_hours = {}
    try:
        formatted_date = target_date.strftime('%Y/%m/%d')
        next_date = (target_date + datetime.timedelta(days=1)).strftime('%Y/%m/%d')
        jql_worklog = f'worklogDate >= "{formatted_date}" AND worklogDate < "{next_date}" AND worklogAuthor = currentUser()'
        logged_issues = jira.search_issues(jql_worklog, expand='worklog')
        if logged_issues:
            for issue in logged_issues:
                issue_total_hours = 0
                worklogs = jira.worklogs(issue.key)
                for worklog in worklogs:
                    try:
                        if '.' in worklog.started:
                            worklog_date = datetime.datetime.strptime(worklog.started, '%Y-%m-%dT%H:%M:%S.%f%z').date()
                        else:
                            worklog_date = datetime.datetime.strptime(worklog.started, '%Y-%m-%dT%H:%M:%S%z').date()
                    except ValueError:
                        worklog_date = datetime.datetime.fromisoformat(worklog.started.replace('Z', '+00:00')).date()
                    if worklog_date == target_date and worklog.author.name.lower() == jira_username.lower():
                        hours_logged = worklog.timeSpentSeconds / 3600
                        issue_total_hours += hours_logged
                        total_hours_logged += hours_logged
                if issue_total_hours > 0:
                    print(f"{issue.key} - {issue_total_hours:.0f}hrs ({issue.permalink()})")
                    issue_hours[issue.key] = issue_total_hours
        else:
            print(f"No issues with work logged by {jira_username} on this date.")
    except Exception as e:
        print(f"Error fetching work-logged issues: {e}")
    print("\n--- Total Work Hours ---")
    print(f"Total hours logged on {target_date}: {total_hours_logged:.0f} hours")


def run_cli():
    print("=== Jira Work Hours CLI ===")
    date_input = input("Enter a date (e.g., '24th Aug', 'yesterday', 'today', '2025-08-27'): ")
    get_jira_details(date_input)
