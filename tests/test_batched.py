import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from agent.graph import assess
from importer.jira_importer import run
from tests.fakes import client, ScriptedModel
from tests.test_agent import fixture


class BatchedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        data = fixture()
        data['records'][0]['links'] = ['REQ-01', 'REQ-02', 'REQ-03']
        for sid in ('REQ-02', 'REQ-03'):
            data['records'].append(dict(data['records'][1], source_id=sid, summary=sid))
        dataset = self.path/'synthetic.json'
        dataset.write_text(json.dumps(data), encoding='utf-8')
        self.jira = client()
        with contextlib.redirect_stdout(io.StringIO()):
            run(dataset, client=self.jira, summary_path=self.path/'import.json')

    def decisions(self):
        return [{'requirement_key': key, 'status': 'PASS',
            'rationale': 'QA confirms every mandatory test passes on the matching production target.',
            'outstanding': 'None.', 'references': [{'issue_key': 'TYN-3', 'comment_id': '10003',
                'quote': 'All 10 tests pass on TEST-1 abc1234 synthetic production.', 'why': 'QA evidence matches the target.'}]}
            for key in ('TYN-2', 'TYN-4', 'TYN-5')]

    def test_model_selects_bundle_before_evidence_is_in_context(self):
        model = ScriptedModel([('get_evidence_bundle', {'requirement_keys': ['TYN-2', 'TYN-4', 'TYN-5']}),
            ('submit_decisions', {'decisions': self.decisions()})])
        result = assess('TYN', self.jira.label, 'TEST-1', client=self.jira, model=model, output_dir=self.path)
        self.assertEqual(result['execution_status'], 'COMPLETED')
        self.assertEqual(result['overall_decision'], 'READY')
        self.assertEqual(len(result['requirements']), 3)
        self.assertEqual(result['metrics']['model_calls'], 2)
        self.assertNotIn('All 10 tests pass', json.dumps(model.seen[0]))
        self.assertIn('All 10 tests pass', json.dumps(model.seen[1]))

    def test_partial_batch_submission_requires_correction(self):
        model = ScriptedModel([('get_evidence_bundle', {'requirement_keys': ['TYN-2', 'TYN-4', 'TYN-5']}),
            ('submit_decisions', {'decisions': self.decisions()[:2]}),
            ('submit_decisions', {'decisions': self.decisions()})])
        result = assess('TYN', self.jira.label, 'TEST-1', client=self.jira, model=model, output_dir=self.path)
        self.assertEqual(result['execution_status'], 'COMPLETED')
        self.assertEqual(len(result['requirements']), 3)
        self.assertIn('exactly one decision', json.dumps(model.seen[-1]))

    def test_unknown_root_and_budget_cannot_approve(self):
        model = ScriptedModel([('get_evidence_bundle', {'requirement_keys': ['OTHER-1']})])
        result = assess('TYN', self.jira.label, 'TEST-1', client=self.jira, model=model, output_dir=self.path, max_turns=1)
        self.assertEqual(result['execution_status'], 'PARTIAL')
        self.assertEqual(result['overall_decision'], 'NEEDS_REVIEW')
        self.assertTrue(all(x['status'] == 'INSUFFICIENT_EVIDENCE' for x in result['requirements']))
