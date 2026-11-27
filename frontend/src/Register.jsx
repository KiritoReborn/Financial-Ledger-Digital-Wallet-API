import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from './api.js';

export default function Register() {
  const [token, setToken] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [copyStatus, setCopyStatus] = useState('');

  async function register(event) {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    setPending(true);
    setError('');
    try {
      const { data } = await api('/users', {
        method: 'POST', authenticated: false,
        body: { name: fields.get('name').trim(), email: fields.get('email').trim() },
      });
      setToken(data.token);
    } catch (err) {
      setError([err.code, err.message].filter(Boolean).join(' · '));
    } finally {
      setPending(false);
    }
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(token);
      setCopyStatus('Token copied.');
    } catch {
      setCopyStatus('Select the token and copy it manually.');
    }
  }

  if (token) return <section>
    <h1>Save your access token</h1>
    <p>This token is shown once. Save it somewhere private before leaving this page.</p>
    <label>Access token<input readOnly value={token} onFocus={event => event.target.select()} /></label>
    <button onClick={copy}>Copy token</button>
    <p role="status">{copyStatus}</p>
    <Link to="/sign-in">Continue to sign in</Link>
  </section>;

  return <section><h1>Register</h1>
    <form onSubmit={register}>
      <label>Name<input name="name" autoComplete="name" required /></label>
      <label>Email<input type="email" name="email" autoComplete="email" required /></label>
      <button disabled={pending}>{pending ? 'Registering…' : 'Register'}</button>
    </form>
    {error && <p role="alert">{error}</p>}
    <Link to="/sign-in">Sign in with a token</Link>
  </section>;
}
