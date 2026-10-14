import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Rails } from '../types'
import {
  afterWrite,
  ALLOW_MARK,
  bashDeny,
  commitScan,
  notesRows,
  pathDeny,
  stackOf,
  scanDiff,
  statusPaths,
  deployRefs,
  undeployed,
  stacksMentioned,
  notesContext,
  secretsFromEnv,
  redact,
  nasRisk,
} from './rules'
import type { Secret } from './rules'

type $ = EngineInterface

const rails = atom({ plugin: 'nas-rails', key: 'rails' } as const, null)
const closing = atom({ plugin: 'nas-rails', key: 'closing' } as const, false)
const isHidden = atom({ plugin: 'nas-rails', key: 'isHidden' } as const, false)
const loadedNotes = atom({ plugin: 'nas-rails', key: 'loadedNotes' } as const, [])

const REFRESH_MS = 20_000
const base = (p: string) => p.slice(p.lastIndexOf('/') + 1)

// Caches of this environment; a reload starts them over.
let root: string | null | undefined
let started = false
let vendored: Set<string> | null = null
const touched = new Set<string>()
let lastDrift = ''
let lastRails = ''
let stackSet = new Set<string>()
let secrets: Secret[] = []

async function repoRoot($: $): Promise<string | null> {
  if (root !== undefined) return root
  const r = await $.session.root()
  const isRepo = (await $.fs.exists(`${r}/scripts/deploy.sh`)) && (await $.fs.exists(`${r}/secrets/vault.sops.yaml`))
  root = isRepo ? r : null
  return root
}

const relOf = (r: string, path: string) => (path.startsWith(`${r}/`) ? path.slice(r.length + 1) : null)

const git = ($: $, r: string, args: string[]) => $.process.run(['git', ...args], { cwd: r, timeoutMs: 10_000 })

async function vendoredCopies($: $, r: string): Promise<Set<string>> {
  if (vendored) return vendored
  const names = new Set(
    (await $.fs.list(`${r}/shared`))
      .filter(f => f.kind === 'file' && f.name.endsWith('.py') && !f.name.startsWith('test_'))
      .map(f => f.name),
  )
  const files = (await git($, r, ['ls-files'])).stdout.split('\n')
  vendored = new Set(files.filter(f => f && !f.startsWith('shared/') && names.has(base(f))))
  return vendored
}

async function stacksOf($: $, r: string): Promise<Set<string>> {
  const out = new Set<string>()
  for (const d of await $.fs.list(r)) {
    if (d.kind === 'dir' && !d.name.startsWith('.') && (await $.fs.exists(`${r}/${d.name}/docker-compose.yml`))) out.add(d.name)
  }
  return out
}

async function deployRecords($: $, r: string): Promise<Map<string, string>> {
  return deployRefs((await git($, r, ['for-each-ref', 'refs/deploy', '--format=%(refname:lstrip=2) %(objectname)'])).stdout)
}

/** What deploy.sh uploads: the worktree (`git stash create`), or HEAD when clean. */
async function worktreeSha($: $, r: string): Promise<string> {
  const stash = (await git($, r, ['stash', 'create'])).stdout.trim()
  return stash || (await git($, r, ['rev-parse', 'HEAD'])).stdout.trim()
}

/** Secret-named values of every rendered .env (gitignored, so `ls-files -oi`). */
async function loadSecrets($: $, r: string) {
  const list = await git($, r, ['ls-files', '-oi', '--exclude-standard', '--', ':(glob)**/.env', ':(glob)**/.env.deploy'])
  const found: Secret[] = []
  for (const f of list.stdout.split('\n').filter(Boolean)) {
    try {
      found.push(...secretsFromEnv(await $.fs.read(`${r}/${f}`)))
    } catch {
      // vanished between list and read
    }
  }
  // Longest first, so a value containing another is replaced whole.
  secrets = [...new Map(found.map(x => [x.value, x])).values()].sort((a, b) => b.value.length - a.value.length)
}

