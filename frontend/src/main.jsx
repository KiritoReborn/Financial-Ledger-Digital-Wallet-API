import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, Link, NavLink, Navigate, Outlet, Route, Routes, useNavigate } from 'react-router-dom';
import { api, sessionKey } from './api.js';
import { DepositPage, TransferPage } from './MoneyPages.jsx';
import Register from './Register.jsx';
import './style.css';

function Shell() {
  const [signedIn, setSignedIn] = useState(Boolean(sessionStorage.getItem(sessionKey)));
  const navigate = useNavigate();
  function signOut() {
    sessionStorage.removeItem(sessionKey);
    setSignedIn(false);
    navigate('/sign-in', { replace: true });
  }
  return <><header><Link className="brand" to="/">Ledger Wallet</Link>
    <nav aria-label="Main navigation">{[['/wallets','Wallets'],['/deposit','Deposit'],['/transfers','Transfers'],['/history','History'],['/admin','Admin']].map(([to,label]) =>
      <NavLink key={to} to={to}>{label}</NavLink>)}</nav>
    {signedIn && <button onClick={signOut}>Sign out</button>}</header>
    <main><Routes>
      <Route path="/" element={<Navigate to="/wallets" replace/>}/>
      <Route path="/sign-in" element={<SignIn onSignIn={() => setSignedIn(true)}/>}/>
      <Route path="/register" element={<Register/>}/>
      <Route path="/admin" element={<Placeholder title="Administration"/>}/>
      <Route element={signedIn ? <Outlet/> : <Navigate to="/sign-in" replace/>}>
        <Route path="/wallets" element={<Wallets/>}/>
        <Route path="/deposit" element={<DepositPage/>}/>
        <Route path="/transfers" element={<TransferPage/>}/>
        <Route path="/history" element={<Placeholder title="Wallet history"/>}/>
        <Route path="/wallets/:id/history" element={<Placeholder title="Wallet history"/>}/>
      </Route>
      <Route path="*" element={<section><h1>Page not found</h1><Link to="/">Return to wallets</Link></section>}/>
    </Routes></main></>;
}

function Placeholder({ title }) {
  return <section><h1>{title}</h1><p>This screen is under development.</p></section>;
}

function SignIn({onSignIn}) {
  const navigate = useNavigate();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  async function submit(event) {
    event.preventDefault();
    const token = new FormData(event.currentTarget).get('token').trim();
    if (!token) return;
    setPending(true);
    setError('');
    try {
      await api('/wallets', { headers: { Authorization: 'Bearer ' + token } });
    } catch (err) {
      setError([err.code, err.message].filter(Boolean).join(' · '));
      setPending(false);
      return;
    }
    sessionStorage.setItem(sessionKey, token);
    onSignIn();
    navigate('/wallets', { replace: true });
  }
  return <section><h1>Sign in</h1><form onSubmit={submit}>
    <label htmlFor="token">Wallet access token</label>
    <input id="token" name="token" type="password" required pattern=".*\S.*" autoComplete="off"/>
    <button disabled={pending}>{pending ? 'Signing in…' : 'Open wallets'}</button></form>
    {error && <p role="alert">{error}</p>}<Link to="/register">Register a user</Link></section>;
}

function Wallets() {
  const [result, setResult] = useState(null);
  useEffect(() => {
    const controller = new AbortController();
    api('/wallets', {signal: controller.signal}).then(({data}) => setResult({wallets:data.wallets}))
      .catch(error => { if (!controller.signal.aborted) setResult({error}); });
    return () => controller.abort();
  }, []);
  return <section><h1>Your wallets</h1>
    {!result ? <p role="status">Loading wallets…</p> : result.error ?
      <p role="alert">{result.error.code || 'REQUEST_FAILED'} · {result.error.message}</p> :
      result.wallets.length ? <ul>{result.wallets.map(w => <li key={w.id}><Link to={'/wallets/'+w.id+'/history'}>{w.currency} wallet</Link></li>)}</ul> : <p>No wallets yet.</p>}
  </section>;
}

createRoot(document.getElementById('root')).render(<BrowserRouter><Shell/></BrowserRouter>);
