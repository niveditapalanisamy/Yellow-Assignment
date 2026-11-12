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
OLLAMA_API_KEY = os.getenv('OLLAMA_API_KEY', '')
OLLAMA_MODEL = os.getenv('OLLAMA_MODEL', 'gpt-oss:120b')
# Ollama Cloud by default; set http://127.0.0.1:11434/v1 for a local Ollama server.
OLLAMA_BASE_URL = os.getenv('OLLAMA_BASE_URL', 'https://ollama.com/v1').rstrip('/')

# Model provider: both expose an OpenAI-compatible /chat/completions API with tool calling.
LLM_PROVIDER = os.getenv('LLM_PROVIDER', 'groq').strip().lower()


def _providers():
    # Read module values at call time so configuration can be patched in tests.
    local = OLLAMA_BASE_URL.startswith(('http://127.0.0.1', 'http://localhost'))
    return {
        'groq': {'base_url': 'https://api.groq.com/openai/v1', 'api_key': GROQ_API_KEY,
                 'model': GROQ_MODEL, 'key_name': 'GROQ_API_KEY', 'key_required': True},
        # A local Ollama server needs no key; Ollama Cloud does.
        'ollama': {'base_url': OLLAMA_BASE_URL, 'api_key': OLLAMA_API_KEY, 'model': OLLAMA_MODEL,
                   'key_name': 'OLLAMA_API_KEY', 'key_required': not local},
    }


def provider_settings(name=None):
    name = (name or LLM_PROVIDER).strip().lower()
    providers = _providers()
    if name not in providers:
        raise RuntimeError(f'Unsupported LLM_PROVIDER {name!r}; use one of: ' + ', '.join(sorted(providers)))
    return {'provider': name, **providers[name]}


def llm_model_name():
    return _providers().get(LLM_PROVIDER, {}).get('model', GROQ_MODEL)


def llm_configured():
    settings = _providers().get(LLM_PROVIDER)
    if not settings:
        return False
    key = settings['api_key']
    return bool(key and not key.startswith('paste-')) or not settings['key_required']


REPORT_DIR = os.getenv('REPORT_DIR', 'reports')

# Record-kind labels written by the importer and used by the agent for discovery.
KIND_LABEL_PREFIX = os.getenv('JIRA_KIND_LABEL_PREFIX', 'tyn-kind-')
RELEASE_LABEL_PREFIX = os.getenv('JIRA_RELEASE_LABEL_PREFIX', 'tyn-release-')
MANIFEST_LABEL = KIND_LABEL_PREFIX + 'manifest'
REQUIREMENT_LABEL = KIND_LABEL_PREFIX + 'requirement'


def env_int(name, default, minimum=1, maximum=None):
    try:
        value = max(minimum, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        value = default
    return min(value, maximum) if maximum is not None else value


# Assessment defaults (CLI flags and dashboard requests can override them).
DEFAULT_RELEASE = os.getenv('JIRA_RELEASE', 'R2.4')
AGENT_BATCH_SIZE = env_int('AGENT_BATCH_SIZE', 1, 1, 3)
AGENT_TIMEOUT_SECONDS = env_int('AGENT_TIMEOUT_SECONDS', 1200, 30)
AGENT_MAX_TURNS = env_int('AGENT_MAX_TURNS', 14, 1)
AGENT_MAX_TOOLS = env_int('AGENT_MAX_TOOLS', 36, 1)
AGENT_MAX_CONTEXT_CHARS = env_int('AGENT_MAX_CONTEXT_CHARS', 240000, 10000)


def validate_jira_config():
    missing = [k for k in ('JIRA_BASE_URL', 'JIRA_EMAIL', 'JIRA_API_TOKEN') if not globals()[k] or 'your-' in globals()[k] or globals()[k].startswith('paste-')]
    if missing:
        raise RuntimeError('Missing Jira configuration: ' + ', '.join(missing))


def validate_agent_config():
    validate_jira_config()
    if not llm_configured():
        raise RuntimeError('Missing ' + provider_settings()['key_name'])
