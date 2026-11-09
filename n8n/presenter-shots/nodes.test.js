'use strict';
// Runs the generated Code-node sources with n8n-shaped globals, so the wrapper
// (auth, static data persistence, read-only tick) is tested, not just core.js.
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const wf = require(path.join(__dirname, '..', 'workflows', 'Presenter_Shots.json'));
const code = Object.fromEntries(wf.nodes.filter((n) => n.type.endsWith('.code')).map((n) => [n.name, n.parameters.jsCode]));

function runNode(name, { json, env, sd }) {
  const fn = new Function('$input', '$env', '$getWorkflowStaticData', 'require', 'Buffer', code[name]);
  return fn({ first: () => ({ json }) }, env, () => sd, require, Buffer);
}
const ENV = { CLIP_INTAKE_TOKEN: 'tok-123' };

test('Apply event rejects a missing / wrong token and an empty env', () => {
  const sd = {};
  assert.equal(runNode('Apply event', { json: { headers: {}, body: { action: 'status' } }, env: ENV, sd })[0].json.code, 401);
  assert.equal(runNode('Apply event', { json: { headers: { 'x-clip-token': 'nope' }, body: {} }, env: ENV, sd })[0].json.code, 401);
  assert.equal(runNode('Apply event', { json: { headers: { 'x-clip-token': '' }, body: {} }, env: {}, sd })[0].json.code, 401);
  assert.equal(sd.state, undefined);
});

test('Apply event persists accepted events and leaves rejected ones out', () => {
  const sd = {};
  const h = { 'x-clip-token': 'tok-123' };
  let r = runNode('Apply event', { json: { headers: h, body: { action: 'create_job', job: 'test-a', product: 'p', shots_total: 2 } }, env: ENV, sd });
  assert.equal(r[0].json.code, 200);
  assert.ok(sd.state.jobs['test-a']);
  const snap = JSON.stringify(sd.state);
  r = runNode('Apply event', { json: { headers: h, body: { action: 'reserve', job: 'test-a', shot: 2 } }, env: ENV, sd });
  assert.equal(r[0].json.code, 409);
  assert.equal(JSON.stringify(sd.state), snap);
});

test('Find stalls returns items and does not write static data', () => {
  const old = new Date(Date.now() - 46 * 60 * 1000).toISOString();
  const state = { jobs: { j: { job: 'j', product: 'P', closed: false, updated_at: old, shots_total: 1,
    shots: { 1: { status: 'submitted', submitted_at: old, edit_id: 'e', history: [] } } } } };
  const sd = { state };
  const snap = JSON.stringify(sd);
  const out = runNode('Find stalls', { json: {}, env: ENV, sd });
  assert.equal(out.length, 1);
  assert.equal(out[0].json.kind, 'render_slow');
  assert.equal(JSON.stringify(sd), snap);
});
