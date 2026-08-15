/**
 * edu-session-owner — session ownership stamping + list isolation for the dsh
 * student workbench (edu-agent track 3, docs/PLAN-dsh-workbench.md §3.2).
 *
 * Stacks on top of edu-auth (does not modify it): this plugin wraps the same
 * `/api` prefix WebRoute handler seam that edu-auth fences and assumes the
 * bearer token has already been verified. Identity comes from the JWT `sub`
 * claim (T8): the edu-auth fence guarantees a valid HS256-signed,
 * unexpired token, so this plugin only needs to re-extract the claim with the
 * same hand-rolled verifier. Load this patch alongside/after edu-auth.
 *
 * Wire format (verified against packages/client/connection/src/rpc-host.ts,
 * packages/host/apiproxy/src/fetch/handler.ts, and live curl):
 *
 *   POST /api/<method>  content-type: application/json
 *   body:   { type: 'client-request', rpcId, method, payload }
 *   reply:  { type: 'server-response', rpcId, result: { ok: true, value } }
 *                             … or { ok: false, error }
 *
 * Intercepted methods:
 *
 * - session.create → after the inner handler succeeds, the created sessionId
 *   is stamped with the calling token's user_id in an owner registry
 *   (in-memory + JSON sidecar under DSH_HOME so ownership survives host
 *   restarts). The wire shapes of SessionSummary / create payload have no
 *   metadata field (checked packages/host/apiproxy/src/api/sessions.ts), so
 *   ownership lives in the sidecar rather than session metadata; see README
 *   for the limitation discussion.
 * - session.list / session.search → the response's value.items is filtered
 *   to sessions whose owner is the calling token's user_id. Sessions without
 *   a recorded owner (created before this plugin existed) are hidden from
 *   everyone (fail-closed).
 *
 * Everything else passes through untouched. Implementation buffers the
 * request body (the stock bridge buffers it anyway), replays it through the
 * wrapped (edu-auth → trust fence → RPC carrier) handler against a fake
 * response, rewrites the JSON envelope, then writes the real response.
 */

import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import type { Context } from '@deepseek-ai/cordis'

import { bearerClaims } from './jwt.ts'

export const name = 'edu-session-owner'
export const inject = ['webServer']

const API_PREFIX = '/api'

interface NodeReq {
  method?: string
  url?: string
  headers: Record<string, string | string[] | undefined>
  on?: (event: string, listener: () => void) => unknown
  [Symbol.asyncIterator](): AsyncIterableIterator<Buffer>
}

interface NodeRes {
  writeHead: (status: number, headers?: Record<string, string>) => NodeRes
  write: (chunk: Buffer | string) => boolean
  end: (body?: Buffer | string) => void
  readonly writableEnded: boolean
  /** node:http ServerResponse event API; the stock bridge registers 'close'. */
  on: (event: string, listener: () => void) => NodeRes
}

type RouteHandler = (req: never, res: never) => void | Promise<void>

/** Extract the caller's user_id from the verified JWT's `sub` claim (T8). */
function userFromAuth(header: string | string[] | undefined): string | undefined {
  const secret = process.env['EDU_JWT_SECRET'] ?? 'change-me-in-production'
  return bearerClaims(header, secret)?.sub
}

function isClientRequest(body: unknown): body is { type: string; method: string; payload: unknown } {
  if (typeof body !== 'object' || body === null) return false
  const record = body as Record<string, unknown>
  return record['type'] === 'client-request' && typeof record['method'] === 'string'
}

interface ServerResponseWire {
  type?: string
  rpcId?: string
  result?: { ok?: boolean; value?: unknown; error?: unknown }
}

/**
 * session.* methods that act on one existing session (T9). The payload's
 * sessionId names the target; a caller whose user_id is not the session's
 * recorded owner is rejected before the inner handler runs. Fail-closed:
 * a session with no recorded owner is owned by nobody.
 */
const SESSION_SCOPED_METHODS = new Set([
  'session.history',
  'session.models',
  'session.selectModel',
  'session.rename',
  'session.fork',
  'session.prompt',
  'session.attachment',
  'session.updateQueue',
  'session.cancel',
])

/** sessionId → owner sidecar, persisted under DSH_HOME. */
class OwnerRegistry {
  private readonly owners = new Map<string, string>()
  private readonly file: string

  constructor(dir: string) {
    this.file = join(dir, 'edu-session-owners.json')
    try {
      if (existsSync(this.file)) {
        const raw = JSON.parse(readFileSync(this.file, 'utf8')) as Record<string, unknown>
        for (const [sessionId, owner] of Object.entries(raw)) {
          if (typeof owner === 'string') this.owners.set(sessionId, owner)
        }
      }
    } catch {
      // Unreadable sidecar: start empty (fail-closed for unregistered sessions).
    }
  }

