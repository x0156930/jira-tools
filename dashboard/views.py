from django.shortcuts import render, redirect
from django.views.decorators.csrf import csrf_protect
from django.contrib import messages
from django.conf import settings
import os
import datetime
from jira import JIRA
from .jira_logic import (
    connect_to_jira, 
    get_jira_details, 
    get_issue_productivity, 
    get_daily_productivity,
    get_range_productivity,
    get_timesheet_completeness
)

# Store credentials in session after login
@csrf_protect
def login_view(request):
    if request.method == 'POST':
        jira_url = request.POST.get('jira_url')
        jira_username = request.POST.get('jira_username')
        jira_pat = request.POST.get('jira_pat')
        try:
            jira = JIRA(server=jira_url, token_auth=jira_pat)
            # Test connection
            jira.myself()
            request.session['jira_url'] = jira_url
            request.session['jira_username'] = jira_username
            request.session['jira_pat'] = jira_pat
            return redirect('dashboard')
        except Exception as e:
            return render(request, 'login.html', {'error': f'Login failed: {e}'})
    return render(request, 'login.html')

def dashboard_view(request):
    if not request.session.get('jira_url') or not request.session.get('jira_pat'):
        return redirect('login')
    # Placeholder for dashboard features
    return render(request, 'dashboard.html', {'username': request.session.get('jira_username')})

def daily_work_hours_view(request):
    if not request.session.get('jira_url') or not request.session.get('jira_pat'):
        return redirect('login')
    result = None
    error = None
    if request.method == 'POST':
        date_str = request.POST.get('date')
        jira, jira_username = connect_to_jira(
            request.session['jira_url'],
            request.session['jira_username'],
            request.session['jira_pat']
        )
        if jira:
            result, error = get_jira_details(jira, jira_username, date_str)
        else:
            error = 'Could not connect to Jira.'
    return render(request, 'daily_work_hours.html', {'result': result, 'error': error})

def daily_productivity_view(request):
    if not request.session.get('jira_url') or not request.session.get('jira_pat'):
        return redirect('login')
    result = None
    error = None
    if request.method == 'POST':
        date_str = request.POST.get('date')
        jira, jira_username = connect_to_jira(
            request.session['jira_url'],
            request.session['jira_username'],
            request.session['jira_pat']
        )
        if jira:
            result, error = get_daily_productivity(jira, jira_username, date_str)
        else:
            error = 'Could not connect to Jira.'
    return render(request, 'daily_productivity.html', {'result': result, 'error': error})

def weekly_productivity_view(request):
    if not request.session.get('jira_url') or not request.session.get('jira_pat'):
        return redirect('login')
    result = None
    error = None
    if request.method == 'POST':
        exclude_weekends = request.POST.get('exclude_weekends') == 'on'
        # Default to last 7 days
        end_date = datetime.date.today()
        start_date = end_date - datetime.timedelta(days=6)
        start_date_str = start_date.strftime('%Y-%m-%d')
        end_date_str = end_date.strftime('%Y-%m-%d')
        
        jira, jira_username = connect_to_jira(
            request.session['jira_url'],
            request.session['jira_username'],
            request.session['jira_pat']
        )
        if jira:
            result, error = get_range_productivity(
                jira, jira_username, start_date_str, end_date_str, "Weekly", exclude_weekends
            )
        else:
            error = 'Could not connect to Jira.'
    
    # For GET request, pre-fill the form
    end_date = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=6)
    
    context = {
        'result': result, 
        'error': error,
        'start_date': start_date.strftime('%Y-%m-%d'),
        'end_date': end_date.strftime('%Y-%m-%d')
    }
    return render(request, 'weekly_productivity.html', context)

def monthly_productivity_view(request):
    if not request.session.get('jira_url') or not request.session.get('jira_pat'):
        return redirect('login')
    result = None
    error = None
    if request.method == 'POST':
        exclude_weekends = request.POST.get('exclude_weekends') == 'on'
        start_date_str = request.POST.get('start_date')
        end_date_str = request.POST.get('end_date')
        
        jira, jira_username = connect_to_jira(
            request.session['jira_url'],
            request.session['jira_username'],
            request.session['jira_pat']
        )
        if jira:
            result, error = get_range_productivity(
                jira, jira_username, start_date_str, end_date_str, "Monthly", exclude_weekends
            )
        else:
            error = 'Could not connect to Jira.'
    
    # For GET request, pre-fill the form with last 30 days
    end_date = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=29)
    
    context = {
        'result': result, 
        'error': error,
        'start_date': start_date.strftime('%Y-%m-%d'),
        'end_date': end_date.strftime('%Y-%m-%d')
    }
    return render(request, 'monthly_productivity.html', context)

def issue_productivity_view(request):
    if not request.session.get('jira_url') or not request.session.get('jira_pat'):
        return redirect('login')
    result = None
    error = None
    if request.method == 'POST':
        issue_key = request.POST.get('issue_key').strip().upper()
        jira, _ = connect_to_jira(
            request.session['jira_url'],
            request.session['jira_username'],
            request.session['jira_pat']
        )
        if jira:
            result, error = get_issue_productivity(jira, issue_key)
        else:
            error = 'Could not connect to Jira.'
    return render(request, 'issue_productivity.html', {'result': result, 'error': error})

def timesheet_completeness_view(request):
    if not request.session.get('jira_url') or not request.session.get('jira_pat'):
        return redirect('login')
    result = None
    error = None
    if request.method == 'POST':
        start_date_str = request.POST.get('start_date')
        end_date_str = request.POST.get('end_date')
        exclude_weekends = request.POST.get('exclude_weekends') == 'on'
        
        jira, jira_username = connect_to_jira(
            request.session['jira_url'],
            request.session['jira_username'],
            request.session['jira_pat']
        )
        if jira:
            result, error = get_timesheet_completeness(jira, jira_username, start_date_str, end_date_str, exclude_weekends)
        else:
            error = 'Could not connect to Jira.'
    
    # Default values for GET request
    end_date = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=6)  # Last week
    
    context = {
        'result': result, 
        'error': error,
        'start_date': start_date.strftime('%Y-%m-%d'),
        'end_date': end_date.strftime('%Y-%m-%d')
    }
    return render(request, 'timesheet_completeness.html', context)

def logout_view(request):
    # Clear session data
    request.session.flush()
    return redirect('login')
