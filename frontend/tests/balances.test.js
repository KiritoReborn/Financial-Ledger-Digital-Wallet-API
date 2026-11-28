import test from 'node:test';
import assert from 'node:assert/strict';
import { formatMinor } from '../src/money.js';
import { api } from '../src/api.js';

test('formats wallet minor units without rounding int64 JSON balances', async t => {
  t.mock.method(globalThis, 'fetch', async () => new Response('{"balance_minor":9223372036854775807}'));
  const { data } = await api('/wallets', { authenticated: false });
  assert.equal(formatMinor(data.balance_minor, 'USD'), '92233720368547758.07');
  assert.equal(formatMinor(-1, 'INR'), '-0.01');
  assert.equal(formatMinor(501, 'JPY'), '501');
});
