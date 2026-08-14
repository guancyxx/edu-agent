# edu-tools plugin

First batch of teaching tools for the dsh student workbench
(edu-agent, docs/PLAN-dsh-workbench.md §3.3). Three model-facing tools
registered via `defineTool` (`ctx.tools.register`), same shape as the
scratch-plugin `greet` tool from the T1 spike.

## Files

- `src/index.ts` — the plugin (function plugin: `name` / `inject` / `apply`)
- `cordis.yml` — `--patch` overlay mounting the plugin into a dsh profile

## Tools and backend contracts

### 1. `query_mistakes` — the mistake notebook

Calls the existing edu-agent FastAPI route:

```
GET {EDU_BASE_URL}/api/mistakes?subject=<subject>
Authorization: Bearer <EDU_TOKEN>
```

- Params: `subject` (optional string), `limit` (optional number, default 20,
  clamped to 1–50; applied client-side since the backend route has no limit
  query param).
- 200 → `[{id, subject, question, student_answer, correct_answer, explanation,
  knowledge_point_id, review_count, ease_factor, interval_days,
  next_review_at, last_reviewed_at, status, created_at}, ...]`
  The tool returns `{count, mistakes: [...]}` sliced to `limit`.
- 401 → `{ok:false, status:401, body:{detail:"Not authenticated"|...}}`

### 2. `get_curriculum` — the curriculum knowledge tree

**Fallback mode (current):** the backend exposes no curriculum HTTP route
(`app/routers/` only has auth / mistakes / chat / health), so the tool reads
the backend's own curriculum YAML files directly from
`backend/app/curriculum/data/*.yaml` (checked at plugin startup; an optional
`src/data/` override directory inside the plugin is searched first). A tiny
built-in YAML subset parser handles the files' nested maps/lists, quoted
strings, and inline flow sequences — no runtime dependency added.

- Params: `grade` (optional number, e.g. 7), `subject` (optional string).
- Returns `{ok:true, source:"local-yaml-fallback", curricula:[{file, subject,
  grade, title, chapters:[{id, title, knowledge_points:[{id, title,
  difficulty}]}]}]}`.
- **Future swap:** when the backend gains `GET /api/curriculum?grade=&subject=`
  (Bearer auth), replace the body of this tool's `execute` with a
  `callBackend('GET', ...)` — the transport helper already exists.

### 3. `submit_answer` — submit a student's answer

**Contract (designed; no dedicated backend route exists yet):** the tool POSTs
to the existing mistake-creation route, which is semantically "record this
answered question into the mistake notebook + SM-2 scheduler":

```
POST {EDU_BASE_URL}/api/mistakes
Authorization: Bearer <EDU_TOKEN>
Content-Type: application/json

{
  "subject": "math",
  "question": "…",
  "student_answer": "…",
  "correct_answer": "…" | null,
  "explanation": "…" | null,
  "knowledge_point_id": "7-1-3" | null,
  "source": "dsh-workbench"
}
```

- 201 → the created `MistakeOut` record (id, SM-2 fields, status…).
- A dedicated `POST /api/answers` route (grading + feedback payload with
  `is_correct`) is the planned evolution; when it lands, only this tool's
  `execute` body changes — the model-facing schema stays.

## Auth

Every HTTP call sends `Authorization: Bearer $EDU_TOKEN`. The token comes from
the `EDU_TOKEN` environment variable — **placeholder plumbing**: host-side
injection (edu-auth plugin obtaining the JWT at login and injecting it into
tool execution context per §3.3 of the plan) is follow-up work. Until then,
export `EDU_TOKEN` (and optionally `EDU_BASE_URL`, default
`http://127.0.0.1:8000`) before starting the dsh instance:

```sh
export EDU_BASE_URL=http://127.0.0.1:8000
export EDU_TOKEN=$(curl -s -X POST $EDU_BASE_URL/api/auth/login \
  -H 'content-type: application/json' \
  -d '{"username":"…","password":"…"}' | jq -r .access_token)
```

## Degraded mode

If the backend is down (connection refused / >4s timeout), HTTP tools return a
fixed JSON body tagged `"backend_unavailable": true` with the transport error
detail, so the model-facing call chain still works end to end. `get_curriculum`
is unaffected (local files).

## Run it

```sh
cd ~/workspace/deepseek-harness
node --import tsx/esm apps/cli/src/bin.ts \
  --profile web --patch ~/workspace/edu-agent/dsh-workbench/plugins/edu-tools/cordis.yml \
  --port 3085
```

Note: plugin resolution needs `@deepseek-ai/dsh-tools` reachable via the
loader's package graph — the `web` profile resolves it through the harness
workspace; if a raw launch fails with "Cannot find module", run from the
harness repo root (same as the scratch-plugin spike).

## Verified live (port 3085, DeepSeek live model)

| Tool | Backend state | Model call | Result |
|---|---|---|---|
| `query_mistakes` | up, real JWT | "Use the query_mistakes tool…" | real entries JSON |
| `get_curriculum` | n/a (local) | "Use the get_curriculum tool…" | real grade-7/8 tree JSON |
| `submit_answer` | up, real JWT | "Use the submit_answer tool…" | 201 + created record |

(See the T4 report in the worktree commit for exact transcripts.)
