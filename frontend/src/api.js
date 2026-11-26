export const sessionKey = 'ledger.userToken';

export async function api(path, { method = 'GET', body, headers, signal, authenticated = true } = {}) {
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
  const data = await response.json();
  if (!response.ok) {
    const error = new Error(data.error?.message || 'Request failed');
    error.code = data.error?.code || 'HTTP_' + response.status;
    throw error;
  }
  return { data, headers: response.headers };
}
