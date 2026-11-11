"""Configuration without third-party dependencies or import-time credential checks."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_env(path=None):
    path = Path(path or ROOT / '.env')
    for line in path.read_text(encoding='utf-8-sig').splitlines() if path.exists() else []:
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            os.environ.setdefault(key.strip(), value.strip().strip('\"\''))


load_env()
JIRA_BASE_URL = os.getenv('JIRA_BASE_URL', '').rstrip('/')
JIRA_EMAIL = os.getenv('JIRA_EMAIL', '')
JIRA_API_TOKEN = os.getenv('JIRA_API_TOKEN', '')
JIRA_PROJECT_KEY = os.getenv('JIRA_PROJECT_KEY', 'TYN').upper()
JIRA_DATASET_LABEL = os.getenv('JIRA_DATASET_LABEL', 'tyn-release-assessment-v2')
GROQ_API_KEY = os.getenv('GROQ_API_KEY', '')
GROQ_MODEL = os.getenv('GROQ_MODEL', 'openai/gpt-oss-120b')
REPORT_DIR = os.getenv('REPORT_DIR', 'reports')


def validate_jira_config():
    missing = [k for k in ('JIRA_BASE_URL', 'JIRA_EMAIL', 'JIRA_API_TOKEN') if not globals()[k] or 'your-' in globals()[k] or globals()[k].startswith('paste-')]
    if missing:
        raise RuntimeError('Missing Jira configuration: ' + ', '.join(missing))


def validate_agent_config():
    validate_jira_config()
    if not GROQ_API_KEY or GROQ_API_KEY.startswith('paste-'):
        raise RuntimeError('Missing GROQ_API_KEY')
