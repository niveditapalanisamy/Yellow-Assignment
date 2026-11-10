import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from agent.graph import assess
from agent.http import APIError
from agent.jira_client import adf_to_text
from agent.tools import EvidenceTools
from importer.jira_importer import run, to_adf
from tests.fakes import client, MemoryJira, ScriptedModel

TARGET = {'release': 'TEST-1', 'commit': 'abc1234', 'service': 'synthetic', 'environment': 'production', 'prompt': 'p1'}


def fixture():
    def record(sid, kind, desc, comments, links):
        return {'source_id': sid, 'kind': kind, 'summary': sid, 'release': 'TEST-1',
            'recorded_status': 'Done', 'description': desc, 'comments': comments, 'links': links}
    target = 'Target: ' + json.dumps(TARGET)
    return {'dataset_label': 'tyn-release-assessment-v2', 'target': TARGET, 'records': [
        record('MANIFEST', 'manifest', target + '\nAll linked requirements are mandatory.', ['Policy recorded by QA.'], ['REQ-01']),
        record('REQ-01', 'requirement', target + '\nMandatory: yes\nAcceptance criterion: All tests pass.', ['Implementation claim is not QA.'], ['REC-1']),
        record('REC-1', 'evidence', 'QA evidence', ['Recorded event 2026-11-08T10:00:00+05:30 | actor Test QA | role QA Lead\nAll 10 tests pass on TEST-1 abc1234 synthetic production.'], [])]}


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.dataset = self.path/'synthetic.json'
        self.dataset.write_text(json.dumps(fixture()), encoding='utf-8')
        self.jira = client(MemoryJira(page_size=1))
        with contextlib.redirect_stdout(io.StringIO()):
            run(self.dataset, client=self.jira, summary_path=self.path/'import.json')

    def decision(self, quote='All 10 tests pass on TEST-1 abc1234 synthetic production.'):
        return {'status': 'PASS', 'rationale': 'QA confirms all mandatory tests pass for the exact target scope.',
            'outstanding': 'None.', 'references': [{'issue_key': 'TYN-3', 'comment_id': '10003',
                'quote': quote, 'why': 'QA result matches release, commit, service and production.'}]}

    def test_tool_loop_generates_report_trace_and_usage(self):
        model = ScriptedModel([('get_record', {'issue_key': 'TYN-2'}),
            ('get_record', {'issue_key': 'TYN-3'}), ('submit_decision', self.decision())])
        result = assess('TYN', self.jira.label, 'TEST-1', client=self.jira, model=model, output_dir=self.path)
        self.assertEqual(result['execution_status'], 'COMPLETED')
        self.assertEqual(result['overall_decision'], 'READY')
        self.assertEqual(result['metrics']['model_calls'], 3)
        self.assertEqual(result['metrics']['usage']['promptTokenCount'], 30)
        report = Path(result['report_path']).read_text(encoding='utf-8')
        self.assertIn('focusedCommentId=10003', report)
        trace = [json.loads(x) for x in Path(result['trace_path']).read_text().splitlines()]
        self.assertTrue(any(x['kind'] == 'tool' and x['name'] == 'get_record' and x['actor'] == 'model' for x in trace))
        self.assertNotIn('source_records', json.dumps(model.seen))

    def test_fabricated_citation_and_omitted_dependency_rejected(self):
        tools = EvidenceTools(self.jira)
        tools.get_record('TYN-2')
        with self.assertRaisesRegex(ValueError, 'Inspect linked ticket'):
            tools.validate_decision(self.decision(), 'TYN-2')
        tools.get_record('TYN-3')
        with self.assertRaisesRegex(ValueError, 'verbatim'):
            tools.validate_decision(self.decision('Fabricated result not in any retrieved evidence.'), 'TYN-2')

    def test_model_failure_produces_honest_partial_artifacts(self):
        model = ScriptedModel([])
        result = assess('TYN', self.jira.label, 'TEST-1', client=self.jira, model=model, output_dir=self.path)
        self.assertEqual(result['execution_status'], 'PARTIAL')
        self.assertEqual(result['overall_decision'], 'NEEDS_REVIEW')
        self.assertEqual(result['requirements'][0]['status'], 'INSUFFICIENT_EVIDENCE')
        self.assertTrue(Path(result['trace_path']).exists())

    def test_unknown_release_fails_before_model(self):
        model = ScriptedModel([])
        result = assess('TYN', self.jira.label, 'NONEXISTENT', client=self.jira, model=model, output_dir=self.path)
        self.assertEqual(result['execution_status'], 'FAILED')
        self.assertFalse(result['requirements'])
        self.assertEqual(result['metrics']['model_calls'], 0)

    def test_scope_guard_prevents_cross_project_and_label_reads(self):
        self.jira.http.issues['TYN-3']['fields']['labels'] = ['different-dataset']
        with self.assertRaisesRegex(APIError, 'out-of-scope'):
            self.jira.get_comments('TYN-3')
        self.jira.http.issues['TYN-2']['fields']['project']['key'] = 'OTHER'
        with self.assertRaises(APIError):
            self.jira.get_issue('TYN-2')

    def test_budget_exhaustion_cannot_approve(self):
        model = ScriptedModel([('get_record', {'issue_key': 'TYN-2'})])
        result = assess('TYN', self.jira.label, 'TEST-1', client=self.jira, model=model,
            output_dir=self.path, max_turns=1)
        self.assertEqual(result['overall_decision'], 'NEEDS_REVIEW')
        self.assertIn('budget', result['errors'][0])

    def test_invalid_keys_and_labels_rejected(self):
        with self.assertRaises(ValueError):
            self.jira.get_issue('../other')
        from agent.jira_client import JiraClient
        with self.assertRaises(ValueError):
            JiraClient('TYN', 'x" OR project=OTHER', transport=MemoryJira())

    def test_adf_roundtrip_preserves_newlines(self):
        text = 'Actor and role\n\nExact text with symbols: ≥ p95.'
        self.assertEqual(adf_to_text(to_adf(text)).strip(), text)

    def test_nested_dependency_must_be_inspected(self):
        data = fixture()
        data['records'][2]['links'] = ['REC-2']
        nested = dict(data['records'][2], source_id='REC-2', summary='Nested defect',
            links=[], comments=['QA confirms a target build defect remains open.'])
        data['records'].append(nested)
        self.dataset.write_text(json.dumps(data), encoding='utf-8')
        with contextlib.redirect_stdout(io.StringIO()):
            run(self.dataset, client=self.jira, summary_path=self.path/'import2.json')
        tools = EvidenceTools(self.jira)
        tools.get_record('TYN-2')
        tools.get_record('TYN-3')
        with self.assertRaisesRegex(ValueError, 'TYN-4'):
            tools.validate_decision(self.decision(), 'TYN-2')
        tools.get_record('TYN-4')
        self.assertEqual(tools.validate_decision(self.decision(), 'TYN-2')['status'], 'PASS')

    def test_comments_past_first_page_are_retrieved(self):
        for index in range(120):
            self.jira.http.request('POST', '/issue/TYN-3/comment', json_body={
                'body': to_adf('Noise event ' + str(index))})
        self.jira.http.request('POST', '/issue/TYN-3/comment', json_body={
            'body': to_adf('Final QA evidence after all noise: a mandatory case fails.')})
        comments = self.jira.get_comments('TYN-3')
        self.assertEqual(len(comments), 122)
        self.assertIn('mandatory case fails', comments[-1]['body'])

    def test_broken_link_is_reported(self):
        self.jira.http.issues['TYN-2']['fields']['issuelinks'] = []
        with self.assertRaisesRegex(APIError, 'Missing native source links'):
            EvidenceTools(self.jira).get_record('TYN-2')

    def test_ambiguous_manifest_cannot_approve(self):
        data = fixture()
        data['records'][0]['source_id'] = 'MANIFEST-OTHER'
        self.dataset.write_text(json.dumps(data), encoding='utf-8')
        with contextlib.redirect_stdout(io.StringIO()):
            run(self.dataset, client=self.jira, summary_path=self.path/'second-manifest.json')
        result = assess('TYN', self.jira.label, 'TEST-1', client=self.jira, model=ScriptedModel([]), output_dir=self.path)
        self.assertEqual(result['execution_status'], 'FAILED')
        self.assertEqual(result['overall_decision'], 'NEEDS_REVIEW')

    def test_search_tool_results_are_valid_gemini_objects(self):
        model = ScriptedModel([('get_record', {'issue_key': 'TYN-2'}),
            ('get_record', {'issue_key': 'TYN-3'}), ('search_issues', {'query': 'regression'}),
            ('submit_decision', self.decision())])
        result = assess('TYN', self.jira.label, 'TEST-1', client=self.jira, model=model, output_dir=self.path)
        self.assertEqual(result['execution_status'], 'COMPLETED')
        function_response = model.seen[-1][-1]['parts'][0]['functionResponse']
        self.assertIsInstance(function_response['response'], dict)
        self.assertIsInstance(function_response['response']['result'], list)
