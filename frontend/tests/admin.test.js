// D05 admin client tests (EI-UI-6, EI-UI-4, EI-UI-7, FR-4.2..FR-5.4).
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {
  adminHeaders,
  formatMismatchValue,
  isUuidV4,
  newReversalOperation,
  runReconciliation,
  sendReversal,
} from '../src/admin.js';

const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const TXN_ID = '20000000-0000-4000-8000-000000000001';
const CREDS = { token: 'adm-tok', key: 'adm-key' };

function apiError(code, message = 'failed') {
  return Object.assign(new Error(message), { code });
}

test('adminHeaders requires both in-memory credentials and ignores browser storage', () => {
  assert.deepEqual(adminHeaders({ token: ' adm-tok ', key: ' adm-key ' }), {
    Authorization: 'Bearer adm-tok',
    'X-Admin-Key': 'adm-key',
  });
  for (const bad of [{}, { token: 'adm-tok' }, { key: 'adm-key' }, { token: ' ', key: 'k' }]) {
    assert.throws(() => adminHeaders(bad), { code: 'VALIDATION_ERROR' });
  }
});

test('runReconciliation sends unauthenticated-user GET with admin headers and returns report', async () => {
  const calls = [];
  const report = {
    ok: false,
    checks: {
      currencies_balanced: true,
      transactions_valid: true,
      wallet_balances_match: false,
      entry_currencies_match: true,
    },
    mismatches: [
      { check: 'wallet_balances_match', currency: 'INR', expected: 100, actual: 200 },
    ],
  };
  const send = async (path, options) => {
    calls.push({ path, ...options });
    return { data: report, headers: new Headers() };
  };

  const result = await runReconciliation(CREDS, { send });

  assert.deepEqual(result, report);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].path, '/admin/reconcile');
  assert.equal(calls[0].method, 'GET');
  assert.equal(calls[0].authenticated, false);
  assert.deepEqual(calls[0].headers, {
    Authorization: 'Bearer adm-tok',
    'X-Admin-Key': 'adm-key',
  });
});

test('runReconciliation propagates 401 UNAUTHENTICATED', async () => {
  const send = async () => {
    throw apiError('UNAUTHENTICATED', 'Authentication is required.');
  };
  await assert.rejects(runReconciliation(CREDS, { send }), { code: 'UNAUTHENTICATED' });
});

test('newReversalOperation validates UUID v4 and freezes an empty body with unique key', () => {
  assert.equal(isUuidV4(TXN_ID), true);
  assert.equal(isUuidV4('not-a-uuid'), false);
  assert.throws(() => newReversalOperation('not-a-uuid'), { code: 'VALIDATION_ERROR' });

  const first = newReversalOperation(` ${TXN_ID} `);
  const second = newReversalOperation(TXN_ID);
  assert.equal(first.path, `/transactions/${TXN_ID}/reverse`);
  assert.match(first.key, UUID_V4);
  assert.notEqual(first.key, second.key);
  assert.deepEqual(first.body, {});
  assert.ok(Object.isFrozen(first) && Object.isFrozen(first.body));
});

test('sendReversal posts once with Idempotency-Key and surfaces replay header', async () => {
  const calls = [];
  let count = 0;
  const send = async (path, options) => {
    calls.push({ path, ...options });
    count += 1;
    return {
      data: { id: '30000000-0000-4000-8000-000000000001', type: 'REVERSAL' },
      headers: new Headers({ 'Idempotent-Replayed': count === 1 ? 'false' : 'true' }),
    };
  };

  const op = newReversalOperation(TXN_ID);
  const first = await sendReversal(op, CREDS, { send });
  const replay = await sendReversal(op, CREDS, { send });

  assert.equal(first.outcome, 'done');
  assert.equal(first.replayed, false);
  assert.equal(replay.outcome, 'done');
  assert.equal(replay.replayed, true);
  assert.equal(calls.length, 2);
  assert.equal(calls[0].authenticated, false);
  assert.equal(calls[0].method, 'POST');
  assert.equal(calls[0].headers['Idempotency-Key'], op.key);
  assert.equal(calls[1].headers['Idempotency-Key'], op.key);
});

test('sendReversal marks timeouts and 5xx uncertain with no automatic retry', async () => {
  let calls = 0;
  const timedOutSend = (_, { signal }) => new Promise((_resolve, reject) => {
    calls += 1;
    signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
  });

  const op = newReversalOperation(TXN_ID);
  const timedOut = await sendReversal(op, CREDS, { send: timedOutSend, timeoutMs: 20 });
  assert.equal(timedOut.outcome, 'uncertain');
  assert.equal(timedOut.code, 'TIMEOUT');
  assert.equal(calls, 1);

  for (const code of ['DATABASE_BUSY', 'INTERNAL_ERROR']) {
    const res = await sendReversal(op, CREDS, {
      send: async () => {
        throw apiError(code, 'Retry safely');
      },
    });
    assert.equal(res.outcome, 'uncertain');
    assert.equal(res.code, code);
  }
});

for (const code of ['UNAUTHENTICATED', 'NOT_FOUND', 'ALREADY_REVERSED', 'NOT_REVERSIBLE',
  'INSUFFICIENT_FUNDS']) {
  test(`sendReversal classifies ${code} as rejected`, async () => {
    const res = await sendReversal(newReversalOperation(TXN_ID), CREDS, {
      send: async () => {
        throw apiError(code, 'Rejected');
      },
    });
    assert.deepEqual(res, { outcome: 'rejected', code, message: 'Rejected' });
  });
}

test('formatMismatchValue formats primitives and structured balances cleanly', () => {
  assert.equal(formatMismatchValue(null), 'none');
  assert.equal(formatMismatchValue(42), '42');
  assert.equal(
    formatMismatchValue({ debits_minor: 100, credits_minor: 200 }),
    'debits_minor: 100, credits_minor: 200',
  );
});

test('AdminPage and admin helpers never persist credentials in browser storage', () => {
  for (const relPath of ['../src/admin.js', '../src/AdminPage.jsx']) {
    const raw = fs.readFileSync(new URL(relPath, import.meta.url), 'utf8');
    const codeOnly = raw.replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, '');
    assert.equal(/\b(sessionStorage|localStorage)\b/.test(codeOnly), false);
    assert.equal(/ADMIN_TOKEN|ADMIN_KEY/.test(codeOnly), false);
  }
});
