import test from 'node:test';
import assert from 'node:assert/strict';
import { api } from '../src/api.js';

test('forwards user credentials and operation key once and preserves the replay header', async t => {
  globalThis.sessionStorage = {getItem: () => 'test-user'};
  const send = t.mock.method(globalThis, 'fetch', async (url, options) => {
    assert.equal(url, '/api/transfers');
    assert.equal(options.headers.get('Authorization'), 'Bearer test-user');
    assert.equal(options.headers.get('Idempotency-Key'), 'test-operation');
    assert.equal(options.body, '{"amount_minor":42}');
    return Response.json({ok:true}, {headers:{'Idempotent-Replayed':'true'}});
  });
  const response = await api('/transfers',{method:'POST', body:{amount_minor:42}, headers:{'Idempotency-Key':'test-operation'}});
  assert.equal(response.headers.get('Idempotent-Replayed'), 'true');
  assert.equal(send.mock.callCount(), 1);
});

test('public requests omit the user credential and surface API errors', async t => {
  t.mock.method(globalThis, 'fetch', async (_, options) => {
    assert.equal(options.headers.has('Authorization'), false);
    return Response.json({error:{code:'VALIDATION_ERROR', message:'Invalid field'}}, {status:422});
  });
  await assert.rejects(api('/users', {authenticated:false}), {code:'VALIDATION_ERROR',message:'Invalid field'});
});
