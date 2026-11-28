import assert from 'node:assert/strict';
import test from 'node:test';
import { createTransferPair, getHistoryPage, reviveHistoryId, sendTransferPair } from '../src/ledger-demo.js';

test('keeps 64-bit entry IDs and cursors exact without changing the amount', () => {
  const page = JSON.parse(
    '{"entries":[{"id":9223372036854775807,"amount_minor":3000}],"next_before_id":9223372036854775807}',
    reviveHistoryId,
  );
  assert.deepEqual(page, {
    entries: [{ id: '9223372036854775807', amount_minor: 3000 }],
    next_before_id: '9223372036854775807',
  });
  assert.equal(JSON.parse('{"next_before_id":null}', reviveHistoryId).next_before_id, null);
});

test('sends the exact exclusive cursor to the shared authenticated API', async t => {
  const walletId = '9835957e-f576-41a3-ae3c-d90f540c8de4';
  const controller = new AbortController();
  const originalStorage = Object.getOwnPropertyDescriptor(globalThis, 'sessionStorage');
  Object.defineProperty(globalThis, 'sessionStorage', {
    configurable: true,
    value: { getItem: () => 'test-token' },
  });
  t.after(() => {
    if (originalStorage) Object.defineProperty(globalThis, 'sessionStorage', originalStorage);
    else delete globalThis.sessionStorage;
  });
  t.mock.method(globalThis, 'fetch', async (path, options) => {
    assert.equal(path, `/api/wallets/${walletId}/transactions?limit=20&before_id=9223372036854775807`);
    assert.equal(options.signal, controller.signal);
    assert.equal(options.headers.get('Authorization'), 'Bearer test-token');
    return new Response('{"entries":[],"next_before_id":null}');
  });
  assert.deepEqual(await getHistoryPage(walletId, '9223372036854775807', controller.signal), {
    entries: [], next_before_id: null,
  });
});

test('sends two independent operations and retries only the uncertain one with its original key', async () => {
  const body = { amount_minor: 3000 };
  const pair = createTransferPair(body);
  assert.notEqual(pair[0].operation.key, pair[1].operation.key);
  const inFlight = [];
  const resolve = [];
  const firstRun = sendTransferPair(pair, operation => new Promise(done => {
    inFlight.push(operation);
    resolve.push(done);
  }));
  assert.deepEqual(inFlight, pair.map(attempt => attempt.operation));
  resolve[1]({ outcome: 'uncertain' });
  resolve[0]({ outcome: 'done' });
  const first = await firstRun;

  const second = await sendTransferPair(first, async operation => {
    assert.equal(operation, pair[1].operation);
    return { outcome: 'done', replayed: true };
  });
  assert.equal(second[0], first[0]);
  assert.equal(second[1].result.replayed, true);
});
