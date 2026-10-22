const assert = require('node:assert/strict');
const Client = require('../examples/js_client/telelogin.js');
const values = new Map();
global.localStorage = {getItem: k => values.get(k) || null, setItem: (k,v) => values.set(k,v), removeItem: k => values.delete(k)};
global.sessionStorage = global.localStorage;
async function main() {
  const client = new Client('http://test');
  client.setToken('old'); client.setRefreshToken('refresh');
  let refreshes = 0;
  global.fetch = async (url, options) => {
    if (url.endsWith('/auth/refresh')) {
      refreshes++;
      await new Promise(resolve => setTimeout(resolve, 10));
      return {ok: true, json: async () => ({session_token:'new',refresh_token:'rotated'})};
    }
    return {status: options.headers.Authorization === 'Bearer new' ? 200 : 401, ok:true, json:async()=>({status:'logged_out'})};
  };
  const responses = await Promise.all(Array.from({length:20}, () => client.authenticatedRequest('/resource')));
  assert(responses.every(r => r.status === 200));
  assert.equal(refreshes, 1);
  await client.refresh('old');
  assert.equal(refreshes, 1);
  client.setToken('old'); client.setRefreshToken('refresh');
  let queue = Promise.resolve();
  Object.defineProperty(globalThis, 'navigator', {value: {locks: {request: (name, run) => {
    assert.equal(name, 'telelogin-refresh');
    const pending = queue.then(run);
    queue = pending.catch(() => {});
    return pending;
  }}}, configurable:true});
  const secondTab = new Client('http://test');
  await Promise.all([client.refresh('old'), secondTab.refresh('old')]);
  assert.equal(refreshes, 2);
  assert.equal(secondTab.getToken(), 'new');
  await client.logout();
  assert.equal(client.getToken(), null);
  assert.equal(localStorage.getItem('telelogin_refresh_token'), null);
  let calls = 0;
  global.fetch = async () => { calls++; throw new Error('Unexpected request'); };
  await assert.rejects(client.authenticatedRequest('/resource'), /Not authenticated. Please login first./);
  assert.equal(calls, 0);

  client.setToken('valid'); client.setRefreshToken('refresh');
  global.fetch = async (url, options) => {
    assert.equal(options.headers['Content-Type'], 'application/json');
    return {status:200};
  };
  await client.authenticatedRequest('/resource');
  global.fetch = async (url, options) => {
    assert.equal(options.headers['Content-Type'], 'text/plain');
    return {status:200};
  };
  await client.authenticatedRequest('/resource', {headers:{'Content-Type':'text/plain'}});

  // The access and refresh tokens have both been revoked on the server.
  const paths = [];
  global.fetch = async (url) => {
    paths.push(url);
    return {status:401, ok:false};
  };
  await assert.rejects(client.logout(), /Refresh failed/);
  assert.deepEqual(paths, ['http://test/auth/logout', 'http://test/auth/refresh']);
  assert.equal(client.getToken(), null);
  assert.equal(localStorage.getItem('telelogin_refresh_token'), null);

  client.setToken('revoked'); client.setRefreshToken('revoked-refresh');
  await assert.rejects(client.refresh(), /Refresh failed/);
  assert.equal(client.getToken(), null);
  assert.equal(localStorage.getItem('telelogin_refresh_token'), null);

  // Even transport errors must not leave local credentials after logout.
  client.setToken('valid'); client.setRefreshToken('refresh');
  global.fetch = async () => { throw new Error('Network failure'); };
  await assert.rejects(client.logoutAll(), /Network failure/);
  assert.equal(client.getToken(), null);
  assert.equal(localStorage.getItem('telelogin_refresh_token'), null);
  // Missing refresh token: tokens cleared, no request sent
  client.setToken('stale'); client.setRefreshToken(null);
  const before = refreshes;
  await assert.rejects(client.refresh('stale'));
  assert.equal(refreshes, before);
  assert.equal(client.getToken(), null);
  console.log('Client proof passed: headers, missing-token guard, revoked-session logout, refresh cleanup, and transport failure; 20 parallel requests, one refresh; changed storage skips refresh; Web Locks coordinates tabs; logout clears both tokens.');
}
main().catch(error => { console.error(error); process.exitCode=1; });
