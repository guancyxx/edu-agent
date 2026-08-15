/**
 * JWT verification (HS256) implemented with node:crypto only — verified
 * against real edu-agent backend tokens (backend/app/utils/auth.py:
 * python-jose, HS256, claims sub/iat/exp, secret via EDU_SECRET_KEY env
 * with pydantic-settings EDU_ prefix; default "change-me-in-production").
 */

import { createHmac, timingSafeEqual } from 'node:crypto'

export interface JwtClaims {
  sub: string
  exp?: number
  iat?: number
}

function base64UrlDecode(input: string): Buffer {
  return Buffer.from(input.replace(/-/g, '+').replace(/_/g, '/'), 'base64')
}

/** Verify signature (HS256) + expiry; returns claims or undefined. */
export function verifyJwt(token: string, secret: string): JwtClaims | undefined {
  const parts = token.split('.')
  if (parts.length !== 3) return undefined
  const [head, payload, sig] = parts
  if (head.length === 0 || payload.length === 0 || sig.length === 0) return undefined

  let header: { alg?: unknown }
  let claims: Record<string, unknown>
  try {
    header = JSON.parse(base64UrlDecode(head).toString('utf8')) as { alg?: unknown }
    claims = JSON.parse(base64UrlDecode(payload).toString('utf8')) as Record<string, unknown>
  } catch {
    return undefined
  }
  if (header.alg !== 'HS256') return undefined

  const expected = createHmac('sha256', secret).update(`${head}.${payload}`).digest()
  const actual = base64UrlDecode(sig)
  if (actual.length !== expected.length || !timingSafeEqual(actual, expected)) return undefined

  const exp = claims['exp']
  if (typeof exp === 'number' && Date.now() / 1000 >= exp) return undefined

  if (typeof claims['sub'] !== 'string' || claims['sub'].length === 0) return undefined
  return { sub: claims['sub'], exp: typeof exp === 'number' ? exp : undefined,
    iat: typeof claims['iat'] === 'number' ? claims['iat'] : undefined }
}

/** Extract and verify the bearer JWT from an authorization header. */
export function bearerClaims(
  header: string | string[] | undefined,
  secret: string,
): JwtClaims | undefined {
  const value = Array.isArray(header) ? header[0] : header
  if (typeof value !== 'string') return undefined
  const match = /^Bearer\s+(.+)$/i.exec(value.trim())
  return match === null ? undefined : verifyJwt(match[1].trim(), secret)
}
