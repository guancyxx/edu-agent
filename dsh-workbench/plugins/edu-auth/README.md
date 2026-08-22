# edu-auth plugin

Login gate + `/api` token fence + WebSocket upgrade fence for the dsh student
workbench (edu-agent track 2, docs/PLAN-dsh-workbench.md).

## Files

- `src/index.ts` — the plugin (function plugin: `name` / `inject` / `apply`)
- `src/jwt.ts` — dependency-free HS256 JWT verification (node:crypto)
- `cordis.yml` — `--patch` overlay mounting the plugin into a dsh profile
  (path points at the worktree copy; adjust when running from elsewhere)

## Function A + D — login page and real login at /workbench

- `GET /workbench` serves an English HTML sign-in form (public by design).
- `POST /workbench` with `application/x-www-form-urlencoded`
  `username`/`password` is forwarded to the edu-agent backend
  `{EDU_BASE_URL}/api/auth/login` (default `http://127.0.0.1:8000`; same env
  var as edu-tools). Success renders the real JWT **and** sets it as an
  `HttpOnly; SameSite=Lax` cookie `edu_token` (`Max-Age=86400`). Wrong
  credentials → 401; backend unreachable → 502; missing fields → 400.

### Cookie plan and its limits

- Same-origin browser requests automatically carry `edu_token` afterwards.
  **However**, the `/api` token fence (Function B) and the WS upgrade fence
  (Function C) currently read only `Authorization` / `?token=` — they do NOT
  read the cookie. The fence would need a cookie-parsing branch before the
  cookie alone grants access; until then the token shown on the success page
  must be copied into the dsh frontend's fetch headers manually.
- The dsh web frontend calls `/api` with `fetch`. Cookies are sent on
  same-origin fetch by default (`credentials: 'same-origin'`), so the cookie
  would ride along — but again only matters once the fence accepts cookies.
- `SameSite=Lax` suits same-origin use; a cross-origin frontend would need
  `SameSite=None; Secure` plus a proper origin allowlist (not done here).
- The token is displayed in the page body for the workbench demo flow — a
  real deployment must not echo credentials/tokens to generic pages.

## Function B — /api HTTP token fence (T8)

The Typert `/api` interceptor seat is single-holder (taken by
typert-gateway) and `rpcFetchHandler` has no 401 path, so the fence wraps
the `/api` **prefix WebRoute** handler registered by client-connection
(plus a `webServer.register` monkey-patch for later registrations). Every
`/api` request needs a valid HS256 bearer JWT (`EDU_JWT_SECRET`, same secret
the backend signs with) or gets **401** + `www-authenticate: Bearer`.

## Function C — WebSocket upgrade fence (T10)

`/api/events.mux` and `/api/events.host` upgrades are rejected with a raw
`HTTP/1.1 401` before protocol negotiation unless the handshake carries a
valid JWT. **Browsers cannot set custom headers on a WS handshake**, so the
token is accepted from:

1. `Authorization: Bearer <jwt>` (non-browser clients), or
2. a `?token=<jwt>` query parameter — **the browser front end must be
   changed to append this to its WS URL**; that frontend change is future
   work and not in this repo.

Mechanism: client-connection registers both routes via
`webServer.registerUpgrade` (exact path; duplicates throw), so the plugin
patches `registerUpgrade` to fence handlers at registration time (same
strategy as the HTTP fence) and also wraps already-registered entries in
the live `upgrades` Map; teardown restores originals.

## Verified live (dsh web @3088, real backend JWT via /api/auth/register)

| Request | Result |
|---|---|
| GET /workbench | 200, login form HTML |
| POST /workbench, correct credentials | **200 + real JWT + `set-cookie: edu_token=...`** |
| POST /workbench, wrong credentials | **401** |
| POST /workbench, missing fields | 400 |
| POST /api/session/list, no token | 401 + `www-authenticate: Bearer` |
| POST /api/session/list, valid Bearer | 415 (fence passed; carrier's normal response) |
| WS upgrade /api/events.mux, no token | **401 Unauthorized** (raw socket) |
| WS upgrade /api/events.mux / events.host, `?token=garbage` | **401** |
| WS upgrade, valid `Authorization: Bearer` header | **101 Switching Protocols** |
| WS upgrade, valid `?token=<jwt>` query (mux + host) | **101 Switching Protocols** |

## Run it

```sh
cd ~/workspace/deepseek-harness
DSH_HOME=<dsh-home> node --import tsx/esm apps/cli/src/bin.ts \
  --profile web --patch /tmp/edu-agent-t10/dsh-workbench/plugins/edu-auth/cordis.yml \
  --port 3088
```

Env: `EDU_JWT_SECRET` (backend signing secret; default
`change-me-in-production`), `EDU_BASE_URL` (backend origin, default
`http://127.0.0.1:8000`).

Notes: `--patch` must precede the app flags. Built `lib/` under plain Node
cannot import `.ts` plugins — use the source launcher
(`node --import tsx/esm apps/cli/src/bin.ts`) on Node >= 24.
