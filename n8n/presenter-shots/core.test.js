'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const core = require('./core.js');

const T0 = Date.parse('2026-11-09T10:00:00Z');
const MIN = 60 * 1000;

function run(state, ev, now = T0) {
  const r = core.apply(state, ev, now);
  return r;
}
function fresh(shots = 3, job = 'vacbag-1') {
  const r = run(core.emptyState(), { action: 'create_job', job, product: 'Vacuum bag', shots_total: shots });
  assert.equal(r.code, 200, JSON.stringify(r.body));
  return r.state;
}
// drive shot `n` from pending to in_review
function toReview(state, job, n, now) {
  let r = run(state, { action: 'reserve', job, shot: n }, now);
  assert.equal(r.code, 200, JSON.stringify(r.body));
  r = run(r.state, { action: 'submitted', job, shot: n, edit_id: `e${n}` }, now + 1000);
  assert.equal(r.code, 200, JSON.stringify(r.body));
  r = run(r.state, { action: 'ready', job, shot: n, file: `/x/s${n}.mp4`, pass: true, gates: { probe: 'ok' } }, now + 20 * MIN);
  assert.equal(r.code, 200, JSON.stringify(r.body));
  return r.state;
}

test('create_job validates and rejects a duplicate open job', () => {
  let s = fresh();
  assert.equal(s.jobs['vacbag-1'].shots_total, 3);
  assert.equal(s.jobs['vacbag-1'].shots['1'].status, 'pending');
  const dup = run(s, { action: 'create_job', job: 'vacbag-1', product: 'x', shots_total: 3 });
  assert.equal(dup.code, 409);
  assert.equal(run(core.emptyState(), { action: 'create_job', job: 'Bad Name!', product: 'x', shots_total: 3 }).code, 400);
  assert.equal(run(core.emptyState(), { action: 'create_job', job: 'ok', product: 'x', shots_total: 9 }).code, 400);
});

test('unknown action is a 400, unknown job is a 404', () => {
  assert.equal(run(core.emptyState(), { action: 'nope' }).code, 400);
  assert.equal(run(core.emptyState(), { action: 'reserve', job: 'ghost', shot: 1 }).code, 404);
});

test('reserve enforces 300 s pacing across jobs', () => {
  let s = fresh(3, 'a');
  s = run(s, { action: 'create_job', job: 'b', product: 'y', shots_total: 2 }).state;
  let r = run(s, { action: 'reserve', job: 'a', shot: 1 }, T0);
  assert.equal(r.code, 200);
  const early = run(r.state, { action: 'reserve', job: 'b', shot: 1 }, T0 + 2 * MIN);
  assert.equal(early.code, 429);
  assert.equal(early.body.wait_s, 180);
  const later = run(r.state, { action: 'reserve', job: 'b', shot: 1 }, T0 + 5 * MIN);
  assert.equal(later.code, 200);
});

test('test-* jobs use their own pacing clock', () => {
  let s = fresh(2, 'real');
  s = run(s, { action: 'reserve', job: 'real', shot: 1 }, T0).state;
  s = run(s, { action: 'create_job', job: 'test-x', product: 'p', shots_total: 2 }).state;
  assert.equal(run(s, { action: 'reserve', job: 'test-x', shot: 1 }, T0 + MIN).code, 200);
});

test('shot k>1 needs shot k-1 rendered (in_review or approved)', () => {
  let s = fresh();
  assert.equal(run(s, { action: 'reserve', job: 'vacbag-1', shot: 2 }).code, 409);
  s = toReview(s, 'vacbag-1', 1, T0);
  assert.equal(run(s, { action: 'reserve', job: 'vacbag-1', shot: 2 }, T0 + 30 * MIN).code, 200);
});

test('a second attempt needs Fix regen decision (credit guard)', () => {
  let s = fresh();
  s = toReview(s, 'vacbag-1', 1, T0);
  assert.equal(run(s, { action: 'reserve', job: 'vacbag-1', shot: 1 }, T0 + 30 * MIN).code, 409);
  s = run(s, { action: 'decide', job: 'vacbag-1', shot: 1, decision: 'regen', by: 'Fix' }, T0 + 31 * MIN).state;
  assert.equal(s.jobs['vacbag-1'].shots['1'].status, 'regen_approved');
  const r = run(s, { action: 'reserve', job: 'vacbag-1', shot: 1 }, T0 + 32 * MIN);
  assert.equal(r.code, 200);
  assert.equal(r.state.jobs['vacbag-1'].shots['1'].attempt, 2);
});

test('submit_failed without credits reverts the reservation but keeps pacing', () => {
  let s = fresh();
  s = run(s, { action: 'reserve', job: 'vacbag-1', shot: 1 }, T0).state;
  const r = run(s, { action: 'submit_failed', job: 'vacbag-1', shot: 1, reason: 'unusual activity', credits_spent: false }, T0 + MIN);
  assert.equal(r.code, 200);
  const sh = r.state.jobs['vacbag-1'].shots['1'];
  assert.equal(sh.status, 'pending');
  assert.equal(sh.attempt, 0);
  assert.equal(run(r.state, { action: 'reserve', job: 'vacbag-1', shot: 1 }, T0 + 2 * MIN).code, 429);
});

