from django.urls import path
from django.shortcuts import redirect
from . import views

urlpatterns = [
    path('', lambda request: redirect('login'), name='root'),
    path('login/', views.login_view, name='login'),
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('report/daily/', views.daily_work_hours_view, name='daily_work_hours'),
    path('report/productivity/', views.daily_productivity_view, name='daily_productivity'),
    path('report/weekly/', views.weekly_productivity_view, name='weekly_productivity'),
    path('report/monthly/', views.monthly_productivity_view, name='monthly_productivity'),
    path('report/issue/', views.issue_productivity_view, name='issue_productivity'),
    path('report/timesheet/', views.timesheet_completeness_view, name='timesheet_completeness'),
    path('logout/', views.logout_view, name='logout'),
]
