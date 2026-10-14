// Pure rules: no `$`, so `claude plugin test` covers them without an engine.

// ── shell parsing ─────────────────────────────────────────────────────────────

// Heredoc bodies are data (commit messages, files being written), never commands.
const HEREDOC = /<<-?\s*(['"]?)(\w+)\1[^\n]*\n[\s\S]*?\n[ \t]*\2[ \t]*(?=\n|$)/g

/** Splits a shell command into simple commands, each a list of words, quotes honoured. */
export function segments(command: string): string[][] {
  const text = command.replace(HEREDOC, m => m.slice(0, m.indexOf('\n')))
  const out: string[][] = []
  let words: string[] = []
  let word = ''
  let hasWord = false
  let quote: '"' | "'" | null = null
  const endWord = () => {
    if (hasWord) words.push(word)
    word = ''
    hasWord = false
  }
  const endSegment = () => {
    endWord()
    if (words.length) out.push(words)
    words = []
  }
  for (let i = 0; i < text.length; i++) {
    const c = text[i]
    if (quote) {
      if (c === quote) quote = null
      else if (c === '\\' && quote === '"' && i + 1 < text.length) word += text[++i]
      else word += c
      continue
    }
    if (c === '"' || c === "'") {
      quote = c
      hasWord = true
    } else if (c === '\\' && i + 1 < text.length) {
      word += text[++i]
      hasWord = true
    } else if (c === ' ' || c === '\t') {
      endWord()
    } else if (c === ';' || c === '|' || c === '&' || c === '\n' || c === '(' || c === ')' || c === '`') {
      endSegment()
    } else if (c === '$' && text[i + 1] === '(') {
      endSegment()
      i++
    } else {
      word += c
      hasWord = true
    }
  }
  endSegment()
  return out
}

const WRAPPERS = new Set(['env', 'sudo', 'command', 'time', 'nohup', 'exec', 'xargs'])

/** The program a simple command runs and its arguments, wrappers stripped; `bash -c` recursed. */
export function programs(command: string, depth = 0): { prog: string; args: string[] }[] {
  const out: { prog: string; args: string[] }[] = []
  for (const seg of segments(command)) {
    let i = 0
    while (i < seg.length) {
      const w = seg[i]!
      if (/^[A-Za-z_][A-Za-z0-9_]*=/.test(w)) i++
      else if (WRAPPERS.has(w)) i++
      else if (w === 'rtk' && seg[i + 1] === 'proxy') i += 2
      else if (w === 'rtk') i++
      else break
    }
    if (i >= seg.length) continue
    let prog = seg[i]!
    let args = seg.slice(i + 1)
    if ((prog === 'bash' || prog === 'sh' || prog === 'zsh') && args.length) {
      const c = args.findIndex(a => /^-[a-z]*c$/.test(a))
      const inner = c >= 0 ? args[c + 1] : undefined
      if (inner !== undefined && depth < 3) {
        out.push(...programs(inner, depth + 1))
        continue
      }
      const script = args.findIndex(a => !a.startsWith('-'))
      if (script < 0) continue
      prog = args[script]!
      args = args.slice(script + 1)
    }
    out.push({ prog, args })
  }
  return out
}

const base = (p: string) => p.slice(p.lastIndexOf('/') + 1)

/** `git -C x -c k=v <sub> ...` → `{ sub, args }`. */
function gitSub(args: string[]): { sub: string; args: string[] } | null {
  let i = 0
  while (i < args.length) {
    const a = args[i]!
    if (a === '-C' || a === '-c') i += 2
    else if (a.startsWith('-')) i++
    else return { sub: a, args: args.slice(i + 1) }
  }
  return null
}

// ── Bash guard ────────────────────────────────────────────────────────────────

const SECRET_FILE = /(^|\/)(\.env|\.env\.deploy|secrets\/vault\.yaml)$/
const CLAUDE_COAUTHOR = /co-authored-by:[^\n]*\b(claude|anthropic)\b/i

export type CommitScan = { includeWorktree: boolean }

/** A reason to refuse a Bash command, or null. */
export function bashDeny(command: string): string | null {
  for (const { prog, args } of programs(command)) {
    const name = base(prog)
    if (name === 'rsync') {
      return 'rsync is banned in this repo: macOS openrsync (protocol 29) and Synology GNU rsync (protocol 31) do not talk. Use `tar | ssh` (see CLAUDE.md).'
    }
    if (name === 'deploy.sh') {
      const ok = args.some(a => a === '-y' || a === '--yes' || a === '-h' || a === '--help' || a === '--restart-only')
      if (!ok) {
        return 'deploy.sh without -y: with no TTY the upload prompt is skipped silently and the script still exits 0. Re-run with `-y`.'
      }
    }
    if (name === 'git') {
      const g = gitSub(args)
      if (g?.sub === 'add') {
        const bad = g.args.filter(a => !a.startsWith('-') && SECRET_FILE.test(a))
        if (bad.length) {
          return `refusing to stage ${bad.join(', ')}: plaintext secrets stay out of git (only secrets/vault.sops.yaml is committed).`
        }
      }
      if (g?.sub === 'commit' && CLAUDE_COAUTHOR.test(command)) {
        return 'commit message carries a Claude/Anthropic Co-Authored-By trailer; the user forbids it. Drop the trailer.'
      }
    }
  }
  return null
}

/** Whether the command commits, and whether the commit takes worktree changes past the index. */
export function commitScan(command: string): CommitScan | null {
  for (const { prog, args } of programs(command)) {
    if (base(prog) !== 'git') continue
    const g = gitSub(args)
    if (g?.sub !== 'commit') continue
    const VALUED = new Set(['-m', '-F', '-C', '-c', '-t', '--author', '--date', '--fixup', '--squash', '--message', '--file', '--template'])
    let includeWorktree = false
    for (let i = 0; i < g.args.length; i++) {
      const a = g.args[i]!
      if (VALUED.has(a)) i++
      else if (a === '--all' || a === '--include' || a === '--only') includeWorktree = true
      else if (/^-[A-Za-z]+$/.test(a) && a.includes('a')) includeWorktree = true
      else if (!a.startsWith('-')) includeWorktree = true
    }
    return { includeWorktree }
  }
  return null
}

// ── Edit/Write guard ──────────────────────────────────────────────────────────

export type PathFacts = {
  /** Path relative to the repo root, `/`-separated; null when outside the repo. */
  rel: string | null
  /** Tracked vendored copies of shared/*.py, repo-relative. */
  vendored: ReadonlySet<string>
}

export const MOD_DIR = '.claude/skills/nas-rails/'

/** A reason to refuse writing this file, or null. */
export function pathDeny({ rel, vendored }: PathFacts): string | null {
  if (rel === null || rel.startsWith(MOD_DIR)) return null
  if (rel.startsWith('.notes/')) {
    return 'root .notes/ is off limits: write to <stack>/.notes/daily_log.md and <stack>/.notes/00_INDEX.md of the stack you worked in.'
  }
  if (/^secrets\/.*\.sops\.yaml$/.test(rel)) {
    return `${rel} is sops-encrypted: edit it with \`make edit-vault\` (or \`sops set\`), never directly.`
  }
  if (vendored.has(rel)) {
    return `${rel} is a vendored copy of shared/${base(rel)}: edit shared/${base(rel)}, then \`make sync-shared\`.`
  }
  return null
}

/** Reminders the model should read after a write lands, by path and new text. */
export function afterWrite(rel: string | null, text: string): string[] {
  if (rel === null) return []
  const out: string[] = []
  if (/^shared\/(?!test_)[^/]+\.py$/.test(rel)) {
    out.push(`nas-rails: ${rel} changed. Run \`make sync-shared\` before testing or committing, or tests/test_shared_sync.py goes red.`)
  }
  if (/(^|\/)secrets\.manifest\.yaml$/.test(rel)) {
    out.push('nas-rails: secrets.manifest.yaml changed. Run `make check`: an `env:` key whose vault path does not exist yet breaks `make secrets` for every stack.')
  }
  if (/(^|\/)docker-compose\.ya?ml$/.test(rel) && /^\s*cpus\s*:/m.test(text)) {
    out.push('nas-rails: `cpus:` is a no-op on DSM (no CFS bandwidth control). Cap CPU inside the workload (e.g. ffmpeg -threads); `mem_limit` works.')
  }
  return out
}

/** The top-level directory a repo path belongs to, if it is a stack. */
export function stackOf(rel: string, stacks: ReadonlySet<string>): string | null {
  const top = rel.split('/')[0]!
  return stacks.has(top) ? top : null
}

// ── git status → notes ────────────────────────────────────────────────────────

/** Paths `git status --porcelain -z` names (renames give the new path). */
export function statusPaths(porcelainZ: string): string[] {
  const parts = porcelainZ.split('\0')
  const out: string[] = []
  for (let i = 0; i < parts.length; i++) {
    const p = parts[i]!
    if (p.length < 4) continue
    const xy = p.slice(0, 2)
    out.push(p.slice(3))
    if (xy.includes('R') || xy.includes('C')) i++
  }
  return out
}

export type NotesRow = { stack: string; log: boolean; index: boolean }

/** Stacks with work and whether their two notes files have been touched too. */
export function notesRows(changed: Iterable<string>, stacks: ReadonlySet<string>): NotesRow[] {
  const work = new Set<string>()
  const log = new Set<string>()
  const index = new Set<string>()
  for (const rel of changed) {
    const s = stackOf(rel, stacks)
    if (!s) continue
    if (rel === `${s}/.notes/daily_log.md`) log.add(s)
    else if (rel === `${s}/.notes/00_INDEX.md`) index.add(s)
    else if (!rel.startsWith(`${s}/.notes/`)) work.add(s)
  }
  return [...work].sort().map(stack => ({ stack, log: log.has(stack), index: index.has(stack) }))
}

// ── deploy records ────────────────────────────────────────────────────────────

/** `git for-each-ref refs/deploy --format='%(refname:lstrip=2) %(objectname)'` → stack → sha. */
export function deployRefs(out: string): Map<string, string> {
  const m = new Map<string, string>()
  for (const line of out.split('\n')) {
    const [stack, sha] = line.trim().split(' ')
    if (stack && sha) m.set(stack, sha)
  }
  return m
}

/**
 * Stacks whose files differ between what was deployed and HEAD. `changed` maps
 * each recorded sha to `git diff --name-only <sha> HEAD`, or null when git
 * could not read it.
 */
export function undeployed(records: ReadonlyMap<string, string>, changed: ReadonlyMap<string, string[] | null>): [string, boolean | null][] {
  const out: [string, boolean | null][] = []
  for (const [stack, sha] of [...records].sort()) {
    const files = changed.get(sha)
    if (files === null || files === undefined) out.push([stack, null])
    else if (files.some(f => f.startsWith(`${stack}/`))) out.push([stack, true])
  }
  return out
}

// ── commit secret scan ────────────────────────────────────────────────────────

export type Finding = { file: string; line: number; rule: string; hint: string }

const TOKENS: [string, RegExp][] = [
  ['anthropic-key', /sk-ant-[A-Za-z0-9_-]{20,}/],
  ['openrouter-key', /sk-or-v1-[A-Fa-f0-9]{40,}/],
  ['api-key', /\bsk-[A-Za-z0-9]{32,}\b/],
  ['github-token', /\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})/],
  ['telegram-bot-token', /\b\d{8,10}:[A-Za-z0-9_-]{35}\b/],
  ['aws-key', /\bAKIA[0-9A-Z]{16}\b/],
  ['slack-token', /\bxox[baprs]-[A-Za-z0-9-]{10,}/],
  ['google-api-key', /\bAIza[0-9A-Za-z_-]{35}\b/],
  ['private-key', /-----BEGIN [A-Z ]*PRIVATE KEY-----/],
  ['age-secret-key', /AGE-SECRET-KEY-1[0-9A-Z]{50,}/],
]

