// B05: send one deposit or transfer with an Idempotency-Key (FR-2.4 to FR-2.9).
//
// Each new operation gets a new UUID key. When the outcome is uncertain (a
// timeout, a lost connection, or a 5xx), the caller keeps the same key and body
// so "Send again with same key" can only replay or finish the same operation,
// never move money twice. Nothing here retries on its own.
import { api } from './api.js';

export const TIMEOUT_MS = 10_000;
const UNCERTAIN_CODES = new Set(['INTERNAL_ERROR', 'DATABASE_BUSY']);

export function newOperation(path, body) {
  return Object.freeze({ path, body: Object.freeze({ ...body }), key: crypto.randomUUID() });
}

// Uncertain: the request may or may not have been applied, so resend with the same key.
// Rejected: the API refused it and stored nothing; fix the form and send a new operation.
export function classifyError(error) {
  const code = error?.code;
  if (!code || UNCERTAIN_CODES.has(code) || /^HTTP_5\d\d$/.test(code)) return 'uncertain';
  return 'rejected';
}

export async function sendOperation(operation, { send = api, timeoutMs = TIMEOUT_MS } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const { data, headers } = await send(operation.path, {
      method: 'POST',
      body: operation.body,
      headers: { 'Idempotency-Key': operation.key },
      signal: controller.signal,
    });
    return { outcome: 'done', data, replayed: headers.get('Idempotent-Replayed') === 'true' };
  } catch (error) {
    const timedOut = controller.signal.aborted;
    return {
      outcome: timedOut ? 'uncertain' : classifyError(error),
      code: timedOut ? 'TIMEOUT' : error?.code || 'NETWORK_ERROR',
      message: timedOut
        ? 'No answer in time. The operation may have gone through.'
        : error?.code ? error.message : 'Could not reach the API.',
    };
  } finally {
    clearTimeout(timer);
  }
}
