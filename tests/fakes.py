"""An in-memory Jira REST double. Never imported by production code."""
from copy import deepcopy
import re
import threading
from urllib.parse import parse_qs, urlsplit

from agent.http import APIError
from agent.jira_client import JiraClient, adf_to_text


class MemoryJira:
    def __init__(self, page_size=100):
        self.lock = threading.RLock()
        self.issues = {}
        self.comments = {}
        self.writes = 0
        self.comment_id = 10000
        self.page_size = page_size
        self.deadline = None

    def request(self, method, path, json_body=None, retry=False):
        # Real Jira assigns issue/comment IDs atomically; concurrent importer tests
        # must provide the same guarantee rather than racing on len(issues).
        with self.lock:
            return self._request(method, path, json_body, retry)

    def _request(self, method, path, json_body=None, retry=False):
        parsed = urlsplit(path)
        path, params = parsed.path, parse_qs(parsed.query)
        body = json_body or {}
        if method in ('POST', 'PUT') and path != '/search/jql':
            self.writes += 1
        if path.startswith('/project/'):
            return {'key': path.split('/')[-1]}
        if path == '/search/jql':
            values = list(self.issues.values())
            jql = body['jql']
            project = re.search(r'project = "([^"]+)"', jql).group(1)
            labels = re.findall(r'labels = "([^"]+)"', jql)
            values = [x for x in values if x['fields']['project']['key'] == project
                and all(label in x['fields']['labels'] for label in labels)]
            start = int(body.get('nextPageToken', 0))
            size = min(self.page_size, body['maxResults'])
            result = {'issues': deepcopy(values[start:start + size])}
            if start + size < len(values):
                result['nextPageToken'] = str(start + size)
            else:
                result['isLast'] = True
            return result
        if path == '/issue' and method == 'POST':
            fields = deepcopy(body['fields'])
            key = fields['project']['key'] + '-' + str(len(self.issues) + 1)
            fields.update({'issuelinks': [], 'status': {'name': 'Done'}})
            self.issues[key] = {'key': key, 'fields': fields}
            self.comments[key] = []
            return {'key': key}
        if path == '/issueLink':
            a, b = body['inwardIssue']['key'], body['outwardIssue']['key']
            self.issues[a]['fields']['issuelinks'].append({'outwardIssue': {
                'key': b, 'fields': {'summary': self.issues[b]['fields']['summary']}}})
            self.issues[b]['fields']['issuelinks'].append({'inwardIssue': {
                'key': a, 'fields': {'summary': self.issues[a]['fields']['summary']}}})
            return None
        match = re.fullmatch(r'/issue/([A-Z0-9_-]+)(/comment)?', path)
        if not match or match[1] not in self.issues:
            raise APIError('Fake Jira 404', 404)
        key = match[1]
        if match[2]:
            if method == 'POST':
                self.comment_id += 1
                self.comments[key].append({'id': str(self.comment_id), 'body': deepcopy(body['body'])})
                return {'id': str(self.comment_id)}
            start = int(params.get('startAt', [0])[0])
            size = min(self.page_size, int(params.get('maxResults', [100])[0]))
            return {'comments': deepcopy(self.comments[key][start:start+size]), 'total': len(self.comments[key])}
        if method == 'PUT':
            self.issues[key]['fields'].update(deepcopy(body['fields']))
            return None
        return deepcopy(self.issues[key])


def client(transport=None):
    jira = JiraClient('TYN', 'tyn-release-assessment-v2', transport=transport or MemoryJira())
    jira.base_url = 'https://example.atlassian.net'
    return jira


class ScriptedModel:
    """Tool-calling orchestration test double, not a semantic evaluator."""
    name = 'TEST-DOUBLE-NOT-A-LIVE-MODEL'

    def __init__(self, actions):
        self.actions = iter(actions)
        self.seen = []

    def invoke(self, system, contents, declarations):
        self.seen.append(deepcopy(contents))
        name, args = next(self.actions)
        return {'role': 'model', 'parts': [{'functionCall': {'name': name, 'args': args}}]}, {'promptTokenCount': 10, 'candidatesTokenCount': 5}
