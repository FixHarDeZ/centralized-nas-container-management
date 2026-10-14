import { describe, expect, test } from 'claude-code/testing'

import { afterWrite, bashDeny, commitScan, notesRows, pathDeny, scanDiff, statusPaths, deployRefs, undeployed } from '../hooks/rules'

describe('bashDeny', () => {
  const denied = [
    'rsync -avz . nas:/volume2/docker/',
    'cd /tmp && rsync -n a b',
    'rtk proxy rsync -a x y',
    './scripts/deploy.sh -s torrentwatch',
    'bash scripts/deploy.sh -s all',
    'bash -c "./scripts/deploy.sh -s homepage"',
    'git add .env',
    'git add news-feed/.env .env.deploy',
    'git -C repo add secrets/vault.yaml',
    `git commit -m "$(cat <<'EOF'\nfix: x\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>\nEOF\n)"`,
  ]
  for (const cmd of denied) test(`denies: ${cmd.split('\n')[0]}`, () => expect(bashDeny(cmd)).not.toBe(null))

  // Commands this repo's sessions really run, which mention the banned words as data.
  const allowed = [
    'grep -n "ALL_STACKS\\|getopts\\|-y\\|-s)\\|restart" scripts/deploy.sh | head -50',
    'sed -n 280,363p scripts/deploy.sh',
    'rtk proxy sed -n 280,363p scripts/deploy.sh',
    'grep rsync CLAUDE.md',
    'git commit -m "docs: never use rsync; use tar | ssh"',
    './scripts/deploy.sh -s torrentwatch -y',
    'scripts/deploy.sh --restart-only -s all',
    'scripts/deploy.sh --help',
    `cat > notes.md <<'EOF'\nrsync -a x y\n./scripts/deploy.sh -s all\nEOF`,
    'git add .env.example news-feed/app/main.py',
    'git add -A',
    `git commit -m "$(cat <<'EOF'\nfeat: x\n\nCo-Authored-By: Someone <a@b.c>\nEOF\n)"`,
    'ssh nas "bash -lc \\"docker ps | grep n8n\\""',
  ]
  for (const cmd of allowed) test(`allows: ${cmd.split('\n')[0]}`, () => expect(bashDeny(cmd)).toBe(null))
})

describe('commitScan', () => {
  test('plain commit reads the index only', () => expect(commitScan('git commit -m "x -a"')).toEqual({ includeWorktree: false }))
  test('-am takes the worktree', () => expect(commitScan('git commit -am "x"')).toEqual({ includeWorktree: true }))
  test('paths take the worktree', () => expect(commitScan('git commit -m x -- a.py')).toEqual({ includeWorktree: true }))
  test('--amend is not -a', () => expect(commitScan('git commit --amend --no-edit')).toEqual({ includeWorktree: false }))
  test('not a commit', () => expect(commitScan('git log --oneline')).toBe(null))
})

describe('pathDeny', () => {
  const vendored = new Set(['shorts-factory/app/mimo.py', 'torrentwatch/notify.py'])
  test('root .notes', () => expect(pathDeny({ rel: '.notes/daily_log.md', vendored })).not.toBe(null))
  test('stack .notes ok', () => expect(pathDeny({ rel: 'torrentwatch/.notes/daily_log.md', vendored })).toBe(null))
  test('vault', () => expect(pathDeny({ rel: 'secrets/vault.sops.yaml', vendored })).not.toBe(null))
  test('vendored copy', () => expect(pathDeny({ rel: 'torrentwatch/notify.py', vendored })).not.toBe(null))
  test('shared source ok', () => expect(pathDeny({ rel: 'shared/notify.py', vendored })).toBe(null))
  test('outside repo ok', () => expect(pathDeny({ rel: null, vendored })).toBe(null))
  test('own folder ok', () => expect(pathDeny({ rel: '.claude/skills/nas-rails/.notes/x', vendored })).toBe(null))
})

