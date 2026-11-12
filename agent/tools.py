"""The agent has no filesystem/network tool: evidence access is exclusively scoped Jira."""
import json
import re
from .jira_client import adf_to_text, source_id


def object_schema(properties, required):
    return {'type': 'OBJECT', 'properties': properties, 'required': required}


STRING = {'type': 'STRING'}
DECLARATIONS = [
    {'name': 'get_record', 'description': 'Read an in-scope Jira ticket, ALL its comments and forward source relationships. Follow linked records recursively, including implementation dependencies.',
     'parameters': object_schema({'issue_key': STRING}, ['issue_key'])},
    {'name': 'search_issues', 'description': 'Search scoped Jira records by phrase or source ID. Returns metadata; use get_record to read evidence. No raw JQL accepted.',
     'parameters': object_schema({'query': STRING}, ['query'])},
    {'name': 'submit_decision', 'description': 'Submit the investigated requirement decision. Cite exact comment excerpts. Explain applicable and rejected evidence, conflicts, supersession, and needed follow-up. Server checks coverage/citations and computes overall release status.',
     'parameters': object_schema({
         'status': {'type': 'STRING', 'enum': ['PASS', 'FAIL', 'INSUFFICIENT_EVIDENCE'],
             'description': 'FAIL needs an applicable demonstrated bad result or explicit applicable rejection. Missing approval or wrong-scope proof => INSUFFICIENT_EVIDENCE. Equally authoritative contradictory target-scope results with no explicit resolution => INSUFFICIENT_EVIDENCE; never cherry-pick a passing result.'},
         'rationale': STRING, 'outstanding': STRING,
         'references': {'type': 'ARRAY', 'items': object_schema({
             'issue_key': STRING, 'comment_id': STRING, 'quote': STRING, 'why': STRING},
             ['issue_key', 'comment_id', 'quote', 'why'])}}, ['status', 'rationale', 'outstanding', 'references'])}
]


class EvidenceTools:
    def __init__(self, jira):
        self.jira = jira
        self.records = {}

    def get_record(self, issue_key):
        issue = self.jira.get_issue(issue_key)
        result = {'key': issue_key, 'source_id': source_id(issue),
            'summary': issue['fields']['summary'],
            'description': adf_to_text(issue['fields'].get('description')).strip(),
            # Stated once per record rather than on every comment (long threads multiply it).
            'comment_note': 'Native Jira author/time are importer metadata; use the recorded actor, role and event time in each body.',
            'comments': self.jira.get_comments(issue_key), 'links': self.jira.linked_records(issue)}
        if len(json.dumps(result)) > 150000:
            raise RuntimeError('Record exceeds context budget; no comments silently truncated')
        self.records[issue_key] = result
        return result

    def search_issues(self, query):
        if not isinstance(query, str) or not query.strip() or len(query) > 120:
            raise ValueError('Search requires a phrase of 1-120 characters')
        # Exact source IDs use a summary match; escape Lucene and then JQL separately.
        phrase = re.sub(r'([+\-!(){}\[\]^"~*?:\\/])', r'\\\1', query.strip())
        lucene = '"' + phrase + '"'
        escaped = lucene.replace('\\', '\\\\').replace('"', '\\"')
        found = self.jira.search_jql(self.jira.scope + ' AND text ~ "' + escaped + '" ORDER BY key ASC', max_results=30)
        return [{'key': x['key'], 'source_id': source_id(x), 'summary': x['fields']['summary']} for x in found]

    def validate_decision(self, decision, root):
        if decision.get('status') not in ('PASS', 'FAIL', 'INSUFFICIENT_EVIDENCE'):
            raise ValueError('Invalid decision status')
        if not isinstance(decision.get('rationale'), str) or len(decision['rationale']) < 30:
            raise ValueError('A substantive rationale is required')
        if not isinstance(decision.get('outstanding'), str):
            raise ValueError('Outstanding verification or clarification must be specified')
        # Read every source-linked dependency, avoiding reverse Jira links and cycles.
        pending, visited = [root], set()
        while pending:
            key = pending.pop()
            if key in visited:
                continue
            visited.add(key)
            if key not in self.records:
                raise ValueError('Inspect linked ticket and its comments first: ' + key)
            pending.extend(x['key'] for x in self.records[key]['links'])
        refs = decision.get('references')
        if not isinstance(refs, list) or not refs:
            raise ValueError('At least one inspected comment reference is required')
        for ref in refs:
            if not isinstance(ref, dict) or not isinstance(ref.get('quote'), str) or len(ref['quote']) < 12:
                raise ValueError('Cite an exact comment excerpt of at least 12 characters')
            record = self.records.get(ref.get('issue_key'))
            comment = next((c for c in (record or {}).get('comments', []) if c['id'] == ref.get('comment_id')), None)
            if not comment or ref['quote'] not in comment['body']:
                raise ValueError('Reference must quote an actually retrieved Jira comment verbatim')
            if not isinstance(ref.get('why'), str) or not ref['why'].strip():
                raise ValueError('Explain the applicability of each reference')
        return decision


def target_from_description(text):
    match = re.search(r'^Target:\s*(\{[^\n]+\})', text, re.MULTILINE)
    if not match:
        raise ValueError('No structured target in Jira manifest')
    target = json.loads(match.group(1))
    if set(target) != {'release', 'commit', 'service', 'environment', 'prompt'} or not all(isinstance(x, str) and x for x in target.values()):
        raise ValueError('Incomplete target metadata in Jira manifest')
    return target
