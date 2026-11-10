"""Build an allowlisted zip; reject files containing configured credential values."""
from pathlib import Path
import zipfile
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent import config


def package():
    files = [ROOT/x for x in ['README.md', 'requirements.txt', 'requirements-dev.txt', '.env.example',
        '.gitignore', '.python-version', 'pytest.ini', 'render.yaml', 'app.py', 'start_backend.bat', 'start_frontend.bat']]
    for folder in ('agent', 'backend', 'frontend', 'importer', 'inputs', 'tests', 'scripts', 'docs', 'submission'):
        files.extend(p for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts
            and p.suffix in ('.py', '.json', '.jsonl', '.md', '.html', '.txt', '.svg', '.png'))
    import os
    secrets = [x.encode() for x in (config.JIRA_API_TOKEN, config.GEMINI_API_KEY, os.getenv('RENDER_API_KEY', '')) if len(x) >= 12]
    for p in files:
        if any(s in p.read_bytes() for s in secrets):
            raise RuntimeError('Credential scan failed: ' + str(p.relative_to(ROOT)))
    target = ROOT/'jira-release-evidence-agent.zip'
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        for p in sorted(set(files)):
            archive.write(p, p.relative_to(ROOT))
    print(f'Created {target.name}: {len(set(files))} files, {target.stat().st_size} bytes. Credential scan passed.')


if __name__ == '__main__':
    package()