describe('afterWrite', () => {
  test('shared source', () => expect(afterWrite('shared/mimo.py', '')).toHaveLength(1))
  test('shared test file', () => expect(afterWrite('shared/test_mimo.py', '')).toHaveLength(0))
  test('manifest', () => expect(afterWrite('ops-bot/secrets.manifest.yaml', '')).toHaveLength(1))
  test('cpus', () => expect(afterWrite('x/docker-compose.yml', '    cpus: 2.0\n')).toHaveLength(1))
  test('mem_limit only', () => expect(afterWrite('x/docker-compose.yml', '    mem_limit: 2g\n')).toHaveLength(0))
})

describe('notes and deploy', () => {
  const stacks = new Set(['torrentwatch', 'hermes-agent', 'ops-bot'])
  test('status -z with a rename', () =>
    expect(statusPaths(' M a.txt\0R  new.txt\0old.txt\0?? b/c.md\0')).toEqual(['a.txt', 'new.txt', 'b/c.md']))
  test('rows', () =>
    expect(
      notesRows(
        ['torrentwatch/app.py', 'torrentwatch/.notes/daily_log.md', 'hermes-agent/.notes/00_INDEX.md', 'README.md', 'ops-bot/.notes/daily_log.md'],
        stacks,
      ),
    ).toEqual([{ stack: 'torrentwatch', log: true, index: false }]))
  test('deploy refs', () =>
    expect([...deployRefs('ops-bot abc\ntorrentwatch def\n')]).toEqual([['ops-bot', 'abc'], ['torrentwatch', 'def']]))
  test('undeployed = files under the stack changed since its sha', () => {
    const records = new Map([['torrentwatch', 's1'], ['ops-bot', 's1'], ['hermes-agent', 's2']])
    const changed = new Map<string, string[] | null>([['s1', ['torrentwatch/a.py', 'README.md']], ['s2', null]])
    expect(undeployed(records, changed)).toEqual([['hermes-agent', null], ['torrentwatch', true]])
  })
})

describe('scanDiff', () => {
  const diff = (file: string, ...lines: string[]) => `+++ b/${file}\n@@ -0,0 +1,${lines.length} @@\n${lines.map(l => `+${l}`).join('\n')}\n`
  test('telegram token, masked', () => {
    const tok = '1234567890:AAEhBP0av28bL2fDqZzxyAbCdEfGhIjKlMn'
    const f = scanDiff(diff('a/config.py', `BOT = "${tok}"`))
    expect(f.map(x => x.rule)).toEqual(['telegram-bot-token'])
    expect(f[0]!.hint).not.toContain(tok.slice(5))
  })
  test('lan ip, not subnets or CIDR', () => {
    expect(scanDiff(diff('README.md', 'open http://192.168.1.20:5000')).map(x => x.rule)).toEqual(['lan-ip'])
    expect(scanDiff(diff('CLAUDE.md', 'allow 192.168.0.0/255.255.0.0 and 10.0.0.0/8 and 192.168.1.0/24'))).toEqual([])
  })
  test('hardcoded password', () =>
    expect(scanDiff(diff('x/compose.yml', 'DB_PASSWORD=hunter2hunter2')).map(x => x.rule)).toEqual(['hardcoded DB_PASSWORD']))
  test('placeholders and vault paths pass', () =>
    expect(
      scanDiff(diff('x/secrets.manifest.yaml', 'TG_TOKEN: stacks.ops_bot.telegram.token', 'PASSWORD=<NAS_SUDO_PASSWORD>', 'API_KEY=${API_KEY}', 'TOKEN=sk-or-...')),
    ).toEqual([]))
  test('allow mark', () => expect(scanDiff(diff('a.md', 'see 192.168.1.20  # secrets-ok'))).toEqual([]))
  test('sops file skipped', () => expect(scanDiff(diff('secrets/vault.sops.yaml', 'k: sk-ant-api03-aaaaaaaaaaaaaaaaaaaaaaaaaaaa'))).toEqual([]))
  test('removed lines ignored', () => expect(scanDiff('+++ b/a.md\n@@ -1 +1 @@\n-ip 192.168.1.20\n+ip <NAS_HOST>\n')).toEqual([]))
  test('line numbers', () => expect(scanDiff('+++ b/a.md\n@@ -9,0 +10,2 @@\n+ok\n+ip 192.168.1.20\n')[0]!.line).toBe(11))
})

