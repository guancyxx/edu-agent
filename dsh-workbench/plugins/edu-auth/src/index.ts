/**
 * edu-auth — login gate + /api token fence + WebSocket upgrade fence for the
 * dsh student workbench (edu-agent track 2).
 *
 * Function A: serves an English login page at GET /workbench.
 * Function B: rejects every /api HTTP request that carries no bearer token.
 * Function C (T10): rejects the /api/events.mux and /api/events.host
 *   WebSocket upgrades when the handshake carries no valid JWT.
 * Function D (T11): POST /workbench with username/password form data is
 *   forwarded to the edu-agent backend {EDU_BASE_URL}/api/auth/login; on
 *   success the token is set as an HttpOnly cookie.
 * Function E (T12): seamless browser auth —
 *   - the login success page stores the JWT in localStorage('edu_token')
 *     and redirects to '/' (the workbench index);
 *   - webServer.tapIndex() injects an inline script into every index.html
 *     that patches window.fetch (add Authorization: Bearer) and
 *     window.WebSocket (append ?token=) for same-origin requests, and
 *     bounces to /workbench on a 401 (expired token);
 *   - both fences additionally accept `Cookie: edu_token=<jwt>` when no
 *     Authorization header is present (double coverage with localStorage).
 *
 * Mechanism notes:
 * - HTTP fence: the `/api` prefix WebRoute registered by client-connection is
 *   wrapped (see T8 commit history) — the Typert interceptor seat is
 *   single-holder and taken by typert-gateway.
 * - Upgrade fence (T10): client-connection registers the two upgrade routes
 *   via `webServer.registerUpgrade` (exact path, duplicate paths throw), so
 *   this plugin monkey-patches `registerUpgrade` itself, exactly like the
 *   `register` patch for the HTTP fence. Whichever order the plugins load,
 *   the handler is wrapped at registration time. Browsers cannot set custom
 *   headers on a WebSocket handshake, so the token is accepted from the
 *   `Authorization` header OR a `?token=` query parameter.
 * - Login (T11): browser native form POST (application/x-www-form-urlencoded)
 *   to the page's own path; the plugin parses the body, calls the backend
 *   login endpoint via fetch, and renders the result.
 */

import type { IncomingMessage } from 'node:http'
import type { Duplex } from 'node:stream'

import type { Context } from '@deepseek-ai/cordis'

import { bearerClaims, verifyJwt } from './jwt.ts'

export const name = 'edu-auth'
export const inject = ['webServer']

const API_PREFIX = '/api'
const WORKBENCH_PATH = '/workbench'
const WS_EVENTS_PATHS = new Set(['/api/events.mux', '/api/events.host'])
const BASE_URL = (process.env.EDU_BASE_URL ?? 'http://127.0.0.1:8000').replace(/\/+$/, '')
const LOGIN_TIMEOUT_MS = 10_000

/** Verify the bearer JWT (HS256 signature + expiry) against EDU_JWT_SECRET. */
function validAuth(req: { headers: { authorization?: string | string[] } }): boolean {
  const secret = process.env['EDU_JWT_SECRET'] ?? 'change-me-in-production'
  if (bearerClaims(req.headers.authorization, secret) !== undefined) return true
  return cookieToken(req) !== undefined && verifyJwt(cookieToken(req) as string, secret) !== undefined
}

/**
 * Cookie: edu_token=<jwt> fallback (T12) — the login flow already drops an
 * HttpOnly edu_token cookie; accept it when no Authorization header exists.
 */
function cookieToken(req: { headers: Record<string, unknown> }): string | undefined {
  const raw = req.headers['cookie']
  if (typeof raw !== 'string') return undefined
  for (const part of raw.split(';')) {
    const eq = part.indexOf('=')
    if (eq === -1) continue
    if (part.slice(0, eq).trim() === 'edu_token') return part.slice(eq + 1).trim()
  }
  return undefined
}

/** Token for a WS upgrade: Authorization header, ?token= query, or cookie. */
function upgradeToken(req: IncomingMessage): 'header' | 'query' | 'cookie' | undefined {
  const secret = process.env['EDU_JWT_SECRET'] ?? 'change-me-in-production'
  if (bearerClaims(req.headers.authorization, secret) !== undefined) return 'header'
  const url = new URL(req.url ?? '/', 'http://x')
  const token = url.searchParams.get('token')
  if (token !== null && verifyJwt(token, secret) !== undefined) return 'query'
  const cookie = cookieToken(req)
  if (cookie !== undefined && verifyJwt(cookie, secret) !== undefined) return 'cookie'
  return undefined
}

