# edu-session-owner plugin

Session ownership stamping + list isolation for the dsh student workbench
(edu-agent track 3, docs/PLAN-dsh-workbench.md §3.2). Stacks on top of
`edu-auth` — it does not modify it and assumes the bearer token fence already
ran (load both patches).

## Files

- `src/index.ts` — the plugin (function plugin: `name` / `inject` / `apply`)
- `cordis.yml` — `--patch` overlay mounting this plugin (pair it with
  `../edu-auth/cordis.yml`)

## What it does

1. **token → user_id (placeholder)**: the bearer token itself is the user_id
   (e.g. `Bearer student-a` → `student-a`). Real JWT parsing against the
   edu-agent backend is future work (same placeholder stance as edu-auth).
2. **Owner stamping on `session.create`**: after the real handler succeeds,
   the returned `sessionId` is recorded in an owner registry — in-memory for
   the boot, plus a JSON sidecar at `$DSH_HOME/edu-session-owners.json` so
   ownership survives host restarts.
3. **List filtering on `session.list` / `session.search`**: the response's
   `value.items` is filtered to sessions whose owner equals the calling
   token's user_id. Sessions with no recorded owner (pre-plugin legacy
   sessions) are hidden from everyone — fail-closed.

## Mechanism (wire-level, verified live)

The RPC carrier wire format (from
`packages/client/connection/src/rpc-host.ts` and
`packages/host/apiproxy/src/fetch/handler.ts`):

```
POST /api/<method>            content-type: application/json
body:   {"type":"client-request","rpcId":"...","method":"<method>","payload":{...}}
reply:  {"type":"server-response","rpcId":"...","result":{"ok":true,"value":{...}}}
```

The plugin wraps the same seam edu-auth uses — the `/api` **prefix WebRoute
handler** registered by client-connection (and monkey-patches
`webServer.register` for later registrations). Wrapping order when both
patches are loaded: `edu-session-owner(outer) → edu-auth(401 fence) →
trust fence → RPC carrier`, so a tokenless request still 401s before any
owner logic runs.

For intercepted methods the wrapper buffers the request body (the stock
bridge buffers it anyway), replays it into the wrapped handler against a fake
response object, then rewrites the JSON envelope before writing the real
response:

- `session.create` → read `value.sessionId` from the (ok) response, stamp
  `owner` in the registry.
- `session.list` / `session.search` → filter `value.items` by
  `registry.get(sessionId) === owner`.

Everything else (prompt, history, SSE streams, workspaces, …) passes through
untouched. No dsh core files are modified.

## Known limitation: no session metadata channel

`SessionSummary` and the `session.create` request payload have **no metadata
field** (checked `packages/host/apiproxy/src/api/sessions.ts`); titles are
LLM/user-generated and would be overwritten, so the task's title-prefix
fallback (`[owner:student-a]`) was rejected in favor of a sidecar registry at
`$DSH_HOME/edu-session-owners.json`. Consequences:

- The owner map is host-local state, not part of the durable session log — a
  host that loses the sidecar loses the mapping (fail-closed: everything
  hidden until re-stamped).
- Enforcing per-session reads (`session.history`, `session.prompt`, …) by
  owner is not done yet (see Remaining work).

## Verified live (dsh web, port 3084, curl)

Two identities, one session each:

| Step | Result |
|---|---|
| `POST /api/session.create` as `student-a` | 200, `sessionId` A stamped owner=student-a |
| `POST /api/session.create` as `student-b` | 200, `sessionId` B stamped owner=student-b |
| `POST /api/session.list` as `student-a` | items = [A] only |
| `POST /api/session.list` as `student-b` | items = [B] only |
| `POST /api/session.list` no token | 401 (edu-auth fence still first) |
| sidecar `$DSH_HOME/edu-session-owners.json` | both ids with correct owners |

## Run it

```sh
cd ~/workspace/deepseek-harness
DSH_HOME=<dsh-home> /Users/guanchunyuan/.nvm/versions/node/v24.12.0/bin/node \
  --import tsx/esm apps/cli/src/bin.ts --profile web \
  --patch ~/workspace/edu-agent/dsh-workbench/plugins/edu-auth/cordis.yml \
  --patch ~/workspace/edu-agent/dsh-workbench/plugins/edu-session-owner/cordis.yml \
  --port 3084
```

Example curl (create as student-a, then list):

```sh
curl -s -X POST localhost:3084/api/session.create \
  -H 'authorization: Bearer student-a' -H 'content-type: application/json' \
  -d '{"type":"client-request","rpcId":"r1","method":"session.create","payload":{}}'

curl -s -X POST localhost:3084/api/session.list \
  -H 'authorization: Bearer student-a' -H 'content-type: application/json' \
  -d '{"type":"client-request","rpcId":"r2","method":"session.list","payload":{}}'
```

## Remaining work

- Real JWT verification + `user_id` extraction (replace token==user_id)
- Enforce owner on per-session reads/writes (`session.history`,
  `session.prompt`, `session.rename`, `session.fork`, …) — currently only
  list/search are filtered, so a student who learns another's sessionId can
  still address it directly
- WebSocket/SSE event streams are not owner-scoped
- Migrate the sidecar into a proper per-user session store once dsh grows a
  metadata channel