/** Adds each stack's 00_INDEX.md not yet in this conversation; returns the context blocks. */
async function notesFor($: $, r: string, wanted: string[]): Promise<string[]> {
  const have = await read($, loadedNotes)
  const fresh = wanted.filter(s => !have.includes(s))
  const out: string[] = []
  for (const s of fresh) {
    try {
      out.push(notesContext(s, await $.fs.read(`${r}/${s}/.notes/00_INDEX.md`)))
    } catch {
      // stack without notes
    }
  }
  if (fresh.length) await update($, loadedNotes, list => [...list, ...fresh])
  return out
}

/** Asks the person; a dismissed dialog or a session with nobody to ask is a no. */
async function confirm($: $, question: string): Promise<boolean> {
  try {
    return (await $.ui.ask(question, { options: ['Run it', 'Cancel'], header: 'NAS' })) === 'Run it'
  } catch {
    return false
  }
}

async function n8nKeyState($: $): Promise<'present' | 'missing' | 'unknown'> {
  try {
    const ran = await $.process.run(
      ['ssh', '-o', 'ConnectTimeout=8', '-o', 'BatchMode=yes', 'nas', 'sudo -n /usr/local/bin/docker exec n8n sh -c "test -s /home/node/.n8n/config && echo present || echo missing"'],
      { timeoutMs: 20_000 },
    )
    const word = ran.stdout.trim()
    return word === 'present' || word === 'missing' ? word : 'unknown'
  } catch {
    return 'unknown'
  }
}

async function refresh($: $): Promise<Rails | null> {
  const r = await repoRoot($)
  if (!r) return null
  vendored = null
  const stacks = await stacksOf($, r)
  stackSet = stacks
  await loadSecrets($, r)
  const status = await git($, r, ['status', '--porcelain', '-z', '--untracked-files=all'])
  const notes = notesRows([...statusPaths(status.stdout), ...touched], stacks)

  const records = await deployRecords($, r)
  const changed = new Map<string, string[] | null>()
  for (const sha of new Set(records.values())) {
    const d = await git($, r, ['diff', '--name-only', sha, 'HEAD'])
    changed.set(sha, d.exitCode === 0 ? d.stdout.split('\n').filter(Boolean) : null)
  }
  const und = undeployed(records, changed).filter(([s]) => stacks.has(s))

  const drift: Rails['drift'] = []
  for (const dst of await vendoredCopies($, r)) {
    const src = `shared/${base(dst)}`
    try {
      if ((await $.fs.read(`${r}/${src}`)) !== (await $.fs.read(`${r}/${dst}`))) drift.push({ src, dst })
    } catch {
      // a copy deleted in the worktree is git's business, not drift
    }
  }
  const driftKey = drift.map(d => d.dst).join(',')
  if (driftKey && driftKey !== lastDrift) {
    $.ui.toast(`shared drift: ${drift.map(d => d.dst).join(', ')} — run make sync-shared`, { timeoutMs: 8000 })
  }
  lastDrift = driftKey

  const next: Rails = { notes, undeployed: und, unrecorded: [...stacks].filter(s => !records.has(s)).length, drift }
  // The timer ticks every 20s; writing an unchanged value would redraw the band each time.
  const key = JSON.stringify(next)
  if (key !== lastRails) {
    lastRails = key
    await update($, rails, () => next)
  }
  return next
}

function ensureStarted($: $) {
  if (started) return
  started = true
  void $.command.register({ name: 'deployed', description: 'nas-rails: mark stacks as deployed at HEAD (args: stack,stack | all)' })
  void $.command.register({ name: 'rails', description: 'nas-rails: refresh and show the notes / deploy / shared-drift band' })
  $.clock.every(REFRESH_MS, () => void refresh($).catch(() => {}))
  void refresh($).catch(() => {})
}

