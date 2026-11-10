"""Repeatable, remote-verified import. This is the ONLY production module reading the dataset."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import time

from agent import config
from agent.jira_client import JiraClient, adf_to_text, source_id
from agent.http import APIError


def to_adf(text):
    return {'type': 'doc', 'version': 1, 'content': [
        {'type': 'paragraph', 'content': [{'type': 'text', 'text': line}] if line else []}
        for line in str(text).split('\n')]}


def description(rec, label):
    return '\n'.join([
        f"Source ID: {rec['source_id']}", f'Dataset label: {label}',
        f"Record kind: {rec['kind']}", f"Release: {rec['release']}",
        f"Source-recorded status: {rec['recorded_status']}", '', 'Source description:',
        rec['description'], '', 'Source linked record IDs:',
        ', '.join(rec['links']) or '(none)', '',
        'Import note: Fictional actors, roles and event timestamps are in source comment text. '
        'Native Jira authors and timestamps describe the importer, not scenario events.'])


def validate_dataset(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(data, dict) or not all(k in data for k in ('dataset_label', 'target', 'records')):
        raise ValueError('Dataset requires dataset_label, target, records')
    if not re.fullmatch(r'[A-Za-z0-9_-]+', data['dataset_label']):
        raise ValueError('Invalid dataset label')
    if not isinstance(data['records'], list) or not data['records']:
        raise ValueError('Records must be a nonempty list')
    if set(data['target']) != {'release', 'commit', 'service', 'environment', 'prompt'}:
        raise ValueError('Target requires release, commit, service, environment and prompt')
    ids = []
    for rec in data['records']:
        if not all(k in rec for k in ('source_id', 'kind', 'release', 'summary', 'description', 'recorded_status', 'comments', 'links')):
            raise ValueError('Record is missing required fields')
        if not re.fullmatch(r'[A-Za-z0-9_-]+', rec['source_id']):
            raise ValueError('Invalid source ID')
        if not all(isinstance(rec[k], str) for k in ('kind', 'release', 'summary', 'description', 'recorded_status')):
            raise ValueError('Record text must be strings')
        if not all(isinstance(rec[k], list) and all(isinstance(x, str) for x in rec[k]) for k in ('comments', 'links')):
            raise ValueError('Comments and links must be lists of strings')
        ids.append(rec['source_id'])
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate source IDs')
    missing = [(r['source_id'], x) for r in data['records'] for x in r['links'] if x not in set(ids)]
    if missing:
        raise ValueError(f'Unresolved relationship IDs: {missing[:10]}')
    return data


def issue_fields(rec, jira):
    slug = lambda x: re.sub('[^a-z0-9_-]+', '-', x.lower()).strip('-')
    return {'project': {'key': jira.project}, 'summary': f"[{rec['source_id']}] {rec['summary']}"[:255],
        'issuetype': {'name': os.getenv('JIRA_ISSUE_TYPE', 'Task')},
        'labels': [jira.label, 'tyn-kind-' + slug(rec['kind']), 'tyn-release-' + slug(rec['release'])],
        'description': to_adf(description(rec, jira.label))}


def verify_import(path='inputs/dataset.json', project=None, client=None):
    """Read-only fidelity audit; dataset remains import/verification input, never model context."""
    data = validate_dataset(path)
    jira = client or JiraClient(project=project, label=data['dataset_label'])
    issues = jira.search_jql(jira.scope, max_results=10000)
    mapping, errors = {}, []
    for issue in issues:
        sid = source_id(issue)
        if sid in mapping:
            errors.append('Duplicate source ID: ' + str(sid))
        mapping[sid] = issue
    def check(rec):
        sid = rec['source_id']
        issue = mapping.get(sid)
        failures = []
        if issue is None:
            return [sid + ': issue missing']
        try:
            if adf_to_text(issue['fields'].get('description')).strip() != description(rec, jira.label).strip():
                failures.append(sid + ': source text mismatch')
            comments = Counter(c['body'] for c in jira.get_comments(issue['key']))
            expected = Counter(rec['comments'])
            if comments != expected:
                failures.append(sid + ': comment multiset mismatch')
            if {x['source_id'] for x in jira.linked_records(issue)} != set(rec['links']):
                failures.append(sid + ': relationship mismatch')
        except Exception as exc:
            failures.append(sid + ': ' + str(exc))
        return failures
    with ThreadPoolExecutor(max_workers=8) as pool:
        for failures in pool.map(check, data['records']):
            errors.extend(failures)
    return {'verified': not errors, 'records_checked': len(data['records']),
        'comments_checked': sum(len(r['comments']) for r in data['records']),
        'relationships_checked': sum(len(r['links']) for r in data['records']), 'errors': errors}


def run(path='inputs/dataset.json', dry_run=False, project=None, client=None, summary_path='import_summary.json', workers=8):
    started = time.monotonic()
    data = validate_dataset(path)
    summary = {'dataset_label': data['dataset_label'], 'target': data['target'],
        'source_sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        'source_records': len(data['records']), 'source_comments': sum(len(r['comments']) for r in data['records']),
        'source_directed_relationships': sum(len(r['links']) for r in data['records']),
        'issues_created': 0, 'issues_updated': 0, 'issues_existing': 0, 'comments_added': 0,
        'comments_existing': 0, 'links_added': 0, 'links_existing': 0, 'failures': []}
    if dry_run:
        summary.update({'dry_run': True, 'elapsed_seconds': round(time.monotonic() - started, 4)})
        print(json.dumps(summary, indent=2))
        return summary
    jira = client or JiraClient(project=project, label=data['dataset_label'])
    if jira.label != data['dataset_label']:
        raise ValueError('Importer label must equal dataset_label in the dataset')
    jira.request('GET', '/project/' + jira.project)
    # Jira is authoritative; never trust a local mapping from another site/project.
    existing = jira.search_jql(jira.scope + ' ORDER BY key ASC', max_results=10000)
    mapping = {}
    for issue in existing:
        sid = source_id(issue)
        if sid:
            if sid in mapping:
                raise ValueError('Duplicate imported source ID in Jira: ' + sid)
            mapping[sid] = issue['key']
    existing_by_key = {x['key']: x for x in existing}
    failed_issues = set()
    def import_issue(rec):
        sid = rec['source_id']
        try:
            fields = issue_fields(rec, jira)
            if sid not in mapping:
                result = jira.request('POST', '/issue', json={'fields': fields})
                return sid, result['key'], 'issues_created', None
            else:
                old = existing_by_key[mapping[sid]]['fields']
                if adf_to_text(old.get('description')).strip() != description(rec, jira.label).strip():
                    jira.request('PUT', '/issue/' + mapping[sid], json={'fields': {
                        'summary': fields['summary'], 'description': fields['description'],
                        'labels': sorted(set(old.get('labels', [])) | set(fields['labels']))}})
                    return sid, mapping[sid], 'issues_updated', None
                return sid, mapping[sid], 'issues_existing', None
        except Exception as exc:
            return sid, None, None, str(exc)
    with ThreadPoolExecutor(max_workers=max(1, min(workers, 8))) as pool:
        for index, (sid, key, counter, error) in enumerate(pool.map(import_issue, data['records']), 1):
            if error:
                failed_issues.add(sid)
                summary['failures'].append({'source_id': sid, 'stage': 'issue', 'error': error})
            else:
                mapping[sid] = key
                summary[counter] += 1
            if index % 50 == 0:
                print(f"Issues processed: {index}/{len(data['records'])}", flush=True)
    def import_comments(rec):
        sid, key = rec['source_id'], mapping.get(rec['source_id'])
        counts = {'comments_added': 0, 'comments_existing': 0}
        if not key or sid in failed_issues:
            return sid, counts, None
        try:
            # Each ticket's comments are sequential; separate tickets are independent.
            existing_counts = Counter(c['body'] for c in jira.get_comments(key))
            for body in rec['comments']:
                if existing_counts[body] > 0:
                    existing_counts[body] -= 1
                    counts['comments_existing'] += 1
                else:
                    jira.request('POST', f'/issue/{key}/comment', json={'body': to_adf(body)})
                    counts['comments_added'] += 1
            return sid, counts, None
        except Exception as exc:
            return sid, counts, str(exc)
    with ThreadPoolExecutor(max_workers=max(1, min(workers, 8))) as pool:
        for index, (sid, counts, error) in enumerate(pool.map(import_comments, data['records']), 1):
            for key, value in counts.items():
                summary[key] += value
            if error:
                summary['failures'].append({'source_id': sid, 'stage': 'comments', 'error': error})
            if index % 50 == 0:
                print(f"Comment threads processed: {index}/{len(data['records'])}", flush=True)
    for rec in data['records']:
        sid, key = rec['source_id'], mapping.get(rec['source_id'])
        if not key or sid in failed_issues:
            continue
        if not rec['links']:
            continue
        try:
            issue = jira.get_issue(key)
            current = {v['key'] for link in issue['fields'].get('issuelinks', [])
                       for k, v in link.items() if k in ('outwardIssue', 'inwardIssue')}
            for target in rec['links']:
                if target not in mapping or target in failed_issues:
                    raise APIError('Missing imported target: ' + target)
                other = mapping[target]
                if other in current:
                    summary['links_existing'] += 1
                else:
                    jira.request('POST', '/issueLink', json={'type': {'name': 'Relates'},
                        'inwardIssue': {'key': key}, 'outwardIssue': {'key': other}})
                    current.add(other)
                    summary['links_added'] += 1
        except Exception as exc:
            summary['failures'].append({'source_id': sid, 'stage': 'links', 'error': str(exc)})
    summary.update({'project': jira.project, 'elapsed_seconds': round(time.monotonic() - started, 3), 'mapping': mapping})
    Path(summary_path).write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in summary.items() if k != 'mapping'}, indent=2))
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', default='inputs/dataset.json')
    parser.add_argument('--project', default=config.JIRA_PROJECT_KEY)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--verify', action='store_true', help='Read-only comparison of imported records to source')
    args = parser.parse_args()
    try:
        if args.verify:
            result = verify_import(args.dataset, args.project)
            print(json.dumps(result, indent=2))
            raise SystemExit(0 if result['verified'] else 2)
        else:
            result = run(args.dataset, args.dry_run, args.project, workers=args.workers)
            raise SystemExit(2 if result['failures'] else 0)
    except (ValueError, RuntimeError) as exc:
        parser.exit(2, str(exc) + '\n')
