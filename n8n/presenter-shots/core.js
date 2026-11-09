'use strict';
// Presenter Shots — pure state machine for multi-shot Flow presenter clips.
// Embedded verbatim into the n8n Code nodes by build_workflow.py; tested with `node --test`.
// No I/O, no clock: every function takes nowMs. apply() never mutates its input.

const PACING_MS = 300 * 1000;          // Flow reCAPTCHA: >= 5 min between any two submits
const MAX_SHOTS = 8;
const PRUNE_MS = 14 * 24 * 3600 * 1000;
const STALL = {                         // first alert after N ms, then hourly
  submit_unconfirmed: 10 * 60 * 1000,
  render_slow: 45 * 60 * 1000,
  job_idle: 30 * 60 * 1000,
};
const REPEAT_MS = 60 * 60 * 1000;
const JOB_RE = /^[a-z0-9][a-z0-9-]{0,40}$/;

function emptyState() {
  return { jobs: {}, last_submit_at: null, test_last_submit_at: null };
}

const clone = (o) => JSON.parse(JSON.stringify(o));
const iso = (ms) => new Date(ms).toISOString();
const ok = (state, body) => ({ state, code: 200, body: Object.assign({ ok: true }, body) });
const fail = (state, code, error, extra) => ({ state, code, body: Object.assign({ ok: false, error }, extra || {}) });
const isTest = (job) => job.startsWith('test-');

function shotNo(job, ev) {
  const n = Number(ev.shot);
  if (!Number.isInteger(n) || n < 1 || n > job.shots_total) return null;
  return String(n);
}

function apply(state0, ev, nowMs) {
  const state = clone(state0 || emptyState());
  if (!state.jobs) Object.assign(state, emptyState());
  ev = ev || {};
  const now = iso(nowMs);
  const act = ev.action;

  if (act === 'status') {
    if (ev.job) {
      const j = state.jobs[ev.job];
      return j ? ok(state, { job: j, last_submit_at: state.last_submit_at }) : fail(state, 404, 'no such job');
    }
    const open = {};
    for (const [k, j] of Object.entries(state.jobs)) if (!j.closed) open[k] = j;
    return ok(state, { jobs: open, last_submit_at: state.last_submit_at });
  }

  if (act === 'create_job') {
    const name = String(ev.job || '');
    if (!JOB_RE.test(name)) return fail(state, 400, 'job must match ' + JOB_RE);
    const total = Number(ev.shots_total);
    if (!Number.isInteger(total) || total < 1 || total > MAX_SHOTS) return fail(state, 400, `shots_total must be 1..${MAX_SHOTS}`);
    const product = String(ev.product || '').slice(0, 200);
    if (!product) return fail(state, 400, 'product required');
    if (state.jobs[name] && !state.jobs[name].closed) return fail(state, 409, 'job already open');
    for (const [k, j] of Object.entries(state.jobs)) {
      if (j.closed && nowMs - Date.parse(j.updated_at) > PRUNE_MS) delete state.jobs[k];
    }
    const shots = {};
    for (let i = 1; i <= total; i++) shots[String(i)] = { status: 'pending', attempt: 0, history: [] };
    state.jobs[name] = {
      job: name, product, link: String(ev.link || '').slice(0, 300), shots_total: total,
      created_at: now, updated_at: now, closed: false, shots,
    };
    return ok(state, { job: state.jobs[name] });
  }

  const KNOWN = ['reserve', 'submitted', 'submit_failed', 'ready', 'decide', 'assemble_check', 'close', 'cancel'];
  if (!KNOWN.includes(act)) return fail(state, 400, 'unknown action');
  const job = state.jobs[String(ev.job || '')];
  if (!job) return fail(state, 404, 'no such job');

  if (act === 'assemble_check') {
    const bad = Object.entries(job.shots).filter(([, s]) => s.status !== 'approved').map(([k, s]) => `${k}:${s.status}`);
    if (bad.length) return fail(state, 409, 'not every shot is approved', { pending: bad });
    const files = Object.keys(job.shots).sort((a, b) => a - b).map((k) => job.shots[k].file);
    return ok(state, { job, files });
  }
  if (act === 'close' || act === 'cancel') {
    job.closed = act === 'close' ? 'done' : 'cancelled';
    job.close_note = String(ev.sha256 || ev.reason || '').slice(0, 200);
    job.updated_at = now;
    return ok(state, { job });
  }
  if (job.closed) return fail(state, 409, 'job is closed');

  const k = shotNo(job, ev);
  if (!k) return fail(state, 400, `shot must be 1..${job.shots_total}`);
  const sh = job.shots[k];
  const log = (what, extra) => sh.history.push(Object.assign({ at: now, what }, extra || {}));
  const touch = () => { job.updated_at = now; };

  if (act === 'reserve') {
    if (!(sh.status === 'pending' || sh.status === 'regen_approved')) {
      const why = sh.status === 'in_review' || sh.status === 'failed'
        ? 'a new attempt needs Fix regen decision (credits)' : `shot is ${sh.status}`;
      return fail(state, 409, why, { status: sh.status });
    }
    if (Number(k) > 1) {
      const prev = job.shots[String(Number(k) - 1)];
      if (!(prev.status === 'in_review' || prev.status === 'approved')) {
        return fail(state, 409, `shot ${Number(k) - 1} must be rendered first (start-frame chaining)`, { prev_status: prev.status });
      }
    }
    const clockKey = isTest(job.job) ? 'test_last_submit_at' : 'last_submit_at';
    const last = state[clockKey] ? Date.parse(state[clockKey]) : null;
    if (last !== null && nowMs - last < PACING_MS) {
      return fail(state, 429, 'pacing: wait before the next Flow submit', { wait_s: Math.ceil((PACING_MS - (nowMs - last)) / 1000) });
    }
    sh.prev_status = sh.status;
    sh.status = 'submitting';
    sh.attempt += 1;
    sh.reserved_at = now;
    state[clockKey] = now;
    log('reserve', { attempt: sh.attempt });
    touch();
    return ok(state, { job, shot: k, attempt: sh.attempt });
  }

  if (act === 'submitted') {
    if (sh.status !== 'submitting') return fail(state, 409, 'reserve the shot first', { status: sh.status });
    sh.status = 'submitted';
    sh.edit_id = String(ev.edit_id || '').slice(0, 80);
    sh.submitted_at = now;
    log('submitted', { edit_id: sh.edit_id });
    touch();
    return ok(state, { job, shot: k });
  }

  if (act === 'submit_failed') {
    if (!(sh.status === 'submitting' || sh.status === 'submitted')) return fail(state, 409, 'nothing in flight', { status: sh.status });
    const reason = String(ev.reason || '').slice(0, 200);
    if (ev.credits_spent === true) {
      sh.status = 'failed';
    } else {
      sh.status = sh.prev_status || 'pending';
      sh.attempt = Math.max(0, sh.attempt - 1);
    }
    log('submit_failed', { reason, credits_spent: ev.credits_spent === true });
    touch();
    return ok(state, { job, shot: k });
  }

  if (act === 'ready') {
    if (sh.status !== 'submitted') return fail(state, 409, 'shot was not submitted', { status: sh.status });
    const file = String(ev.file || '');
    if (!file) return fail(state, 400, 'file required');
    const gates = ev.gates && typeof ev.gates === 'object' ? ev.gates : {};
    if (JSON.stringify(gates).length > 4000) return fail(state, 400, 'gates too large');
    sh.status = 'in_review';
    sh.file = file.slice(0, 300);
    sh.pass = ev.pass === true;
    sh.gates = gates;
    sh.ready_at = now;
    log('ready', { pass: sh.pass });
    touch();
    return ok(state, { job, shot: k });
  }

  if (act === 'decide') {
    const d = ev.decision;
    if (d !== 'approve' && d !== 'regen') return fail(state, 400, 'decision must be approve|regen');
    if (!(sh.status === 'in_review' || (sh.status === 'failed' && d === 'regen'))) {
      return fail(state, 409, 'shot is not waiting for a decision', { status: sh.status });
    }
    sh.status = d === 'approve' ? 'approved' : 'regen_approved';
    sh.decided_at = now;
    log('decide', { decision: d, by: String(ev.by || '').slice(0, 40) });
    touch();
    return ok(state, { job, shot: k });
  }
  return fail(state, 400, 'unknown action');
}