test('submit_failed that spent credits counts as an attempt and needs a regen decision', () => {
  let s = fresh();
  s = run(s, { action: 'reserve', job: 'vacbag-1', shot: 1 }, T0).state;
  s = run(s, { action: 'submitted', job: 'vacbag-1', shot: 1, edit_id: 'e1' }, T0).state;
  const r = run(s, { action: 'submit_failed', job: 'vacbag-1', shot: 1, reason: 'Failed card', credits_spent: true }, T0 + 20 * MIN);
  assert.equal(r.code, 200);
  assert.equal(r.state.jobs['vacbag-1'].shots['1'].status, 'failed');
  assert.equal(run(r.state, { action: 'reserve', job: 'vacbag-1', shot: 1 }, T0 + 30 * MIN).code, 409);
});

test('ready requires submitted; decide requires in_review', () => {
  let s = fresh();
  assert.equal(run(s, { action: 'ready', job: 'vacbag-1', shot: 1, file: '/x', pass: true, gates: {} }).code, 409);
  assert.equal(run(s, { action: 'decide', job: 'vacbag-1', shot: 1, decision: 'approve' }).code, 409);
  s = toReview(s, 'vacbag-1', 1, T0);
  assert.equal(s.jobs['vacbag-1'].shots['1'].status, 'in_review');
  assert.equal(run(s, { action: 'decide', job: 'vacbag-1', shot: 1, decision: 'maybe' }).code, 400);
});

test('assemble_check passes only when every shot is approved', () => {
  let s = fresh(2);
  s = toReview(s, 'vacbag-1', 1, T0);
  s = run(s, { action: 'decide', job: 'vacbag-1', shot: 1, decision: 'approve' }, T0 + 21 * MIN).state;
  assert.equal(run(s, { action: 'assemble_check', job: 'vacbag-1' }, T0 + 21 * MIN).code, 409);
  s = toReview(s, 'vacbag-1', 2, T0 + 25 * MIN);
  s = run(s, { action: 'decide', job: 'vacbag-1', shot: 2, decision: 'approve' }, T0 + 50 * MIN).state;
  const r = run(s, { action: 'assemble_check', job: 'vacbag-1' }, T0 + 50 * MIN);
  assert.equal(r.code, 200);
  assert.deepEqual(r.body.files, ['/x/s1.mp4', '/x/s2.mp4']);
});

test('close and cancel end the job; a closed job name can be reused', () => {
  let s = fresh(1);
  s = run(s, { action: 'cancel', job: 'vacbag-1', reason: 'Fix stopped' }).state;
  assert.equal(s.jobs['vacbag-1'].closed, 'cancelled');
  assert.equal(run(s, { action: 'reserve', job: 'vacbag-1', shot: 1 }).code, 409);
  assert.equal(run(s, { action: 'create_job', job: 'vacbag-1', product: 'again', shots_total: 1 }).code, 200);
});

test('status lists open jobs only', () => {
  let s = fresh(1, 'a');
  s = run(s, { action: 'create_job', job: 'b', product: 'y', shots_total: 1 }).state;
  s = run(s, { action: 'cancel', job: 'b' }).state;
  const r = run(s, { action: 'status' });
  assert.deepEqual(Object.keys(r.body.jobs), ['a']);
  assert.equal(run(s, { action: 'status', job: 'b' }).body.job.closed, 'cancelled');
});

test('stalls: submitted too long fires once inside one tick window, read-only', () => {
  let s = fresh();
  s = run(s, { action: 'reserve', job: 'vacbag-1', shot: 1 }, T0).state;
  s = run(s, { action: 'submitted', job: 'vacbag-1', shot: 1, edit_id: 'e1' }, T0).state;
  const before = JSON.stringify(s);
  const tick = 5 * MIN;
  assert.equal(core.stalls(s, T0 + 44 * MIN, tick).length, 0);
  const hits = core.stalls(s, T0 + 47 * MIN, tick);
  assert.equal(hits.length, 1);
  assert.equal(hits[0].kind, 'render_slow');
  assert.equal(core.stalls(s, T0 + 52 * MIN, tick).length, 0);
  assert.equal(core.stalls(s, T0 + 107 * MIN, tick).length, 1); // hourly reminder
  assert.equal(JSON.stringify(s), before);
});

test('stalls: reservation never confirmed, and an idle job with pending shots', () => {
  let s = fresh(2);
  s = run(s, { action: 'reserve', job: 'vacbag-1', shot: 1 }, T0).state;
  const k = core.stalls(s, T0 + 12 * MIN, 5 * MIN).map((x) => x.kind);
  assert.deepEqual(k, ['submit_unconfirmed']);
  let t = fresh(2, 'idle');
  t = toReview(t, 'idle', 1, T0);
  t = run(t, { action: 'decide', job: 'idle', shot: 1, decision: 'approve' }, T0 + 21 * MIN).state;
  const kinds = core.stalls(t, T0 + 21 * MIN + 32 * MIN, 5 * MIN).map((x) => x.kind);
  assert.deepEqual(kinds, ['job_idle']);
});

test('in_review waiting on Fix never alerts', () => {
  let s = fresh(1);
  s = toReview(s, 'vacbag-1', 1, T0);
  for (let m = 0; m < 300; m += 5) assert.equal(core.stalls(s, T0 + m * MIN, 5 * MIN).length, 0);
});