import { nasRisk, notesContext, NOTES_CAP, redact, secretsFromEnv, stacksMentioned } from '../hooks/rules'

describe('stacksMentioned', () => {
  const stacks = new Set(['n8n', 'torrentwatch', 'ai-deck', 'homepage'])
  test('words only, in order', () => expect(stacksMentioned('แก้ TorrentWatch แล้วดู ai-deck กับ n8n-ish', stacks)).toEqual(['torrentwatch', 'ai-deck']))
  test('notes capped with a pointer', () => {
    const c = notesContext('x', 'a'.repeat(NOTES_CAP + 50))
    expect(c).toContain('Read x/.notes/00_INDEX.md')
    expect(c.length).toBeLessThan(NOTES_CAP + 300)
  })
})

describe('redaction', () => {
  const env = 'MIMO_API_KEY=tp-abcdefghijklmnop\nSSH_PORT=2222\nNAS_SUDO_PASSWORD="hunter2hunter2"\nTELEGRAM_CHAT_ID=123456789\nSHORT_TOKEN=abc\n'
  const secrets = secretsFromEnv(env)
  test('picks secret-named, long values', () => expect(secrets.map(s => s.key)).toEqual(['MIMO_API_KEY', 'NAS_SUDO_PASSWORD']))
  test('replaces values and token shapes', () => {
    const r = redact('key=tp-abcdefghijklmnop pw hunter2hunter2 gh ghp_abcdefghijklmnopqrstuvwxyz0123456789', secrets)
    expect(r.text).toBe('key=«SECRET:MIMO_API_KEY» pw «SECRET:NAS_SUDO_PASSWORD» gh «REDACTED:github-token»')
    expect(r.hidden).toBe(3)
  })
  test('nothing to hide', () => expect(redact('plain text 2222', secrets)).toEqual({ text: 'plain text 2222', hidden: 0 }))
})

describe('nasRisk', () => {
  const r = (c: string) => nasRisk(c)
  test('reboot over ssh', () => expect(r('ssh nas "sudo reboot"').danger).toEqual(['reboot/shutdown']))
  test('synopkg restart', () => expect(r("ssh -p 2222 nas 'sudo synopkg restart ContainerManager'").danger).toEqual(['synopkg stop/restart']))
  test('prune', () => expect(r('ssh nas "sudo -n /usr/local/bin/docker system prune -af"').danger).toEqual(['docker prune']))
  test('rm -rf under volume', () => expect(r('ssh nas "rm -rf /volume2/docker/n8n"').danger).toEqual(['rm -r under /volume']))
  test('compose down -v', () => expect(r('ssh nas "docker compose -f x.yml down -v"').danger).toEqual(['compose down -v']))
  test('read-only ssh is clean', () => {
    const x = r('ssh nas "sudo -n /usr/local/bin/docker ps --format {{.Names}} | grep reboot-notifier; ls /volume2/docker"')
    expect(x.danger).toEqual([])
    expect(x.composeDirect).toBe(false)
  })
  test('local grep for reboot is clean', () => expect(r('grep -rn reboot ops-bot/').danger).toEqual([]))
  test('direct compose up', () => expect(r('ssh nas "cd /volume2/docker/ops-bot && sudo docker compose up -d"').composeDirect).toBe(true))
  test('deploy n8n', () => expect(r('./scripts/deploy.sh -s homepage,n8n -y').startsN8n).toBe(true))
  test('deploy all', () => expect(r('./scripts/deploy.sh -s all -y').startsN8n).toBe(true))
  test('deploy other', () => expect(r('./scripts/deploy.sh -s homepage -y').startsN8n).toBe(false))
  test('upload only', () => expect(r('./scripts/deploy.sh --upload-only -s all -y').startsN8n).toBe(false))
  test('compose n8n up over ssh', () => expect(r('ssh nas "docker compose -f /volume2/docker/n8n/docker-compose.yml up -d"').startsN8n).toBe(true))
})