// Read-only: alerts whose threshold (or an hourly repeat of it) was crossed inside the last tick.
function stalls(state, nowMs, tickMs) {
  const out = [];
  const fires = (sinceIso, threshold) => {
    if (!sinceIso) return false;
    const age = nowMs - Date.parse(sinceIso);
    if (age < threshold) return false;
    return (age - threshold) % REPEAT_MS < tickMs;
  };
  const mins = (sinceIso) => Math.round((nowMs - Date.parse(sinceIso)) / 60000);
  for (const j of Object.values((state && state.jobs) || {})) {
    if (j.closed) continue;
    const shots = Object.entries(j.shots);
    for (const [k, s] of shots) {
      if (s.status === 'submitting' && fires(s.reserved_at, STALL.submit_unconfirmed)) {
        out.push({ job: j.job, shot: k, kind: 'submit_unconfirmed',
          text: `⏰ ${j.product}: ช็อต ${k} จองคิว submit ไว้ ${mins(s.reserved_at)} นาทีแล้วแต่ยังไม่ยืนยันว่าส่ง Flow สำเร็จ` });
      }
      if (s.status === 'submitted' && fires(s.submitted_at, STALL.render_slow)) {
        out.push({ job: j.job, shot: k, kind: 'render_slow',
          text: `⏰ ${j.product}: ช็อต ${k} ส่ง Flow ไป ${mins(s.submitted_at)} นาทีแล้วยังไม่มีผล (edit ${s.edit_id || '-'})` });
      }
    }
    const busy = shots.some(([, s]) => ['submitting', 'submitted', 'in_review'].includes(s.status));
    if (!busy && fires(j.updated_at, STALL.job_idle)) {
      const allDone = shots.every(([, s]) => s.status === 'approved');
      out.push({ job: j.job, shot: null, kind: allDone ? 'assemble_pending' : 'job_idle',
        text: allDone
          ? `⏰ ${j.product}: ผ่านครบทุกช็อตแล้ว ${mins(j.updated_at)} นาที แต่ยังไม่ประกอบคลิป`
          : `⏰ ${j.product}: งานนิ่งมา ${mins(j.updated_at)} นาที ยังมีช็อตที่ยังไม่ได้ส่ง (${shots.filter(([, s]) => s.status !== 'approved').map(([n]) => n).join(', ')})` });
    }
  }
  return out;
}

module.exports = { apply, stalls, emptyState, PACING_MS };
