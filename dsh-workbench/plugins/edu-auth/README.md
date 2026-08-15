# edu-auth plugin

Experimental login gate + `/api` token fence for the dsh student workbench
(edu-agent track 2, docs/PLAN-dsh-workbench.md §3.1).

## Files

- `src/index.ts` — the plugin (function plugin: `name` / `inject` / `apply`)
- `cordis.yml` — `--patch` overlay mounting the plugin into a dsh profile

## Function A — login page at /workbench

`ctx.webServer.register({ kind: 'exact', path: '/workbench' })` serves a minimal
English HTML login form. Public (no token required) by design — it is the entry
point that will later obtain the JWT.

## Function B — /api token fence

**Mechanism (research findings, verified):**

- The Typert `/api` interceptor seat (`connection.rpc.intercept('/api', ...)`)
  is single-holder and already taken by `typert-gateway` in the default web
  composition; a second registration throws.
- `rpcFetchHandler` (packages/client/connection/src/rpc-host.ts) only returns
  200/400/404/415/500 — there is no 401 path from inside the interceptor.
- Equivalent seam chosen: the `/api` **prefix WebRoute** registered by
  client-connection (packages/client/connection/src/index.ts) whose handler runs
  the browser-trust fence + HTTP bridge. This plugin wraps that route handler
  (and monkey-patches `webServer.register` to also wrap any later `/api` prefix
  registration) with an Authorization check that answers **401 Unauthorized**
  before the fence/bridge run.

**Placeholder validation:** any non-empty `Authorization: Bearer <token>`
passes. Real JWT verification against the edu-agent backend is future work.

## Verified live (dsh web, port 3082, curl -i)

| Request | Result |
|---|---|
| GET /workbench | 200, login page HTML |
| POST /api/session/list, no token | **401** + `www-authenticate: Bearer` |
| POST /api/session/list, `Bearer test-token-123` | 404 (fence passed; carrier's normal response for an unknown endpoint) |
| GET /api/events.mux, no token | 401 |
| GET /api/events.mux, with token | 426 upgrade required (passed fence, reached dsh's own handler) |
| POST /api/..., `Authorization: Basic abc` | 401 (only Bearer accepted) |

## Run it

```sh
cd ~/workspace/deepseek-harness
DSH_HOME=<dsh-home> node --import tsx/esm apps/cli/src/bin.ts \
  --profile web --patch ~/workspace/edu-agent/dsh-workbench/plugins/edu-auth/cordis.yml \
  --port 3082
```

Notes: `--patch` must precede the app flags (`dsh web --patch ...` fails:
the web app rejects parent flags). Built `lib/` under plain Node cannot import
`.ts` plugins — use the source launcher (`node --import tsx/esm apps/cli/src/bin.ts`)
on Node >= 24 (Node 22 hits `ERR_REQUIRE_CYCLE_MODULE` importing the .ts entry).

## Remaining work

- ~~Real JWT verification~~ — DONE (T8): HS256 + expiry via `src/jwt.ts`
  (`node:crypto`, no deps); secret from `EDU_JWT_SECRET` (same default
  fallback as the backend). Live-verified: no/tampered/expired/garbage
  tokens all answer 401.
- Login page actually obtains/stores the token host-side (bind to
  connection/session) — plan §8 T11
- WebSocket upgrade routes (/api/events.*) are not token-fenced yet —
  plan §8 T10
