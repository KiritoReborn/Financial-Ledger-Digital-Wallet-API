// D05 admin client helpers (EI-UI-6, EI-UI-4, EI-UI-7, FR-4.2..FR-5.4).
// Credentials stay strictly in memory (passed per call) and never touch
// sessionStorage, localStorage, or bundled assets.
import { api } from './api.js';
import { TIMEOUT_MS, classifyError } from './operation.js';

export const UUID_V4_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export const RECONCILE_CHECKS = Object.freeze([
  Object.freeze({
    key: 'currencies_balanced',
    label: 'Currency debits equal credits',
  }),
  Object.freeze({
    key: 'transactions_valid',
    label: 'Every transaction has 1 debit + 1 credit in 1 currency',
  }),
  Object.freeze({
    key: 'wallet_balances_match',
    label: 'Wallet cached balances match ledger entries',
  }),
  Object.freeze({
    key: 'entry_currencies_match',
    label: 'Ledger entry currencies match wallet currencies',
  }),
]);

export function isUuidV4(value) {
  return typeof value === 'string' && UUID_V4_PATTERN.test(value.trim());
}

export function adminHeaders(credentials) {
  const token = typeof credentials?.token === 'string' ? credentials.token.trim() : '';
  const key = typeof credentials?.key === 'string' ? credentials.key.trim() : '';
  if (!token || !key) {
    const error = new Error('Both Admin bearer token and X-Admin-Key are required.');
    error.code = 'VALIDATION_ERROR';
    throw error;
  }
  return {
    Authorization: 'Bearer ' + token,
    'X-Admin-Key': key,
  };
}

export async function runReconciliation(credentials, { send = api, signal } = {}) {
  const { data } = await send('/admin/reconcile', {
    method: 'GET',
    authenticated: false,
    headers: adminHeaders(credentials),
    signal,
  });
  return data;
}

export function newReversalOperation(txnId) {
  const id = typeof txnId === 'string' ? txnId.trim() : '';
  if (!isUuidV4(id)) {
    const error = new Error('Enter a valid UUID v4 transaction ID.');
    error.code = 'VALIDATION_ERROR';
    throw error;
  }
  return Object.freeze({
    path: `/transactions/${id}/reverse`,
    txnId: id,
    body: Object.freeze({}),
    key: crypto.randomUUID(),
  });
}

export async function sendReversal(
  operation,
  credentials,
  { send = api, timeoutMs = TIMEOUT_MS } = {},
) {
  const headers = {
    ...adminHeaders(credentials),
    'Idempotency-Key': operation.key,
  };
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const { data, headers: responseHeaders } = await send(operation.path, {
      method: 'POST',
      authenticated: false,
      body: operation.body,
      headers,
      signal: controller.signal,
    });
    return {
      outcome: 'done',
      data,
      replayed: responseHeaders.get('Idempotent-Replayed') === 'true',
    };
  } catch (error) {
    const timedOut = controller.signal.aborted;
    return {
      outcome: timedOut ? 'uncertain' : classifyError(error),
      code: timedOut ? 'TIMEOUT' : error?.code || 'NETWORK_ERROR',
      message: timedOut
        ? 'No answer in time. The reversal may have gone through.'
        : error?.code ? error.message : 'Could not reach the API.',
    };
  } finally {
    clearTimeout(timer);
  }
}

export function formatMismatchValue(value) {
  if (value === null || value === undefined) return 'none';
  if (typeof value === 'object') {
    return Object.entries(value)
      .map(([k, v]) => `${k}: ${v}`)
      .join(', ');
  }
  return String(value);
}
