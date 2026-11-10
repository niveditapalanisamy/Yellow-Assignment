from __future__ import annotations
import base64
import re
from urllib.parse import urlencode, urlsplit
from . import config
from .http import APIError, JsonHTTP

JiraAPIError = APIError


def adf_to_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return ''.join(adf_to_text(x) for x in value)
    if not isinstance(value, dict):
        return ''
    if value.get('type') == 'text':
        return value.get('text', '')
    if value.get('type') == 'hardBreak':
        return '\n'
    text = adf_to_text(value.get('content', []))
    return text + ('\n' if value.get('type') in ('paragraph', 'heading', 'listItem') else '')


def source_id(issue):
    match = re.match(r'^\[([A-Za-z0-9_-]+)\]\s+', issue['fields'].get('summary', ''))
    return match.group(1) if match else None


def source_links(issue):
    match = re.search(r'Source linked record IDs:\s*\n([^\n]*)', adf_to_text(issue['fields'].get('description')))
    if not match:
        raise APIError('Missing source relationship metadata; reimport with the current importer')
    return [] if match.group(1).strip() == '(none)' else [x.strip() for x in match.group(1).split(',') if x.strip()]


class JiraClient:
    def __init__(self, project=None, label=None, transport=None):
        self.project, self.label = project or config.JIRA_PROJECT_KEY, label or config.JIRA_DATASET_LABEL
        if not re.fullmatch(r'[A-Z][A-Z0-9_]*', self.project):
            raise ValueError('Invalid Jira project key')
        if not re.fullmatch(r'[A-Za-z0-9_-]+', self.label):
            raise ValueError('Invalid dataset label')
        self.base_url = config.JIRA_BASE_URL
        if transport is None:
            config.validate_jira_config()
            parsed = urlsplit(self.base_url)
            if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.query or parsed.fragment:
                raise ValueError('JIRA_BASE_URL must be an HTTPS Jira site URL')
            auth = base64.b64encode(f'{config.JIRA_EMAIL}:{config.JIRA_API_TOKEN}'.encode()).decode()
            transport = JsonHTTP(self.base_url + '/rest/api/3', {'Authorization': 'Basic ' + auth})
        self.http = transport

    @property
    def scope(self):
        return f'project = "{self.project}" AND labels = "{self.label}"'

    def request(self, method, path, **kwargs):
        if 'params' in kwargs:
            path += '?' + urlencode(kwargs.pop('params'))
        return self.http.request(method, path, json_body=kwargs.get('json'), retry=method == 'GET' or path == '/search/jql')

    def _assert_in_scope(self, issue):
        fields = issue.get('fields', {})
        if fields.get('project', {}).get('key') != self.project or self.label not in fields.get('labels', []):
            raise APIError(f'Refusing out-of-scope issue {issue.get("key")}', 403)

    @staticmethod
    def valid_key(key):
        if not re.fullmatch(r'[A-Z][A-Z0-9_]*-[0-9]+', key):
            raise ValueError('Invalid Jira issue key')
        return key

    def get_issue(self, key):
        self.valid_key(key)
        issue = self.request('GET', f'/issue/{key}', params={'fields': 'project,summary,description,labels,status,issuelinks'})
        self._assert_in_scope(issue)
        return issue

    def search_jql(self, jql, max_results=500):
        result, token, seen = [], None, set()
        while True:
            body = {'jql': jql, 'maxResults': min(100, max_results - len(result)),
                    'fields': ['project', 'summary', 'description', 'labels', 'status', 'issuelinks']}
            if token:
                body['nextPageToken'] = token
            page = self.request('POST', '/search/jql', json=body)
            for issue in page.get('issues', []):
                self._assert_in_scope(issue)
                result.append(issue)
            token = page.get('nextPageToken')
            if not token or page.get('isLast'):
                return result
            if token in seen or not page.get('issues') or len(result) >= max_results:
                raise APIError('Jira search incomplete or pagination stalled; narrow the search')
            seen.add(token)

    def get_comments(self, key):
        self.get_issue(key)
        result, start = [], 0
        while True:
            page = self.request('GET', f'/issue/{key}/comment', params={'startAt': start, 'maxResults': 100})
            batch = page.get('comments', [])
            result.extend({'id': str(c['id']), 'body': adf_to_text(c.get('body')).strip(),
                'metadata_note': 'Native author/time are importer metadata; use recorded actors/events in body.'} for c in batch)
            start += len(batch)
            if start >= page.get('total', 0):
                return result
            if not batch or start > 10000:
                raise APIError('Jira comments incomplete or pagination stalled')

    def linked_records(self, issue):
        expected = set(source_links(issue))
        result = []
        for link in issue['fields'].get('issuelinks', []) or []:
            for direction in ('outwardIssue', 'inwardIssue'):
                other = link.get(direction)
                if other and source_id(other) in expected:
                    result.append({'key': other['key'], 'source_id': source_id(other)})
        missing = expected - {x['source_id'] for x in result}
        if missing:
            raise APIError('Missing native source links: ' + ', '.join(sorted(missing)))
        return result
