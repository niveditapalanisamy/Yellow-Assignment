"""Offline evaluation ONLY: not imported by the agent or exposed as a tool.

Expected decisions were independently reviewed from the supplied fictional scenario.
This is a regression check for an actual generated report, not an assessment engine.
"""
import argparse
import json
from pathlib import Path

EXPECTED = {'REQ-01': 'PASS', 'REQ-02': 'FAIL', 'REQ-03': 'INSUFFICIENT_EVIDENCE',
    'REQ-04': 'PASS', 'REQ-05': 'FAIL', 'REQ-06': 'INSUFFICIENT_EVIDENCE',
    'REQ-07': 'PASS', 'REQ-08': 'FAIL', 'REQ-09': 'INSUFFICIENT_EVIDENCE',
    'REQ-10': 'PASS', 'REQ-11': 'INSUFFICIENT_EVIDENCE', 'REQ-12': 'FAIL'}


def evaluate(path):
    report = json.loads(Path(path).read_text(encoding='utf-8'))
    actual = {x['requirement_id']: x['status'] for x in report['requirements']}
    mismatches = {k: {'expected': v, 'actual': actual.get(k)} for k, v in EXPECTED.items() if actual.get(k) != v}
    unexpected = sorted(set(actual) - set(EXPECTED))
    return {'passed': not mismatches and not unexpected and report['execution_status'] == 'COMPLETED'
        and report['overall_decision'] == 'BLOCKED', 'mismatches': mismatches,
        'unexpected': unexpected, 'execution_status': report['execution_status'], 'overall_decision': report['overall_decision']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report')
    result = evaluate(parser.parse_args().report)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['passed'] else 1)
