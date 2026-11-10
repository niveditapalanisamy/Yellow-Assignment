"""Small model-selected evidence bundles reduce API calls without preloading the dataset."""
from copy import deepcopy
import json
import time

from .tools import DECLARATIONS, EvidenceTools, object_schema, STRING
from .jira_client import source_id


def investigate_group(issues, manifest, target, jira, model, system, call, trace, metrics,
                      deadline, max_turns, max_tools):
    tools = EvidenceTools(jira)
    roots = {x['key']: x for x in issues}
    schema = deepcopy(DECLARATIONS[-1]['parameters'])
    schema['properties']['requirement_key'] = STRING
    schema['required'].append('requirement_key')
    declarations = [
        {'name': 'get_evidence_bundle', 'description': 'Read selected requirement roots and all forward linked dependencies, with every comment page. Choose one to three requirement keys from the current group. No evidence is preloaded.',
         'parameters': object_schema({'requirement_keys': {'type': 'ARRAY', 'items': STRING}}, ['requirement_keys'])},
        *deepcopy(DECLARATIONS[:2]),
        {'name': 'submit_decisions', 'description': 'Submit exactly one decision for every requirement in this group, with exact Jira comment quotes and follow-up.',
         'parameters': object_schema({'decisions': {'type': 'ARRAY', 'items': schema}}, ['decisions'])}]

    def bundle(requirement_keys):
        if not isinstance(requirement_keys, list) or not 1 <= len(requirement_keys) <= 3 or not set(requirement_keys) <= set(roots):
            raise ValueError('Choose one to three requirement keys from the current group')
        pending, records = list(requirement_keys), {}
        while pending:
            key = pending.pop(0)
            if key in records:
                continue
            if len(records) >= 30:
                raise ValueError('Evidence bundle record budget exceeded')
            record = tools.get_record(key)
            records[key] = record
            pending.extend(link['key'] for link in record['links'])
        if len(json.dumps(records)) > 180000:
            raise ValueError('Evidence bundle context budget exceeded')
        return {'records': list(records.values())}

    def submit(decisions):
        if not isinstance(decisions, list) or len(decisions) != len(roots) or {x.get('requirement_key') for x in decisions} != set(roots):
            raise ValueError('Submit exactly one decision for every requirement key in the group')
        for decision in decisions:
            tools.validate_decision(decision, decision['requirement_key'])
        return {'accepted': True, 'decisions': decisions}

    contents = [{'role': 'user', 'parts': [{'text': json.dumps({'target': target, 'manifest': manifest,
        'requirements': [{'key': key, 'source_id': source_id(x), 'summary': x['fields']['summary']} for key, x in roots.items()],
        'instruction': 'Choose get_evidence_bundle for this small group, investigate the returned evidence, then submit_decisions for every requirement. Prefer one bundled read and one batch submission; use other tools when further investigation is necessary.'})}]}]
    group_id = ','.join(source_id(x) for x in issues)
    system += '\nYou are assessing a small group of at most three requirements with isolated group context. Select get_evidence_bundle to inspect all comments and recursive links for your chosen requirement roots. Use submit_decisions (plural) to submit all decisions together. Keep each rationale concise but address applicability, misleading evidence and outstanding work.'
    accepted, errors, tool_count = None, [], 0
    try:
        for turn in range(max_turns):
            if time.monotonic() >= deadline or len(json.dumps(contents)) > 240000:
                raise RuntimeError('Investigation time or context budget exhausted')
            metrics['model_calls'] += 1
            response, usage = model.invoke(system, contents, declarations)
            for key, value in usage.items():
                if isinstance(value, (int, float)):
                    metrics['usage'][key] = metrics['usage'].get(key, 0) + value
            trace('model', requirement_id=group_id, turn=turn, response=response, usage=usage)
            contents.append(response)
            responses = []
            for part in response.get('parts', []):
                if 'functionCall' not in part:
                    continue
                action = part['functionCall']
                name, args = action.get('name'), action.get('args', {})
                tool_count += 1
                if tool_count > max_tools:
                    raise RuntimeError('Investigation tool budget exhausted')
                try:
                    fn = {'get_evidence_bundle': bundle, 'get_record': tools.get_record,
                          'search_issues': tools.search_issues, 'submit_decisions': submit}.get(name)
                    if fn is None:
                        raise ValueError('Unknown tool: ' + str(name))
                    value = call(name, args, fn)
                    if name == 'submit_decisions':
                        accepted = value['decisions']
                except Exception as exc:
                    value = {'error': str(exc) or type(exc).__name__}
                    if name != 'submit_decisions':
                        errors.append(value['error'])
                response_item = {'name': name, 'response': value if isinstance(value, dict) else {'result': value}}
                if 'id' in action:
                    response_item['id'] = action['id']
                responses.append({'functionResponse': response_item})
            if accepted is not None:
                break
            if not responses:
                raise RuntimeError('Model selected no actions')
            contents.append({'role': 'user', 'parts': responses})
        if accepted is None:
            raise RuntimeError('Investigation turn budget exhausted')
    except Exception as exc:
        errors.append(str(exc) or type(exc).__name__)
        trace('model_error', requirement_id=group_id, error=errors[-1])
    decisions = []
    for root, issue in roots.items():
        if errors or accepted is None:
            decision = {'status': 'INSUFFICIENT_EVIDENCE', 'references': [],
                'rationale': 'Investigation could not be completed: ' + '; '.join(errors),
                'outstanding': 'Resolve the execution failures and rerun the investigation.'}
        else:
            decision = next(x for x in accepted if x['requirement_key'] == root)
        decision.update({'requirement_id': source_id(issue),
            'requirement_name': issue['fields']['summary'].split('] ', 1)[-1], 'jira_key': root})
        decisions.append(decision)
        trace('decision', **decision)
    return decisions, [group_id + ': ' + x for x in errors]
