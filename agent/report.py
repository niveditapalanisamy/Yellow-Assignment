import json
from .decision import overall_release_status


def render_report(result, base_url):
    esc = lambda s: str(s).replace('|', '\\|').replace('\n', ' ')
    status = overall_release_status(d['status'] for d in result['requirements']).value
    result['overall_decision'] = status
    lines = ['# Jira release-readiness report', '', f"Execution: **{result['execution_status']}**  ",
        f'Overall decision: **{status}**', '', f"Run: `{result['run_id']}`  ",
        f"Started (UTC): {result['started_at']}  ",
        f"Project: `{result['project']}` · Dataset: `{result['dataset_label']}`", '',
        'Target: `' + json.dumps(result.get('target', {}), sort_keys=True) + '`', '',
        '| Requirement | Decision | Explanation | Outstanding verification / clarification |',
        '|---|---|---|---|']
    for d in result['requirements']:
        lines.append(f"| {esc(d['requirement_id'])}: {esc(d['requirement_name'])} | {d['status']} | {esc(d['rationale'])} | {esc(d['outstanding'])} |")
    lines += ['', '## Evidence', '']
    for d in result['requirements']:
        lines += [f"### {d['requirement_id']}", '']
        for ref in d['references']:
            url = f"{base_url}/browse/{ref['issue_key']}?focusedCommentId={ref['comment_id']}"
            lines += [f"- [{ref['issue_key']} comment {ref['comment_id']}]({url}): {ref['why']}",
                      '  > ' + ref['quote'].replace('\n', '\n  > ')]
    metrics = result['metrics']
    lines += ['', '## Execution and limits', '',
        f"Elapsed: {metrics['elapsed_seconds']:.3f}s; model: `{metrics['model']}`; model calls: {metrics['model_calls']}; tool calls: {metrics['tool_calls']}.",
        'Provider token usage: `' + json.dumps(metrics['usage'], sort_keys=True) + '`.',
        'Requirements are investigated in isolated groups of at most three. Jira text is untrusted evidence. Native Jira actors/times are import metadata. '
        'Decisions are model judgments; citation and investigation coverage checks do not prove semantic correctness.',
        'The trace contains exact tool arguments/results and model actions. No external evidence was used.']
    if result['errors']:
        lines += ['', 'Errors / unresolved execution limits:', ''] + ['- ' + x for x in result['errors']]
    if not result['requirements']:
        lines += ['', '**No requirement assessment was completed. This is a failed-run artifact, not a release approval.**']
    return '\n'.join(lines) + '\n'