// A LAN host address; network/broadcast addresses (subnets in docs) and CIDR are fine.
const LAN_IP = /(?<![\d.])(192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3})(?![\d.]|\/\d)/g

const ASSIGN = /\b([A-Z][A-Z0-9_]*(?:PASSWORD|PASSWD|SECRET|TOKEN|API_KEY|ACCESS_KEY))(?:=|\s*:\s*)["']?([^\s"'#,;`)\]]+)/
const PLACEHOLDER = /^(\$|<|\{\{|%|\*|abc)|\.\.\.|…|example|change.?me|placeholder|your[_-]|xxx|dummy|fake|redacted|replace|random|secret_here|^(none|null|true|false)$/i
// secrets.manifest.yaml maps env keys to vault paths (`stacks.x.y`), not values.
// Lower-case dotted names are vault paths or code (`settings.token`), not values.
const VAULT_PATH = /^[a-z_][a-z0-9_-]*(\.[a-z0-9_-]+)+$/
const SKIP_FILE = /(\.sops\.ya?ml|\.lock|package-lock\.json|\.min\.js|\.svg|\.png|\.jpe?g|\.woff2?)$/
const TEST_FILE = /(^|\/)(tests?\/|test_[^/]*$|[^/]*_test\.[a-z]+$|[^/]*\.test\.[a-z]+$)/

export const ALLOW_MARK = 'secrets-ok'

const mask = (s: string) => `${s.slice(0, 4)}…(${s.length} chars)`

/** Secrets in the added lines of a unified diff. Values are masked in the result. */
export function scanDiff(diff: string): Finding[] {
  const out: Finding[] = []
  let file = ''
  let line = 0
  for (const raw of diff.split('\n')) {
    if (raw.startsWith('+++ ')) {
      file = raw.startsWith('+++ b/') ? raw.slice(6) : ''
      continue
    }
    const hunk = /^@@ -\d+(?:,\d+)? \+(\d+)/.exec(raw)
    if (hunk) {
      line = Number(hunk[1])
      continue
    }
    if (!file || SKIP_FILE.test(file)) continue
    if (raw.startsWith('+')) {
      const text = raw.slice(1)
      if (!text.includes(ALLOW_MARK)) {
        for (const [rule, re] of TOKENS) {
          const m = re.exec(text)
          if (m) out.push({ file, line, rule, hint: mask(m[0]) })
        }
        for (const m of TEST_FILE.test(file) ? [] : text.matchAll(LAN_IP)) {
          const ip = m[1]!
          const last = Number(ip.split('.')[3])
          if (last !== 0 && last !== 255) out.push({ file, line, rule: 'lan-ip', hint: ip.replace(/\.\d+$/, '.x') })
        }
        const a = ASSIGN.exec(text)
        const [, key = '', value = ''] = a ?? []
        if (a && key !== 'NOPASSWD' && !TEST_FILE.test(file) && value.length >= 8 && !PLACEHOLDER.test(value) && !VAULT_PATH.test(value) && !/[()[\]{}]/.test(value)) {
          out.push({ file, line, rule: `hardcoded ${key}`, hint: mask(value) })
        }
      }
      line++
    } else if (!raw.startsWith('-') && !raw.startsWith('\\')) {
      line++
    }
  }
  return out
}

// ── stack notes in context ────────────────────────────────────────────────────

/** Stacks named as whole words in a prompt, in the order first named. */
export function stacksMentioned(text: string, stacks: ReadonlySet<string>): string[] {
  const out: string[] = []
  for (const m of text.toLowerCase().matchAll(/[a-z0-9][a-z0-9-]*[a-z0-9]/g)) {
    if (stacks.has(m[0]) && !out.includes(m[0])) out.push(m[0])
  }
  return out
}

export const NOTES_CAP = 16_000

/** The context block carrying a stack's 00_INDEX.md, its head when long. */
export function notesContext(stack: string, index: string): string {
  const path = `${stack}/.notes/00_INDEX.md`
  const head = index.length > NOTES_CAP ? `${index.slice(0, NOTES_CAP)}\n\n[… ${index.length - NOTES_CAP} more characters: Read ${path} for the rest]` : index
  return `nas-rails: ${path} (the stack's memory, loaded because this work touches ${stack}):\n\n${head}`
}

// ── secret redaction ──────────────────────────────────────────────────────────

const SECRET_KEY = /(KEY|TOKEN|SECRET|PASSWORD|PASSWD|PASS|CREDENTIALS?|_B64|COOKIE|HTPASSWD|WEBHOOK_URL)$/

export type Secret = { key: string; value: string }

/** Secret-named values of a dotenv file, long enough to be worth hiding. */
export function secretsFromEnv(text: string): Secret[] {
  const out: Secret[] = []
  for (const line of text.split('\n')) {
    const m = /^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=\s*(.*)$/.exec(line)
    if (!m) continue
    const key = m[1]!
    let value = m[2]!.trim()
    if (/^(['"]).*\1$/.test(value)) value = value.slice(1, -1)
    // A path (NAS_SSH_KEY=~/.ssh/id_ed25519) names a secret, it is not one.
    if (SECRET_KEY.test(key) && value.length >= 8 && !/^[~/]/.test(value)) out.push({ key, value })
  }
  return out
}

/** Replaces known secret values and token-shaped strings; counts what it hid. */
export function redact(text: string, secrets: readonly Secret[]): { text: string; hidden: number } {
  let hidden = 0
  let out = text
  for (const { key, value } of secrets) {
    if (!out.includes(value)) continue
    const parts = out.split(value)
    hidden += parts.length - 1
    out = parts.join(`«SECRET:${key}»`)
  }
  for (const [rule, re] of TOKENS) {
    out = out.replace(new RegExp(re.source, 'g'), () => {
      hidden++
      return `«REDACTED:${rule}»`
    })
  }
  return { text: out, hidden }
}

// ── NAS commands ──────────────────────────────────────────────────────────────

const SSH_VALUED = new Set(['-p', '-i', '-o', '-l', '-F', '-J', '-L', '-R', '-D', '-c', '-m', '-E', '-b', '-e', '-S', '-W', '-O', '-Q', '-B', '-I', '-w'])

/** The remote command of an `ssh` invocation, or null when it opens a shell. */
function sshRemote(args: string[]): string | null {
  let i = 0
  while (i < args.length && args[i]!.startsWith('-')) i += SSH_VALUED.has(args[i]!) ? 2 : 1
  const rest = args.slice(i + 1)
  return rest.length ? rest.join(' ') : null
}

const POWER = new Set(['reboot', 'poweroff', 'shutdown', 'halt'])

const DANGER: [string, RegExp][] = [
  ['synopkg stop/restart', /\bsynopkg\s+(restart|stop|uninstall)\b/],
  ['docker prune', /\bdocker\s+(system|volume|image|container|network|builder)\s+prune\b/],
  ['docker volume rm', /\bdocker\s+volume\s+rm\b/],
  ['rm -r under /volume', /\brm\s+(-[a-zA-Z]*\s+)*-[a-zA-Z]*r[a-zA-Z]*\s+(\S+\s+)*['"]?\/volume\d/],
  ['compose down -v', /\bcompose\b[^;&|]*\bdown\b[^;&|]*(\s-v\b|--volumes)/],
  ['synoshare --del', /\bsynoshare\s+--del\b/],
  ['disk tools', /\b(mkfs(\.\w+)?|fdisk|parted)\b|\bdd\b[^;|]*\bof=/],
  ['router network restart', /\b(restart_net_and_phy|restart_wireless|service\s+reboot)\b/],
]

export type NasRisk = {
  /** Destructive remote operations: each needs the person's yes. */
  danger: string[]
  /** compose up/down/restart run straight on the NAS, past deploy.sh's ops-bot window. */
  composeDirect: boolean
  /** The command (re)starts n8n, whose data volume holds the credentials key. */
  startsN8n: boolean
}

export function nasRisk(command: string): NasRisk {
  const risk: NasRisk = { danger: [], composeDirect: false, startsN8n: false }
  for (const { prog, args } of programs(command)) {
    const name = base(prog)
    if (name === 'ssh') {
      const remote = sshRemote(args)
      if (!remote) continue
      // Power commands count only as the program run (not `grep reboot-notifier`).
      if (programs(remote).some(p => POWER.has(base(p.prog))) && !risk.danger.includes('reboot/shutdown')) risk.danger.push('reboot/shutdown')
      for (const [label, re] of DANGER) if (re.test(remote) && !risk.danger.includes(label)) risk.danger.push(label)
      if (/\bcompose\b[^;&|]*\b(up|down|restart|stop)\b/.test(remote)) risk.composeDirect = true
      if (/\bcompose\b[^;&|]*\bn8n\b[^;&|]*\b(up|restart|start)\b/.test(remote) || /\bdocker\s+(start|restart)\s+n8n\b/.test(remote)) {
        risk.startsN8n = true
      }
    }
    if (name === 'deploy.sh' && !args.includes('--upload-only')) {
      const at = args.findIndex(a => a === '-s' || a === '--stacks')
      const value = at >= 0 ? (args[at + 1] ?? '') : (args.find(a => a.startsWith('--stacks='))?.slice(9) ?? '')
      if (value.split(',').some(s => s.trim() === 'n8n' || s.trim() === 'all')) risk.startsN8n = true
    }
  }
  return risk
}
