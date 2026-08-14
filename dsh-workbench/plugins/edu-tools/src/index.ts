/**
 * edu-tools — first batch of teaching tools for the dsh student workbench
 * (edu-agent, docs/PLAN-dsh-workbench.md §3.3).
 *
 * Three model-facing tools (defineTool / ctx.tools.register):
 *
 *   query_mistakes  → GET  {EDU_BASE_URL}/api/mistakes?subject=&limit-ish
 *   get_curriculum  → reads backend/app/curriculum/data/*.yaml locally
 *                     (no HTTP route exists yet; README documents the
 *                     future swap to GET /api/curriculum)
 *   submit_answer   → POST {EDU_BASE_URL}/api/mistakes with a minimal
 *                     answer-submission payload (README documents the
 *                     contract; no dedicated backend route exists yet)
 *
 * HTTP tools send `Authorization: Bearer $EDU_TOKEN` on every call. When the
 * backend is unreachable (connection refused / timeout) the tools degrade to
 * a fixed JSON body tagged `"backend_unavailable": true` so the model-facing
 * call chain still works end to end.
 */

import type { Context } from '/Users/guanchunyuan/workspace/deepseek-harness/vendor/cordis/src/index.ts'
import { defineTool } from '/Users/guanchunyuan/workspace/deepseek-harness/packages/core/tools/src/index.ts'
import * as fs from 'node:fs'
import { join } from 'node:path'

export const name = 'edu-tools'
export const inject = ['tools']

// ── Config ─────────────────────────────────────────────────────────

const BASE_URL = (process.env.EDU_BASE_URL ?? 'http://127.0.0.1:8000').replace(/\/+$/, '')
const TOKEN = process.env.EDU_TOKEN ?? ''
const TIMEOUT_MS = 4000

// Backend curriculum YAMLs, read locally as the documented fallback because
// the backend exposes no curriculum HTTP route yet.
const CURRICULUM_DATA_DIRS = [
  join(import.meta.dirname, 'data'),
  '/Users/guanchunyuan/workspace/edu-agent/backend/app/curriculum/data',
]

// ── HTTP helper ────────────────────────────────────────────────────

interface BackendResult {
  ok: boolean
  status: number
  body: unknown
}

