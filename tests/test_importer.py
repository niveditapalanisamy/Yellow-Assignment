from collections import Counter
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from agent.jira_client import adf_to_text, source_id, source_links
from importer.jira_importer import run, validate_dataset, verify_import
from tests.fakes import client, MemoryJira

DATASET = Path(__file__).resolve().parents[1] / 'inputs/dataset.json'


class ImportTests(unittest.TestCase):
    def test_full_dataset_exact_fidelity_and_repeatability(self):
        jira = client(MemoryJira(page_size=23))
        data = validate_dataset(DATASET)
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            first = run(DATASET, client=jira, summary_path=Path(tmp)/'summary.json')
            writes = jira.http.writes
            second = run(DATASET, client=jira, summary_path=Path(tmp)/'summary.json')
        self.assertEqual(first['issues_created'], 400)
        self.assertEqual(first['comments_added'], 2059)
        self.assertFalse(first['failures'])
        self.assertFalse(second['failures'])
        self.assertEqual(writes, jira.http.writes, 'Repeat import must perform zero writes')
        self.assertEqual(second['comments_existing'], 2059)
        for rec in data['records']:
            key = first['mapping'][rec['source_id']]
            issue = jira.get_issue(key)
            self.assertEqual(source_id(issue), rec['source_id'])
            self.assertEqual(source_links(issue), rec['links'])
            self.assertIn(rec['description'], adf_to_text(issue['fields']['description']))
            self.assertEqual(Counter(c['body'] for c in jira.get_comments(key)), Counter(rec['comments']))
            self.assertEqual({x['source_id'] for x in jira.linked_records(issue)}, set(rec['links']))
        audit = verify_import(DATASET, client=jira)
        self.assertTrue(audit['verified'])
        self.assertEqual(audit['comments_checked'], 2059)

    def test_dry_run_has_no_credentials_or_writes(self):
        with contextlib.redirect_stdout(io.StringIO()):
            result = run(DATASET, dry_run=True)
        self.assertTrue(result['dry_run'])
        self.assertEqual(result['source_comments'], 2059)

    def test_duplicate_and_dangling_ids_are_rejected(self):
        data = validate_dataset(DATASET)
        for mutation in ('duplicate', 'dangling'):
            modified = json.loads(json.dumps(data))
            if mutation == 'duplicate':
                modified['records'].append(modified['records'][0])
            else:
                modified['records'][0]['links'].append('NONEXISTENT')
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp)/'bad.json'
                path.write_text(json.dumps(modified), encoding='utf-8')
                with self.assertRaises(ValueError):
                    validate_dataset(path)

    def test_label_mismatch_rejected_before_writes(self):
        jira = client()
        jira.label = 'other-import'
        with self.assertRaises(ValueError), contextlib.redirect_stdout(io.StringIO()):
            run(DATASET, client=jira)
        self.assertEqual(jira.http.writes, 0)
