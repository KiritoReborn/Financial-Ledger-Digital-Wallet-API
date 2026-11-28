export const sessionKey = 'ledger.userToken';

export async function api(path, {
  method = 'GET', body, headers, signal, authenticated = true, revive,
} = {}) {
  if (!path.startsWith('/') || path.startsWith('//')) throw new Error('Expected an API path');
  const requestHeaders = new Headers(headers);
  if (authenticated && !requestHeaders.has('Authorization')) {
    const token = sessionStorage.getItem(sessionKey);
    if (token) requestHeaders.set('Authorization', 'Bearer ' + token);
  }
  if (body !== undefined) requestHeaders.set('Content-Type', 'application/json');
  const response = await fetch('/api' + path, {
    method, headers: requestHeaders, body: JSON.stringify(body), signal, redirect: 'error',
  });
  const data = JSON.parse(await response.text(), (key, value, context) => {
    // Preserve SQLite int64 balances before JavaScript rounds the JSON number.
    if (key === 'balance_minor' && !Number.isSafeInteger(value)) {
      if (!context?.source) throw new Error('Update your browser to display this balance accurately.');
      return BigInt(context.source);
    }
    return response.ok && revive ? revive(key, value, context) : value;
  });
  if (!response.ok) {
    const error = new Error(data.error?.message || 'Request failed');
    error.code = data.error?.code || 'HTTP_' + response.status;
    throw error;
  }
  return { data, headers: response.headers };
}
