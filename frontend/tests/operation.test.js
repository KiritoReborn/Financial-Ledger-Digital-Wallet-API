// B05: one deposit or transfer with an Idempotency-Key (FR-2.4 to FR-2.9).
import test from 'node:test';
import assert from 'node:assert/strict';
import { classifyError, newOperation, sendOperation } from '../src/operation.js';

const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

function apiError(code, message = 'failed') {
  return Object.assign(new Error(message), { code });
}

function replying(replayed, data = { id: 'txn' }) {
  const calls = [];
  const send = async (path, options) => {
    calls.push({ path, ...options });
    return { data, headers: new Headers({ 'Idempotent-Replayed': String(replayed) }) };
  };
  return { send, calls };
}

test('each new operation gets its own UUID v4 key and a frozen body', () => {
  const first = newOperation('/transfers', { amount_minor: 1 });
  const second = newOperation('/transfers', { amount_minor: 1 });
  assert.match(first.key, UUID_V4);
  assert.notEqual(first.key, second.key);
  assert.ok(Object.isFrozen(first) && Object.isFrozen(first.body));
});

test('sends one POST with the key header and reports the result', async () => {
  const { send, calls } = replying(false);
  const operation = newOperation('/transfers', { amount_minor: 42 });

  const result = await sendOperation(operation, { send });

  assert.deepEqual(result, { outcome: 'done', data: { id: 'txn' }, replayed: false });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].path, '/transfers');
  assert.equal(calls[0].method, 'POST');
  assert.deepEqual(calls[0].body, { amount_minor: 42 });
  assert.deepEqual(calls[0].headers, { 'Idempotency-Key': operation.key });
});

test('sending the same operation again reuses its key and shows the replay', async () => {
  const { send, calls } = replying(true);
  const operation = newOperation('/wallets/w/deposit', { amount_minor: 5 });

  await sendOperation(operation, { send });
  const again = await sendOperation(operation, { send });

  assert.equal(again.replayed, true);
  assert.equal(calls[0].headers['Idempotency-Key'], calls[1].headers['Idempotency-Key']);
  assert.deepEqual(calls[0].body, calls[1].body);
});

test('a timeout is uncertain and is never retried automatically', async () => {
  let calls = 0;
  const send = (_, { signal }) => new Promise((_resolve, reject) => {
    calls += 1;
    signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
  });

  const result = await sendOperation(newOperation('/transfers', {}), { send, timeoutMs: 20 });

  assert.equal(result.outcome, 'uncertain');
  assert.equal(result.code, 'TIMEOUT');
  assert.match(result.message, /may have gone through/);
  assert.equal(calls, 1);
});

test('a lost connection is uncertain', async () => {
  const send = async () => { throw new TypeError('Failed to fetch'); };
  const result = await sendOperation(newOperation('/transfers', {}), { send });
  assert.deepEqual(result, { outcome: 'uncertain', code: 'NETWORK_ERROR',
    message: 'Could not reach the API.' });
});

for (const code of ['INTERNAL_ERROR', 'DATABASE_BUSY', 'HTTP_502', 'HTTP_504', undefined]) {
  test(`${code ?? 'an unreadable response'} is uncertain`, () => {
    assert.equal(classifyError(code ? apiError(code) : new SyntaxError('bad json')), 'uncertain');
  });
}

for (const code of ['INSUFFICIENT_FUNDS', 'CURRENCY_MISMATCH', 'VALIDATION_ERROR', 'FORBIDDEN',
  'NOT_FOUND', 'UNAUTHENTICATED', 'IDEMPOTENCY_CONFLICT', 'IDEMPOTENCY_KEY_MISSING', 'HTTP_429']) {
  test(`${code} is a definite rejection`, async () => {
    const send = async () => { throw apiError(code, 'Balance is too low.'); };
    const result = await sendOperation(newOperation('/transfers', {}), { send });
    assert.deepEqual(result, { outcome: 'rejected', code, message: 'Balance is too low.' });
  });
}