async function readHook($: $, e: any, next: (e: any) => Promise<any>) {
  const r = await repoRoot($)
  const rel = r ? relOf(r, String(e.file_path ?? '')) : null
  const ran = await next(e)
  if (!r || rel === null || ran.deny !== undefined || ran.isError) return ran
  const stack = stackOf(rel, stackSet)
  if (!stack) return ran
  if (rel === `${stack}/.notes/00_INDEX.md`) {
    await update($, loadedNotes, list => (list.includes(stack) ? list : [...list, stack]))
    return ran
  }
  const ctx = await notesFor($, r, [stack])
  return ctx.length ? { ...ran, context: [...(ran.context ?? []), ...ctx] } : ran
}

const pendingNotes = (s: Rails) => s.notes.filter(n => !n.log || !n.index)
const noteLine = (n: Rails['notes'][number]) => `${n.stack} ${n.log ? '✓' : '✗'}log ${n.index ? '✓' : '✗'}index`

// A guard that throws must not lock the session out of Bash or Edit: these rails fail open.
const failOpen = <E,>(_: $, e: E, next: (e: E) => any) => next(e)

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const r = await repoRoot($)
    if (r) ensureStarted($)
    return next(e)
  })

  // ── guards ──────────────────────────────────────────────────────────────────

  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    if (!(await repoRoot($))) return next(e)
    const risk = nasRisk(e.command)
    if (risk.danger.length) {
      const yes = await confirm($, `Run a destructive NAS command (${risk.danger.join(', ')})?\n\n${e.command.slice(0, 600)}`)
      if (!yes) return { deny: `nas-rails: the person declined (or could not be asked about) a destructive NAS command: ${risk.danger.join(', ')}.` }
    }
    if (risk.startsN8n) {
      const key = await n8nKeyState($)
      if (key === 'missing') {
        return {
          deny:
            'nas-rails: n8n has no encryption key in /home/node/.n8n/config. Starting it now generates a new key and every stored credential becomes undecryptable for good. Restore n8n_data first (see n8n/.notes/00_INDEX.md).',
        }
      }
      if (key === 'unknown' && !(await confirm($, 'Could not verify n8n\'s encryption key (container down or SSH failed). Start n8n anyway?'))) {
        return { deny: 'nas-rails: n8n start refused: its encryption key could not be verified and the person did not confirm.' }
      }
    }
    const ran = await next(e)
    if (!risk.composeDirect || ran.deny !== undefined) return ran
    return {
      ...ran,
      context: [
        ...(ran.context ?? []),
        'nas-rails: compose ran straight on the NAS, so no ops-bot maintenance window was written: expect Uptime Kuma DOWN alerts for these containers. scripts/deploy.sh -s <stack> -y writes the window.',
      ],
    }
  }).catch(($, e, next) => {
    // Fail closed only for the commands this guard exists for; every other Bash call goes on.
    if (next.called) return next(e)
    let risky = true
    try {
      const r = nasRisk(e.command)
      risky = r.danger.length > 0 || r.startsN8n
    } catch {}
    return risky ? { deny: 'nas-rails: the NAS command guard failed, so this destructive/n8n command is refused. Check `claude --debug`.' } : next(e)
  })

  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    if (!(await repoRoot($))) return next(e)
    const why = bashDeny(e.command)
    return why ? { deny: `nas-rails: ${why}` } : next(e)
  }).catch(failOpen)

  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    const scan = commitScan(e.command)
    const r = await repoRoot($)
    if (!scan || !r) return next(e)
    let diff = (await git($, r, ['diff', '--cached', '-U0', '--no-color'])).stdout
    if (scan.includeWorktree) diff += '\n' + (await git($, r, ['diff', '-U0', '--no-color'])).stdout
    const found = scanDiff(diff)
    if (!found.length) return next(e)
    const list = found.slice(0, 15).map(f => `  ${f.file}:${f.line}  ${f.rule}  ${f.hint}`).join('\n')
    const more = found.length > 15 ? `\n  …and ${found.length - 15} more` : ''
    return {
      deny:
        `nas-rails: commit refused, ${found.length} possible secret(s) in the added lines:\n${list}${more}\n` +
        'Move real values to the vault (`make edit-vault` + secrets.manifest.yaml) or use a placeholder like <NAS_HOST>. ' +
        `If a line is a deliberate false positive, add a \`${ALLOW_MARK}\` comment on it.`,
    }
  }).catch(($, e, next) =>
    next.called || !commitScan(e.command) ? next(e) : { deny: 'nas-rails: the commit secret scan failed to run, so the commit is refused. Run /rails or check `claude --debug`.' },
  )

  on('tool.call', async ($, e, next) => {
    const tool = String(e.tool)
    if (tool === 'Read') return readHook($, e, next)
    if (tool !== 'Edit' && tool !== 'Write' && tool !== 'NotebookEdit') return next(e)
    const r = await repoRoot($)
    if (!r) return next(e)
    const input = e as unknown as { file_path?: string; notebook_path?: string; content?: string; new_string?: string }
    const rel = relOf(r, input.file_path ?? input.notebook_path ?? '')
    const why = pathDeny({ rel, vendored: await vendoredCopies($, r) })
    if (why) return { deny: `nas-rails: ${why}` }

    const ran = await next(e)
    if (ran.deny !== undefined || ran.isError || rel === null) return ran
    touched.add(rel)
    const notes = afterWrite(rel, input.content ?? input.new_string ?? '')
    if (notes.length) $.ui.toast(notes[0]!.replace(/^nas-rails: /, ''), { timeoutMs: 8000 })
    const stack = stackOf(rel, stackSet)
    const ctx = [...notes, ...(stack ? await notesFor($, r, [stack]) : [])]
    return ctx.length ? { ...ran, context: [...(ran.context ?? []), ...ctx] } : ran
  }).catch(failOpen)

  // ── "จบงาน" ────────────────────────────────────────────────────────────────

  on('prompt.submit', async ($, e, next) => {
    const r = await repoRoot($)
    if (!r) return next(e)
    ensureStarted($)
    if (!stackSet.size) stackSet = await stacksOf($, r)
    const named = await notesFor($, r, stacksMentioned(e.text, stackSet))
    if (named.length) e = { ...e, context: [...(e.context ?? []), ...named] }
    if (!e.text.includes('จบงาน')) return next(e)
    await update($, closing, () => true)
    const s = await refresh($)
    if (!s?.notes.length) return next(e)
    const ctx =
      'nas-rails: stacks with work in this tree and the state of their notes ' +
      `(update both <stack>/.notes/daily_log.md and <stack>/.notes/00_INDEX.md before closing): ${s.notes.map(noteLine).join('; ')}`
    return next({ ...e, context: [...(e.context ?? []), ctx] })
  }).catch(failOpen)

  on('turn.complete', async ($, e, next) => {
    const result = await next(e)
    if (!(await repoRoot($))) return result
    ensureStarted($)
    const s = await refresh($)
    if (await read($, closing)) {
      await update($, closing, () => false)
      const left = s ? pendingNotes(s) : []
      if (left.length) $.ui.toast(`จบงาน but notes not updated: ${left.map(noteLine).join(' · ')}`, { timeoutMs: 15_000 })
    }
    return result
  })

  // ── secrets out of the conversation ─────────────────────────────────────────

  on('session.append', async ($, e, next) => {
    if (e.message.type !== 'user' || !(await repoRoot($))) return next(e)
    let hidden = 0
    const scrub = (text: string) => {
      const r = redact(text, secrets)
      hidden += r.hidden
      return r.text
    }
    const content = e.message.content.map(block => {
      if (block.type === 'text' && typeof block.text === 'string' && e.door !== 'prompt') return { ...block, text: scrub(block.text) }
      if (block.type !== 'tool_result') return block
      const c = block.content
      if (typeof c === 'string') return { ...block, content: scrub(c) }
      if (Array.isArray(c)) {
        return { ...block, content: c.map((x: any) => (x?.type === 'text' && typeof x.text === 'string' ? { ...x, text: scrub(x.text) } : x)) }
      }
      return block
    })
    if (!hidden) return next(e)
    $.ui.toast(`nas-rails: hid ${hidden} secret value(s) from a tool result`, { timeoutMs: 5000 })
    return next({ ...e, message: { ...e.message, content } })
  }).catch(failOpen)

  on('session.compact', async ($, e, next) => {
    const result = await next(e)
    // The summary replaces the notes that were in context; let them load again.
    await update($, loadedNotes, () => [])
    return result
  })

  // ── commands ────────────────────────────────────────────────────────────────

  on('command.run', { command: 'deployed' }, async ($, e) => {
    const r = await repoRoot($)
    if (!r) return { text: 'nas-rails: not in the NAS repo.' }
    const stacks = await stacksOf($, r)
    const want = e.args.trim() === 'all' ? [...stacks] : e.args.split(/[\s,]+/).filter(Boolean)
    const unknown = want.filter(s => !stacks.has(s))
    if (!want.length || unknown.length) {
      return { text: `usage: /deployed <stack,stack|all>${unknown.length ? ` (unknown: ${unknown.join(', ')})` : ''}` }
    }
    const sha = await worktreeSha($, r)
    for (const s of want) await git($, r, ['update-ref', `refs/deploy/${s}`, sha])
    await refresh($)
    return { text: `marked ${want.length} stack(s) as deployed from the current worktree (${sha.slice(0, 7)})` }
  })

  on('command.run', { command: 'rails' }, async ($, e) => {
    await update($, isHidden, () => false)
    const s = await refresh($)
    if (!s) return { text: 'nas-rails: not in the NAS repo.' }
    const lines = [
      `notes: ${s.notes.length ? s.notes.map(noteLine).join(' · ') : 'nothing pending'}`,
      `undeployed: ${s.undeployed.length ? s.undeployed.map(([k, n]) => (n === null ? `${k} ?` : k)).join(' · ') : 'none'} (${s.unrecorded} stack(s) without a deploy record — /deployed after a deploy)`,
      `shared drift: ${s.drift.length ? s.drift.map(d => d.dst).join(', ') : 'none'}`,
    ]
    return { text: lines.join('\n') }
  })

  // ── band ────────────────────────────────────────────────────────────────────

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const s = await read($, rails)
    if (e.props.hasSurvey || !s || (await read($, isHidden))) return next(e)
    const und = s.undeployed
    const notes = pendingNotes(s)
    if (!notes.length && !und.length && !s.drift.length) return next(e)
    const { Box, Button, Text } = $.ui.resolve(e)
    return (
      <Box flexDirection="column">
        {notes.length > 0 && (
          <Text wrap="truncate">
            <Text dimColor>notes </Text>
            {notes.map(n => (
              <Text key={n.stack}>
                {n.stack} <Text color={n.log ? 'success' : 'warning'}>{n.log ? '✓' : '✗'}log</Text>{' '}
                <Text color={n.index ? 'success' : 'warning'}>{n.index ? '✓' : '✗'}index</Text>
                {'  '}
              </Text>
            ))}
          </Text>
        )}
        {und.length > 0 && (
          <Text wrap="truncate">
            <Text dimColor>undeployed </Text>
            <Text color="warning">{und.map(([k, n]) => (n === null ? `${k} ?` : k)).join(' · ')}</Text>
            <Text dimColor> changed since last deploy</Text>
          </Text>
        )}
        {s.drift.length > 0 && (
          <Text wrap="truncate">
            <Text color="error">shared drift </Text>
            {s.drift.map(d => d.dst).join(', ')}
            <Text dimColor> → make sync-shared</Text>
          </Text>
        )}
        <Box>
          <Button key="hide" plain label="hide (/rails to show)" onPress={() => update($, isHidden, () => true)} />
        </Box>
      </Box>
    )
  })
}
