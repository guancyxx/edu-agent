/**
 * edu-auth — experimental login gate + /api token fence for the dsh student
 * workbench (edu-agent track 2).
 *
 * Function A: serves a minimal English login page at GET /workbench.
 * Function B: rejects every /api HTTP request that carries no bearer token.
 *
 * Mechanism note (researched in T2): the Typert `/api` interceptor seat is
 * single-holder and already occupied by typert-gateway in the default web
 * composition, and rpcFetchHandler has no 401 return path. The equivalent
 * seam used here is the `/api` prefix WebRoute registered by client-connection:
 * this plugin wraps that route's handler (and any future `/api` prefix
 * registration, for load-order robustness) with an Authorization check that
 * answers 401 before the trust fence/bridge run.
 *
 * Token validation is real JWT verification (T8): HS256 signature and expiry
 * are checked against EDU_JWT_SECRET (same secret the edu-agent backend signs
 * with; falls back to the backend's own default when unset). Hand-rolled with
 * node:crypto in ./jwt — no dependencies.
 */

import type { Context } from '@deepseek-ai/cordis'

import { bearerClaims } from './jwt.ts'

export const name = 'edu-auth'
export const inject = ['webServer']

const API_PREFIX = '/api'
const WORKBENCH_PATH = '/workbench'

const LOGIN_PAGE = `<!doctype html>
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
</style>
</head>
<body>
<form method="get" action="/workbench">
  <h1>Edu Workbench</h1>
  <label for="username">Username</label>
  <input id="username" name="username" autocomplete="username">
  <label for="password">Password</label>
  <input id="password" name="password" type="password" autocomplete="current-password">
  <button type="submit">Sign in</button>
</form>
</body>
</html>
`

/** Verify the bearer JWT (HS256 signature + expiry) against EDU_JWT_SECRET. */
function validAuth(req: { headers: { authorization?: string | string[] } }): boolean {
  const secret = process.env['EDU_JWT_SECRET'] ?? 'change-me-in-production'
  return bearerClaims(req.headers.authorization, secret) !== undefined
}

export function apply(ctx: Context): void {
  ctx.inject(['webServer'], (webCtx) => {
    const webServer = webCtx.webServer as unknown as {
      register: (route: { kind: string; path: string; handler: unknown }) => () => void
      prefixes: Map<string, { kind: string; path: string; handler: unknown }>
    }

    const restore: Array<() => void> = []

    // Function A: login page at /workbench (public WebServer API).
    restore.push(webCtx.effect(() => webServer.register({
      kind: 'exact',
      path: WORKBENCH_PATH,
      handler: (_req, res) => {
        res.writeHead(200, { 'content-type': 'text/html; charset=utf-8' })
        res.end(LOGIN_PAGE)
      },
    }), 'edu-auth: /workbench login page'))

    // Function B: token fence over the /api prefix route.
    // Wrap the handler of an already-registered /api route (normal case: this
    // plugin loads after client-connection), and also wrap webServer.register
    // so an /api prefix registered later is fenced too.
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

    webCtx.effect(() => () => {
      for (const undo of restore.reverse()) undo()
    }, 'edu-auth: teardown')
  })
}
