"""Extract our submission zip into an isolated temporary directory and run tests without credentials."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def smoke():
    with tempfile.TemporaryDirectory(prefix='jira-release-package-') as temp:
        destination = Path(temp).resolve()
        with zipfile.ZipFile(ROOT/'jira-release-evidence-agent.zip') as archive:
            for member in archive.infolist():
                if not (destination/member.filename).resolve().is_relative_to(destination):
                    raise RuntimeError('Unsafe archive member')
                if Path(member.filename).name == '.env':
                    raise RuntimeError('Credential file in archive')
            archive.extractall(destination)
        env = {k: v for k, v in os.environ.items() if not k.startswith(('JIRA_', 'GROQ_', 'GOOGLE_'))}
        result = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-v'],
            cwd=destination, env=env, capture_output=True, text=True, timeout=60)
        text = 'Extracted submission tested without Jira/Groq environment variables.\n' + result.stdout + result.stderr
        (ROOT/'submission/package_smoke_test.txt').write_text(text, encoding='utf-8')
        print(text[-220:])
        if result.returncode:
            raise SystemExit(result.returncode)


if __name__ == '__main__':
    smoke()
