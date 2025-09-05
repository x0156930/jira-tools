from setuptools import setup

setup(
    name="jira-work-hours",
    version="0.2.0",
    description="CLI to fetch Jira work hours and productivity",
    py_modules=["jira_logic_with_productivity", "main"],  # Added main module
    install_requires=[
        "jira",
        "python-dateutil",
        "python-dotenv",
        "dateparser"
    ],
    entry_points={
        'console_scripts': [
            'get-work-hours=main:main'
        ]
    }
)
