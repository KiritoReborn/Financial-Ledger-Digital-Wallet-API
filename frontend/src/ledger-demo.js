import { api } from './api.js';
import { newOperation, sendOperation } from './operation.js';

export const UUID4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export function reviveHistoryId(key, value, context) {
  if ((key !== 'id' && key !== 'next_before_id') || typeof value !== 'number') return value;
  // SQLite entry IDs may exceed JavaScript's safe integer range.
  const exact = context?.source ?? (Number.isSafeInteger(value) ? String(value) : '');
  if (!/^[1-9]\d*$/.test(exact)) throw new Error('Invalid wallet history cursor.');
  return exact;
}

export async function getHistoryPage(walletId, beforeId, signal) {
  const query = new URLSearchParams({ limit: '20' });
  if (beforeId !== null) query.set('before_id', beforeId);
  const { data } = await api(`/wallets/${encodeURIComponent(walletId)}/transactions?${query}`, {
    signal,
    revive: reviveHistoryId,
  });
  return data;
}

export function createTransferPair(body) {
  return [
    { operation: newOperation('/transfers', body), result: null },
    { operation: newOperation('/transfers', body), result: null },
  ];
}

export function sendTransferPair(attempts, send = sendOperation) {
  return Promise.all(attempts.map(async attempt => {
    if (attempt.result && attempt.result.outcome !== 'uncertain') return attempt;
    return { ...attempt, result: await send(attempt.operation) };
  }));
}
