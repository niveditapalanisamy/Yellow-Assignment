# Deploy Yellow Assignment to Render

The root `render.yaml` defines a free Python web service. Source repository:
`https://github.com/niveditapalanisamy/Yellow-Assignment`.

## Deployment

1. Push the tested source, `render.yaml` and existing `submission/` artifacts to the repository. Do not push `.env`, local browser profiles, virtual environments or credentials.
2. In Render, choose **New > Blueprint**, connect the GitHub repository, and use its `render.yaml`.
3. Enter the secret environment values requested by the Blueprint: `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`, and `GEMINI_API_KEY`. Use the dedicated project and dataset scope already configured. The importer does not need to run again for the records already in Jira.
4. Deploy. The build runs the standard-library tests, then starts `python app.py`. Render supplies `PORT` and `RENDER_EXTERNAL_URL`; the application binds `0.0.0.0` and trusts only the configured external origin and local addresses.
5. Open the service's HTTPS URL. The dashboard, reports, Jira import and live Jira/Gemini assessments are accessible without a username or password.

All application routes are public, as requested by the owner. Jira and model credentials stay in Render environment secrets and are never returned to the browser. Requests must still use the configured host and browser origin, and one operation runs at a time. `/api/health` returns only `{"status":"ok"}` for Render health checks. For custom domains, set `PUBLIC_BASE_URL` to the exact HTTPS origin and redeploy. `APP_USERNAME` and `APP_PASSWORD` are no longer used and can be removed from existing services.

The original report and trace are served directly from the committed `submission/` artifacts if runtime storage has no newer run. Deployment never invents or adds release evidence. Fresh investigations still retrieve evidence only through Jira tools.

## Storage and plan

The Blueprint uses the free plan. Render's free filesystem is ephemeral, so newly generated reports can disappear on restart/redeploy; download them after a run. The submitted report survives because it is part of the source repository. Free services also sleep when idle, which can interrupt a background task if no browser remains connected. Keep the dashboard open while an investigation runs. For long-term runtime report storage, choose a paid persistent disk separately and set `REPORT_DIR` to its mount path; this Blueprint creates no paid resources.

This is a single-process assessment/demo service. Background tasks are not a durable job queue, and there is one active operation at a time. Service restarts do not change the imported Jira evidence. Model availability and account quotas still apply to fresh assessments.

## Verification after deployment

- `/api/health` responds 200 without login.
- `/` and `/api/report/json` respond without a login or authentication challenge.
- The dashboard loads the actual completed report: 12 requirements, overall BLOCKED.
- Downloads return the existing Markdown, JSON and tool trace.
- A new assessment can be started after verifying your Jira/model credentials and quota.

Hosting references: [Render web services and port binding](https://render.com/docs/web-services#port-binding), [Blueprint configuration](https://render.com/docs/blueprint-spec), [secret environment variables](https://render.com/docs/configure-environment-variables), and [free-service storage limits](https://render.com/docs/free).