  get(sessionId: string): string | undefined {
    return this.owners.get(sessionId)
  }

  set(sessionId: string, owner: string): void {
    this.owners.set(sessionId, owner)
    try {
      const record: Record<string, string> = {}
      for (const [id, own] of this.owners) record[id] = own
      mkdirSync(dirname(this.file), { recursive: true })
      writeFileSync(this.file, `${JSON.stringify(record, null, 2)}\n`)
    } catch {
      // Durable write failure: in-memory ownership still enforced this boot.
    }
  }
}

export function apply(ctx: Context): void {
  ctx.inject(['webServer'], (webCtx: Context) => {
    const webServer = webCtx.webServer as unknown as {
      register: (route: { kind: string; path: string; handler: unknown }) => () => void
      prefixes: Map<string, { kind: string; path: string; handler: unknown }>
    }

    const registry = new OwnerRegistry(process.env['DSH_HOME'] ?? process.cwd())
    const log = (message: string): void => {
      const logger = (ctx as unknown as { logger?: { info?: (m: string) => void } }).logger
      logger?.info?.(message)
    }

    /** A one-shot replay stream over an already-buffered body. */
    function replayStream(body: Buffer): () => AsyncIterableIterator<Buffer> {
      return async function* () {
        if (body.length > 0) yield body
      }
    }

    /**
     * Run the wrapped handler with the buffered body and a fake response,
     * rewrite the envelope per owner rules, write the real response.
     */
    async function interceptRpc(
      handler: RouteHandler,
      req: NodeReq,
      res: NodeRes,
      body: Buffer,
      owner: string,
      method: string,
    ): Promise<void> {
      const replayReq = Object.create(req) as NodeReq
      Object.assign(replayReq, {
        [Symbol.asyncIterator]: () => replayStream(body)()[Symbol.asyncIterator](),
        headers: { ...req.headers, 'content-length': String(body.length) },
      })

      let status = 200
      let responseHeaders: Record<string, string> = {}
      const chunks: Buffer[] = []
      const self: NodeRes = {
        get writableEnded() { return false },
        on: (_event: string, _listener: () => void) => self,
        writeHead: (code: number, headers?: Record<string, string>) => {
          status = code
          responseHeaders = headers ?? {}
          return self
        },
        write: (chunk: Buffer | string) => {
          chunks.push(typeof chunk === 'string' ? Buffer.from(chunk) : chunk)
          return true
        },
        end: (chunk?: Buffer | string) => {
          if (chunk !== undefined) chunks.push(typeof chunk === 'string' ? Buffer.from(chunk) : chunk)
        },
      }

      let handlerError: unknown
      try {
        await handler(replayReq as never, self as never)
      } catch (error) {
        handlerError = error
      }
      if (handlerError !== undefined) {
        res.writeHead(500, { 'content-type': 'text/plain; charset=utf-8' })
        res.end(`edu-session-owner: handler failure: ${String(handlerError)}`)
        return
      }

      const raw = Buffer.concat(chunks)
      let out = raw
      if (status === 200) {
        try {
          const wire = JSON.parse(raw.toString('utf8')) as ServerResponseWire
          if (wire?.type === 'server-response' && wire.result?.ok === true) {
            if (method === 'session.create') {
              const value = wire.result.value as { sessionId?: unknown } | undefined
              if (typeof value?.sessionId === 'string') {
                registry.set(value.sessionId, owner)
                log(`edu-session-owner: session ${value.sessionId} owner=${owner}`)
              }
            } else if (method === 'session.fork') {
              // The fork's new sessionId is owned by the fork caller (who was
              // already verified as the source session's owner).
              const value = wire.result.value as { sessionId?: unknown } | undefined
              if (typeof value?.sessionId === 'string') {
                registry.set(value.sessionId, owner)
                log(`edu-session-owner: fork ${value.sessionId} owner=${owner}`)
              }
            } else {
              const value = wire.result.value as { items?: unknown } | undefined
              if (Array.isArray(value?.items)) {
                const items = value.items as Array<{ sessionId?: unknown }>
                const before = items.length
                value.items = items.filter(
                  (item) => typeof item.sessionId === 'string' && registry.get(item.sessionId) === owner,
                )
                log(`edu-session-owner: ${method} owner=${owner} ${before}->${value.items.length} items`)
                out = Buffer.from(JSON.stringify(wire))
              }
            }
          }
        } catch {
          // Non-JSON or unexpected shape: pass through unchanged.
        }
      }

      const headers = { ...responseHeaders }
      delete headers['content-length']
      res.writeHead(status, headers)
      res.end(out)
    }

    /**
     * Answer 403 with a plain-text body — used for owner-mismatch on
     * session-scoped methods (the JSON envelope the carrier would produce is
     * unnecessary because the request is rejected before it reaches RPC).
     */
    function denyForbidden(res: NodeRes, owner: string, sessionId: string, method: string): void {
      log(`edu-session-owner: DENY ${method} user=${owner} session=${sessionId} (not owner)`)
      res.writeHead(403, { 'content-type': 'text/plain; charset=utf-8' })
      res.end('forbidden: session belongs to another user')
    }

    /** Wrap one /api route handler with owner-aware envelope rewriting. */
    function wrapHandler(handler: RouteHandler): (req: NodeReq, res: NodeRes) => void | Promise<void> {
      return async (req, res) => {
        const owner = userFromAuth(req.headers.authorization)
        const pathname = req.url === undefined ? '' : new URL(req.url, 'http://dsh.internal').pathname
        const method = pathname.startsWith(`${API_PREFIX}/`) ? pathname.slice(API_PREFIX.length + 1) : undefined
        const intercepted = owner !== undefined && method !== undefined
          && (method === 'session.create' || method === 'session.list' || method === 'session.search'
            || SESSION_SCOPED_METHODS.has(method))
          && (req.method ?? '') === 'POST'
          && (req.headers['content-type']?.split(';', 1)[0]?.trim().toLowerCase() ?? '') === 'application/json'

        if (!intercepted) {
          return handler(req as never, res as never)
        }

        const MAX_BODY = 64 * 1024 * 1024
        const declared = req.headers['content-length']
        if (declared !== undefined && Number(declared) > MAX_BODY) {
          return handler(req as never, res as never)
        }
        const chunks: Buffer[] = []
        let received = 0
        for await (const chunk of req) {
          received += chunk.byteLength
          if (received > MAX_BODY) return handler(req as never, res as never)
          chunks.push(chunk)
        }
        const body = Buffer.concat(chunks)

        let parsed: unknown
        try {
          parsed = body.length === 0 ? undefined : JSON.parse(body.toString('utf8'))
        } catch {
          parsed = undefined
        }
        if (!isClientRequest(parsed)) {
          // Not a well-formed envelope: replay bytes verbatim (the carrier
          // produces its own bad-request error).
          const replayReq = Object.create(req) as NodeReq
          Object.assign(replayReq, {
            [Symbol.asyncIterator]: () => replayStream(body)()[Symbol.asyncIterator](),
            headers: { ...req.headers, 'content-length': String(body.length) },
          })
          await handler(replayReq as never, res as never)
          return
        }

        // T9: session-scoped methods — reject before the handler runs when the
        // caller is not the session's recorded owner (fail-closed for sessions
        // without a recorded owner). The method in the body must match the
        // path (the carrier enforces this too; rejecting early is equivalent).
        if (method !== undefined && SESSION_SCOPED_METHODS.has(method)) {
          const payload = (parsed as { payload?: unknown }).payload
          const sessionId = typeof payload === 'object' && payload !== null
            ? (payload as Record<string, unknown>)['sessionId']
            : undefined
          if (typeof sessionId !== 'string' || sessionId.length === 0) {
            // Malformed target: let the inner handler produce its own error.
          } else if (registry.get(sessionId) !== owner) {
            denyForbidden(res, owner, sessionId, method)
            return
          }
        }

        await interceptRpc(handler, req, res, body, owner, method as string)
      }
    }

    const restore: Array<() => void> = []

    const existing = webServer.prefixes.get(API_PREFIX)
    if (existing !== undefined && typeof existing.handler === 'function') {
      const original = existing.handler as RouteHandler
      existing.handler = wrapHandler(original)
      restore.push(() => { existing.handler = original })
    }

    const originalRegister = webServer.register.bind(webServer)
    webServer.register = (route: { kind: string; path: string; handler: unknown }) => {
      if (route.kind === 'prefix' && route.path === API_PREFIX && typeof route.handler === 'function') {
        const original = route.handler as RouteHandler
        route.handler = wrapHandler(original)
      }
      return originalRegister(route)
    }
    restore.push(() => { webServer.register = originalRegister })

    webCtx.effect(() => () => {
      for (const undo of restore.reverse()) undo()
    }, 'edu-session-owner: teardown')
  })
}