/** Raw-socket 401 — mirrors client-connection's rejectWebSocketUpgrade (403). */
function rejectUpgradeUnauthorized(socket: Duplex): void {
  socket.end([
    'HTTP/1.1 401 Unauthorized',
    'Connection: close',
    'WWW-Authenticate: Bearer',
    'Content-Type: text/plain; charset=utf-8',
    'Content-Length: 27',
    '',
    'unauthorized: token required',
  ].join('\r\n'))
}

/** Read a urlencoded request body (bounded, login form only). */
function readBody(req: IncomingMessage): Promise<string> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = []
    let size = 0
    req.on('data', (chunk: Buffer) => {
      size += chunk.length
      if (size > 64 * 1024) { reject(new Error('body too large')); req.destroy(); return }
      chunks.push(chunk)
    })
    req.on('end', () => { resolve(Buffer.concat(chunks).toString('utf8')) })
    req.on('error', reject)
  })
}

function page(body: string): string {
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Edu Workbench — Sign in</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body { font-family: system-ui, sans-serif; display: grid; place-items: center; min-height: 100vh; margin: 0; background: #f5f6fa; }
  form { background: #fff; padding: 2rem; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,.08); display: grid; gap: .75rem; width: 18rem; }
  h1 { font-size: 1.1rem; margin: 0 0 .5rem; }
  label { font-size: .85rem; color: #333; }
  input { padding: .5rem; border: 1px solid #ccc; border-radius: 4px; }
  button { padding: .6rem; border: 0; border-radius: 4px; background: #2563eb; color: #fff; cursor: pointer; }
  .token { word-break: break-all; font-family: ui-monospace, monospace; font-size: .75rem; background: #f0fdf4; padding: .6rem; border-radius: 4px; border: 1px solid #bbf7d0; }
  .error { color: #b91c1c; font-size: .85rem; }
</style>
</head>
<body>
${body}
</body>
</html>
`
}

const LOGIN_FORM = page(`<form method="post" action="/workbench">
  <h1>Edu Workbench</h1>
  <label for="username">Username</label>
  <input id="username" name="username" autocomplete="username" required>
  <label for="password">Password</label>
  <input id="password" name="password" type="password" autocomplete="current-password" required>
  <button type="submit">Sign in</button>
</form>
`)

interface BackendAuthResponse { access_token?: string, user?: { username?: string } }

/**
 * T12 inline script injected into every index.html via webServer.tapIndex().
 * Small (<60 lines), zero dependencies, ES2020. Behaviour:
 * - window.fetch patch: same-origin + localStorage token + no Authorization
 *   header already set → add `Authorization: Bearer <token>`; a 401 clears
 *   the token and bounces to /workbench.
 * - window.WebSocket patch: /api/events.* URLs get `?token=<jwt>` appended.
 * The HttpOnly edu_token cookie rides along as server-side double coverage.
 */
const AUTH_SHIM = `<script>
(function () {
  'use strict'
  function token() {
    try { return localStorage.getItem('edu_token') || '' } catch (e) { return '' }
  }
  function bounceToLogin() {
    try { localStorage.removeItem('edu_token') } catch (e) {}
    if (location.pathname !== '/workbench') location.replace('/workbench')
  }
  var rawFetch = window.fetch
  if (typeof rawFetch === 'function') {
    window.fetch = function (input, init) {
      init = init || {}
      var url = typeof input === 'string' ? input : (input && input.url) || ''
      var sameOrigin = url.indexOf('/') === 0
        || new URL(url, location.origin).origin === location.origin
      var t = token()
      var hasAuth = (init.headers && init.headers.Authorization) || false
      if (sameOrigin && t && !hasAuth && url.indexOf('/api/') !== -1) {
        var h = new Headers(init.headers || {})
        h.set('Authorization', 'Bearer ' + t)
        init.headers = h
      }
      return rawFetch.call(window, input, init).then(function (res) {
        if (res && res.status === 401 && sameOrigin) bounceToLogin()
        return res
      })
    }
  }
  var RawWS = window.WebSocket
  if (typeof RawWS === 'function') {
    window.WebSocket = function (url, protocols) {
      var t = token()
      if (t && typeof url === 'string' && url.indexOf('/api/events.') !== -1) {
        url += (url.indexOf('?') === -1 ? '?' : '&') + 'token=' + encodeURIComponent(t)
      }
      return protocols === undefined ? new RawWS(url) : new RawWS(url, protocols)
    }
    window.WebSocket.prototype = RawWS.prototype
    window.WebSocket.OPEN = RawWS.OPEN
    window.WebSocket.CONNECTING = RawWS.CONNECTING
    window.WebSocket.CLOSING = RawWS.CLOSING
    window.WebSocket.CLOSED = RawWS.CLOSED
  }
})()
</script>`

/** Forward credentials to {EDU_BASE_URL}/api/auth/login; token or error. */
async function backendLogin(
  username: string,
  password: string,
): Promise<{ ok: true, token: string, username: string } | { ok: false, status: number }> {
  const controller = new AbortController()
  const timer = setTimeout(() => { controller.abort() }, LOGIN_TIMEOUT_MS)
  try {
    const res = await fetch(`${BASE_URL}/api/auth/login`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ username, password }),
      signal: controller.signal,
    })
    if (!res.ok) return { ok: false, status: res.status }
    const data = (await res.json()) as BackendAuthResponse
    if (typeof data.access_token !== 'string' || data.access_token.length === 0) {
      return { ok: false, status: 502 }
    }
    return { ok: true, token: data.access_token, username: data.user?.username ?? username }
  } catch {
    return { ok: false, status: 502 }
  } finally {
    clearTimeout(timer)
  }
}

export function apply(ctx: Context): void {
  ctx.inject(['webServer'], (webCtx) => {
    const webServer = webCtx.webServer as unknown as {
      register: (route: { kind: string; path: string; handler: unknown }) => () => void
      registerUpgrade: (route: { path: string; handler: unknown }) => () => void
      prefixes: Map<string, { kind: string; path: string; handler: unknown }>
    }

    const restore: Array<() => void> = []

    // ── Function E (T12): inject the auth shim into every index.html ──
    // tapIndex transforms are applied by the fallback owner to every index
    // response — the official no-touch injection channel for browser scripts.
    const webServerFull = webServer as unknown as {
      tapIndex?: (transform: (html: string) => string) => () => void
    }
    if (typeof webServerFull.tapIndex === 'function') {
      const untap = webServerFull.tapIndex((html: string) =>
        html.includes('</head>')
          ? html.replace('</head>', `${AUTH_SHIM}</head>`)
          : AUTH_SHIM + html)
      restore.push(untap)
    }

    // ── Function A + D: login page and form-POST login at /workbench ──
    restore.push(webCtx.effect(() => webServer.register({
      kind: 'exact',
      path: WORKBENCH_PATH,
      handler: async (req: IncomingMessage, res: {
        writeHead: (status: number, headers?: Record<string, string>) => void
        end: (body?: string) => void
      }) => {
        if (req.method === 'GET') {
          res.writeHead(200, { 'content-type': 'text/html; charset=utf-8' })
          res.end(LOGIN_FORM)
          return
        }
        if (req.method !== 'POST') {
          res.writeHead(405, { allow: 'GET, POST' })
          res.end('method not allowed')
          return
        }
        // T11: real login against the edu-agent backend.
        const params = new URLSearchParams(await readBody(req))
        const username = params.get('username') ?? ''
        const password = params.get('password') ?? ''
        if (username.length === 0 || password.length === 0) {
          res.writeHead(400, { 'content-type': 'text/html; charset=utf-8' })
          res.end(page(`<form method="post" action="/workbench">
  <h1>Edu Workbench</h1>
  <p class="error">Username and password are required.</p>
  <label for="username">Username</label>
  <input id="username" name="username" required>
  <label for="password">Password</label>
  <input id="password" name="password" type="password" required>
  <button type="submit">Sign in</button>
</form>
`))
          return
        }
        const result = await backendLogin(username, password)
        if (!result.ok) {
          // 401 = bad credentials; anything else = upstream/backend failure.
          const status = result.status === 401 ? 401 : 502
          const reason = result.status === 401
            ? 'Invalid username or password.'
            : 'Login backend unavailable. Try again later.'
          res.writeHead(status, { 'content-type': 'text/html; charset=utf-8' })
          res.end(page(`<h1>Edu Workbench</h1><p class="error">${reason}</p>
<p><a href="/workbench">Back to sign in</a></p>`))
          return
        }
        // Success: store the token where the injected front-end script reads
        // it (localStorage), drop the HttpOnly cookie for the fence's cookie
        // branch, then land on the workbench index — the tapIndex-injected
        // patch makes every subsequent fetch/WS request carry the token.
        res.writeHead(200, {
          'content-type': 'text/html; charset=utf-8',
          'set-cookie': `edu_token=${result.token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=86400`,
        })
        res.end(page(`<h1>Signed in as ${result.username}</h1>
<p>Signing you in…</p>
<script>
  try { localStorage.setItem('edu_token', ${JSON.stringify(result.token)}) } catch (e) {}
  location.replace('/')
</script>
<noscript><p>JavaScript is disabled — copy this bearer token manually:</p>
<div class="token">${result.token}</div></noscript>
<p><a href="/workbench">Sign out</a></p>`))
      },
    }), 'edu-auth: /workbench login page'))

    // ── Function B: token fence over the /api prefix route (T8) ──
    const fenceHandler = (
      handler: (req: never, res: never) => void | Promise<void>,
    ): (req: { headers: { authorization?: string | string[] } }, res: {
      writeHead: (status: number, headers?: Record<string, string>) => void
      end: (body?: string) => void
    }) => void | Promise<void> => async (req, res) => {
      if (!validAuth(req)) {
        res.writeHead(401, { 'content-type': 'text/plain; charset=utf-8', 'www-authenticate': 'Bearer' })
        res.end('unauthorized: missing or invalid bearer token')
        return
      }
      return handler(req as never, res as never)
    }

    const existing = webServer.prefixes.get(API_PREFIX)
    if (existing !== undefined && typeof existing.handler === 'function') {
      const original = existing.handler as (req: never, res: never) => void | Promise<void>
      existing.handler = fenceHandler(original)
      restore.push(() => { existing.handler = original })
    }

    const originalRegister = webServer.register.bind(webServer)
    webServer.register = (route) => {
      if (route.kind === 'prefix' && route.path === API_PREFIX && typeof route.handler === 'function') {
        const original = route.handler as (req: never, res: never) => void | Promise<void>
        route.handler = fenceHandler(original)
      }
      return originalRegister(route)
    }
    restore.push(() => { webServer.register = originalRegister })

    // ── Function C (T10): token fence over the WS upgrade routes ──
    // client-connection registers /api/events.mux and /api/events.host via
    // webServer.registerUpgrade (exact path). Duplicate paths throw, so we
    // cannot re-register; instead patch registerUpgrade so the handler is
    // wrapped at registration time, and wrap any already-registered route.
    type UpgradeHandler = (req: IncomingMessage, socket: Duplex, head: Buffer) => void | Promise<void>
    const fenceUpgrade = (handler: UpgradeHandler): UpgradeHandler =>
      (req, socket, head) => {
        if (upgradeToken(req) === undefined) {
          rejectUpgradeUnauthorized(socket)
          return
        }
        return handler(req, socket, head)
      }

    // If client-connection registered the upgrade routes before this plugin
    // applied, wrap the live Map entries now (`upgrades` is TS-private only);
    // the registerUpgrade patch below covers the normal load order.
    const upgradesMap = (webServer as unknown as {
      upgrades?: Map<string, { handler: unknown }>
    }).upgrades
    const wrappedUpgrades: Array<{ entry: { handler: unknown }, original: UpgradeHandler }> = []
    if (upgradesMap instanceof Map) {
      for (const entry of upgradesMap.values()) {
        if (typeof entry.handler === 'function') {
          const original = entry.handler as UpgradeHandler
          entry.handler = fenceUpgrade(original)
          wrappedUpgrades.push({ entry, original })
        }
      }
      restore.push(() => {
        for (const { entry, original } of wrappedUpgrades) entry.handler = original
      })
    }

    const originalRegisterUpgrade = webServer.registerUpgrade.bind(webServer)
    webServer.registerUpgrade = (route) => {
      if (WS_EVENTS_PATHS.has(route.path) && typeof route.handler === 'function') {
        const original = route.handler as UpgradeHandler
        route.handler = fenceUpgrade(original)
      }
      return originalRegisterUpgrade(route)
    }
    restore.push(() => { webServer.registerUpgrade = originalRegisterUpgrade })

    webCtx.effect(() => () => {
      for (const undo of restore.reverse()) undo()
    }, 'edu-auth: teardown')
  })
}
