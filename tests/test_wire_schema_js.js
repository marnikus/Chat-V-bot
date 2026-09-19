'use strict';
const assert = require('node:assert/strict');
const test = require('node:test');
const wire = require('../ui/js/wire_schema.js');
const schema = require('../ui/js/wire-schema.json');
wire.use(schema);
test('real artifact methods, types, and callback arity', () => {
  assert.equal(wire.known('history_open'), true);
  assert.equal(wire.known('toString'), false);
  assert.equal(wire.arity('history_open'), 3);
  assert.deepEqual(wire.params('history_open'), ['QString', 'QString', 'QString']);
  assert.equal(wire.check('history_open', ['id', 'nick', '{}', () => {}]), true);
  assert.equal(wire.params('missing'), null);
  assert.equal(wire.arity('missing'), null);
});
test('diagnostics do not suppress calls or lose this', () => {
  wire.reset();
  const bridge = {value: 9, unknown() {return this.value;}, history_open() {return 7;}};
  const guard = wire.guard(bridge);
  assert.equal(guard.unknown(), 9);
  assert.equal(guard.history_open(), 7);
  assert.equal(guard.value, 9);
  assert.equal(wire.problems().length, 2);
  const copy = wire.problems(); copy.length = 0;
  assert.equal(wire.problems().length, 2);
  wire.reset(); assert.deepEqual(wire.problems(), []);
});
test('parity covers every actual method', () => {
  const bridge = Object.fromEntries(Object.keys(schema.methods).map(name => [name, () => {}]));
  assert.deepEqual(wire.parity(bridge), []);
  delete bridge.copy_text;
  assert.deepEqual(wire.parity(bridge), ['copy_text']);
});
test('loader reports HTTP and malformed artifacts', async () => {
  assert.throws(() => wire.use({}), TypeError);
  global.fetch = async () => ({ok: false, status: 404});
  await assert.rejects(wire.load(), /404/);
  global.fetch = async () => ({ok: true, json: async () => schema});
  assert.equal(await wire.load('schema.json'), wire);
  delete global.fetch;
});