async function callBackend(method: 'GET' | 'POST', path: string, body?: unknown): Promise<BackendResult> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS)
  try {
    const res = await fetch(`${BASE_URL}${path}`, {
      method,
      headers: {
        ...(body !== undefined ? { 'content-type': 'application/json' } : {}),
        ...(TOKEN ? { authorization: `Bearer ${TOKEN}` } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    })
    const text = await res.text()
    let parsed: unknown
    try {
      parsed = JSON.parse(text)
    } catch {
      parsed = text
    }
    return { ok: res.ok, status: res.status, body: parsed }
  } finally {
    clearTimeout(timer)
  }
}

function unavailable(method: string, path: string, err: unknown): BackendResult {
  return {
    ok: false,
    status: 0,
    body: {
      backend_unavailable: true,
      detail: `backend unreachable (${method} ${BASE_URL}${path}): ${err instanceof Error ? err.message : String(err)}`,
    },
  }
}

// ── Minimal local YAML subset parser ───────────────────────────────
// Line-based recursive descent over the backend curriculum files' subset:
// nested maps, block sequences (incl. compact `- key: value` items),
// quoted/plain scalars, and inline [a, b] / {k: v} flow collections.

type YamlNode = string | number | YamlList | YamlMap
interface YamlList extends Array<YamlNode> {}
interface YamlMap { [k: string]: YamlNode }

interface YamlLine { indent: number; text: string }

/** Strip comments and blanks; keep per-line indent. */
function yamlLines(src: string): YamlLine[] {
  const out: YamlLine[] = []
  for (const raw of src.split('\n')) {
    // remove comments not inside quotes
    let s = ''
    let q: string | null = null
    for (let i = 0; i < raw.length; i++) {
      const c = raw[i]
      if (q) {
        s += c
        if (c === q && raw[i - 1] !== '\\') q = null
      } else if (c === '"' || c === "'") {
        q = c
        s += c
      } else if (c === '#' && (i === 0 || raw[i - 1] === ' ' || raw[i - 1] === '\t')) {
        break
      } else {
        s += c
      }
    }
    const t = s.replace(/\s+$/, '')
    if (!t.trim()) continue
    const indent = t.length - t.trimStart().length
    out.push({ indent, text: t.trim() })
  }
  return out
}

class MiniYaml {
  private pos = 0
  constructor(private readonly lines: YamlLine[]) {}

  static parse(src: string): YamlMap {
    const doc = new MiniYaml(yamlLines(src)).parseNode(0)
    if (doc && typeof doc === 'object' && !Array.isArray(doc)) return doc
    return { items: doc as YamlNode }
  }

  private done(): boolean { return this.pos >= this.lines.length }
  private peek(): YamlLine | undefined { return this.lines[this.pos] }

  /** Parse a map or sequence whose items sit at exactly `indent`. */
  private parseNode(indent: number): YamlNode {
    const line = this.peek()
    if (!line) return ''
    if (line.text === '-' || line.text.startsWith('- ')) return this.parseSequence(indent)
    return this.parseMap(indent)
  }

  private parseSequence(indent: number): YamlList {
    const list: YamlList = []
    while (!this.done()) {
      const line = this.peek()
      if (!line || line.indent < indent || !line.text.startsWith('-')) break
      if (line.indent > indent) break // deeper content belongs to previous item
      const rest = line.text.slice(1).trim() // after '-'
      this.pos++
      if (!rest) {
        // value on following lines
        const next = this.peek()
        if (next && next.indent > indent) list.push(this.parseNode(next.indent))
        else list.push('')
      } else if (/^[^'"\[\{\s]+:(\s|$)/.test(rest) || /^["'][^"']*["']:(\s|$)/.test(rest)) {
        // compact map item: `- key: value` — key starts at column indent+2
        // Re-inject as a virtual map: parse rest as first entry, siblings follow.
        list.push(this.parseCompactMap(rest, indent + 2))
      } else {
        list.push(parseScalar(rest))
      }
    }
    return list
  }

  /** Parse a compact map whose first entry text is `first`, siblings at `col`. */
  private parseCompactMap(first: string, col: number): YamlMap {
    const map: YamlMap = {}
    this.parseMapEntry(map, first, col)
    // sibling keys of this item appear at exactly col
    while (!this.done()) {
      const line = this.peek()
      if (!line || line.indent !== col || line.text.startsWith('-')) break
      this.pos++
      this.parseMapEntry(map, line.text, col)
    }
    return map
  }

  private parseMap(indent: number): YamlMap {
    const map: YamlMap = {}
    while (!this.done()) {
      const line = this.peek()
      if (!line || line.indent < indent) break
      if (line.indent > indent) { this.pos++; continue } // unexpected; skip
      if (line.text.startsWith('-')) break
      this.pos++
      this.parseMapEntry(map, line.text, line.indent)
    }
    return map
  }

  /**
   * Parse one `key: value` line into `map`. Nested value (deeper lines)
   * or inline flow value. `col` = column where sibling keys of this key sit.
   */
  private parseMapEntry(map: YamlMap, text: string, _col: number): void {
    const ci = findColon(text)
    if (ci < 0) {
      map[text] = ''
      return
    }
    const key = unquote(text.slice(0, ci).trim())
    const rest = text.slice(ci + 1).trim()
    if (!rest) {
      // nested block or empty
      const next = this.peek()
      if (next && next.indent > _col) {
        map[key] = this.parseNode(next.indent)
      } else {
        map[key] = ''
      }
    } else {
      map[key] = parseScalar(rest)
    }
  }
}

/** Find the colon that separates key from value (outside quotes/brackets). */
function findColon(s: string): number {
  let depth = 0
  let q: string | null = null
  for (let i = 0; i < s.length; i++) {
    const c = s[i]
    if (q) {
      if (c === q && s[i - 1] !== '\\') q = null
    } else if (c === '"' || c === "'") q = c
    else if (c === '[' || c === '{') depth++
    else if (c === ']' || c === '}') depth--
    else if (c === ':' && depth === 0 && (i + 1 === s.length || s[i + 1] === ' ')) return i
  }
  return -1
}

function unquote(s: string): string {
  if (s.length >= 2 && ((s[0] === '"' && s.at(-1) === '"') || (s[0] === "'" && s.at(-1) === "'"))) {
    return s.slice(1, -1)
  }
  return s
}

function parseScalar(s: string): YamlNode {
  const c = s[0]
  if (c === '[') return parseFlowList(s)
  if (c === '{') return parseFlowMap(s)
  if (c === '"' || c === "'") return unquote(s)
  const t = s.trim()
  if (t === '' || t === 'null' || t === '~') return ''
  if (t === 'true') return 1
  if (t === 'false') return 0
  if (/^-?\d+(\.\d+)?$/.test(t)) return Number(t)
  return t
}

/** Parse one flow collection starting at s[0]; returns value + end index. */
function parseFlow(s: string, i: number): { value: YamlNode; next: number } {
  const c = s[i]
  if (c === '[') {
    const list: YamlList = []
    i++
    i = skipWs(s, i)
    if (s[i] === ']') return { value: list, next: i + 1 }
    for (;;) {
      const r = parseFlowItem(s, i)
      list.push(r.value)
      i = skipWs(s, r.next)
      if (s[i] === ',') { i++; i = skipWs(s, i); continue }
      if (s[i] === ']') return { value: list, next: i + 1 }
      // malformed; bail
      return { value: list, next: s.length }
    }
  }
  // '{'
  const map: YamlMap = {}
  i++
  i = skipWs(s, i)
  if (s[i] === '}') return { value: map, next: i + 1 }
  for (;;) {
    const ci = findColon(s.slice(i))
    if (ci < 0) return { value: map, next: s.length }
    const key = unquote(s.slice(i, i + ci).trim())
    const r = parseFlowItem(s, i + ci + 1)
    map[key] = r.value
    i = skipWs(s, r.next)
    if (s[i] === ',') { i++; i = skipWs(s, i); continue }
    if (s[i] === '}') return { value: map, next: i + 1 }
    return { value: map, next: s.length }
  }
}

function skipWs(s: string, i: number): number {
  while (i < s.length && (s[i] === ' ' || s[i] === '\t')) i++
  return i
}

function parseFlowItem(s: string, i: number): { value: YamlNode; next: number } {
  i = skipWs(s, i)
  const c = s[i]
  if (c === '[' || c === '{') return parseFlow(s, i)
  if (c === '"' || c === "'") {
    let j = i + 1
    while (j < s.length && s[j] !== c) {
      if (s[j] === '\\') j++
      j++
    }
    return { value: unquote(s.slice(i, j + 1)), next: j + 1 }
  }
  let j = i
  while (j < s.length && s[j] !== ',' && s[j] !== ']' && s[j] !== '}') j++
  return { value: parseScalar(s.slice(i, j)), next: j }
}

function parseFlowList(s: string): YamlList {
  return parseFlow(s, 0).value as YamlList
}

function parseFlowMap(s: string): YamlMap {
  return parseFlow(s, 0).value as YamlMap
}

function loadCurriculumFiles(): { file: string; data: YamlMap }[] {
  const results: { file: string; data: YamlMap }[] = []
  for (const dir of CURRICULUM_DATA_DIRS) {
    let names: string[]
    try {
      names = fs.readdirSync(dir).filter((n: string) => n.endsWith('.yaml') || n.endsWith('.yml'))
    } catch {
      continue
    }
    for (const n of names) {
      try {
        const text = fs.readFileSync(join(dir, n), 'utf8')
        results.push({ file: n, data: MiniYaml.parse(text) })
      } catch {
        // skip unreadable file
      }
    }
  }
  return results
}

// ── Tool registration ──────────────────────────────────────────────

export function apply(ctx: Context): void {
  // The `tools` service key is added by dsh's ToolRuntime plugin via TS
  // declaration merging inside the dsh workspace; this file lives outside it,
  // so the merged key is asserted here (runtime-verified by the plugin boot).
  const tools = (ctx as unknown as { tools: import('/Users/guanchunyuan/workspace/deepseek-harness/packages/core/tools/src/index.ts').ToolRuntime }).tools
  // 1) query_mistakes — GET /api/mistakes (Bearer auth), slice to limit.
  tools.register(defineTool({
    name: 'query_mistakes',
    description:
      "Fetch the student's mistake notebook entries from the edu-agent backend. " +
      'Returns a JSON array of entries (id, subject, question, answers, explanation, review status).',
    parameters: {
      subject: { type: 'string', description: 'Filter by subject, e.g. "math". Omit for all subjects.' },
      limit: { type: 'number', description: 'Max entries to return (default 20, max 50).' },
    },
    output: {
      schema: { type: 'string' },
      render: (_args, value) => [{ type: 'text', text: value }],
    },
    async execute(args) {
      const subject = typeof args.subject === 'string' && args.subject ? args.subject : null
      const limit = Math.max(1, Math.min(50, typeof args.limit === 'number' ? args.limit : 20))
      const qs = new URLSearchParams()
      if (subject) qs.set('subject', subject)
      let result: BackendResult
      try {
        result = await callBackend('GET', `/api/mistakes${qs.size ? `?${qs}` : ''}`)
      } catch (err) {
        result = unavailable('GET', '/api/mistakes', err)
      }
      const body = result.body
      if (result.ok && Array.isArray(body)) {
        return JSON.stringify({ count: Math.min(body.length, limit), mistakes: body.slice(0, limit) })
      }
      return JSON.stringify({ ok: false, status: result.status, body })
    },
  }))

  // 2) get_curriculum — local YAML fallback (no backend route yet).
  tools.register(defineTool({
    name: 'get_curriculum',
    description:
      'Get the curriculum knowledge tree (chapters and knowledge points). ' +
      'Currently reads the backend curriculum YAML files directly; an HTTP route is future work.',
    parameters: {
      grade: { type: 'number', description: 'Grade level filter, e.g. 7 or 8. Omit for all grades.' },
      subject: { type: 'string', description: 'Subject filter, e.g. "math".' },
    },
    output: {
      schema: { type: 'string' },
      render: (_args, value) => [{ type: 'text', text: value }],
    },
    async execute(args) {
      const files = loadCurriculumFiles()
      const grade = typeof args.grade === 'number' ? args.grade : null
      const subject = typeof args.subject === 'string' && args.subject ? args.subject : null
      const matched = files.filter(({ data }) => {
        const g = data.grade
        const s = data.subject
        const gradeOk = grade === null || g === grade || String(g) === String(grade)
        const subjectOk = subject === null || s === subject
        return gradeOk && subjectOk
      })
      if (matched.length === 0) {
        return JSON.stringify({
          ok: false,
          source: 'local-yaml-fallback',
          detail: 'No curriculum file matched the filters.',
          available: files.map(({ file, data }) => ({ file, subject: data.subject, grade: data.grade, title: data.title })),
        })
      }
      // Compact projection: chapters + knowledge point ids/titles.
      const trees = matched.map(({ file, data }) => ({
        file,
        subject: data.subject,
        grade: data.grade,
        title: data.title,
        chapters: Array.isArray(data.chapters)
          ? (data.chapters as YamlMap[]).map((ch) => ({
              id: ch.id,
              title: ch.title,
              knowledge_points: Array.isArray(ch.knowledge_points)
                ? (ch.knowledge_points as YamlMap[]).map((kp) => ({
                    id: kp.id,
                    title: kp.title,
                    difficulty: kp.difficulty,
                  }))
                : [],
            }))
          : [],
      }))
      return JSON.stringify({ ok: true, source: 'local-yaml-fallback', curricula: trees })
    },
  }))

  // 3) submit_answer — POST /api/mistakes with a minimal answer payload.
  tools.register(defineTool({
    name: 'submit_answer',
    description:
      "Submit the student's answer to a question to the edu-agent backend. " +
      'Creates a mistake-notebook entry that the spaced-repetition scheduler picks up for later review.',
    parameters: {
      question: { type: 'string', required: true, description: 'The question text the student answered.' },
      student_answer: { type: 'string', required: true, description: "The student's answer." },
      correct_answer: { type: 'string', description: 'The correct answer, if known.' },
      subject: { type: 'string', description: 'Subject, e.g. "math" (default "math").' },
      knowledge_point_id: { type: 'string', description: 'Curriculum knowledge point id, e.g. "7-1-3".' },
      explanation: { type: 'string', description: 'Optional explanation to store with the entry.' },
    },
    output: {
      schema: { type: 'string' },
      render: (_args, value) => [{ type: 'text', text: value }],
    },
    async execute(args) {
      const payload = {
        subject: typeof args.subject === 'string' && args.subject ? args.subject : 'math',
        question: args.question,
        student_answer: args.student_answer,
        correct_answer: typeof args.correct_answer === 'string' ? args.correct_answer : null,
        explanation: typeof args.explanation === 'string' ? args.explanation : null,
        knowledge_point_id: typeof args.knowledge_point_id === 'string' ? args.knowledge_point_id : null,
        source: 'dsh-workbench',
      }
      let result: BackendResult
      try {
        result = await callBackend('POST', '/api/mistakes', payload)
      } catch (err) {
        result = unavailable('POST', '/api/mistakes', err)
      }
      return JSON.stringify({ ok: result.ok, status: result.status, body: result.body })
    },
  }))
}
