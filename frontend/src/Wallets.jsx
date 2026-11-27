import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { currencyExponents } from '../currencies.js';
import { api } from './api.js';
import { formatMinor } from './money.js';

export default function Wallets() {
  const [wallets, setWallets] = useState(null);
  const [error, setError] = useState('');
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    api('/wallets', { signal: controller.signal })
      .then(({ data }) => setWallets(data.wallets))
      .catch(err => {
        if (!controller.signal.aborted) setError([err.code, err.message].filter(Boolean).join(' · '));
      });
    return () => controller.abort();
  }, []);

  async function create(event) {
    event.preventDefault();
    const currency = new FormData(event.currentTarget).get('currency');
    setCreating(true);
    setError('');
    try {
      const { data } = await api('/wallets', { method: 'POST', body: { currency } });
      setWallets(current => [...current, data]);
    } catch (err) {
      setError([err.code, err.message].filter(Boolean).join(' · '));
    } finally {
      setCreating(false);
    }
  }

  const available = Object.keys(currencyExponents).filter(code => !wallets?.some(w => w.currency === code));
  return <section><h1>Your wallets</h1>
    {error && <p role="alert">{error}</p>}
    {!wallets && !error && <p role="status">Loading wallets…</p>}
    {wallets?.length === 0 && <p>No wallets yet.</p>}
    {wallets?.map(wallet => <article key={wallet.id}>
      <h2>{wallet.currency} wallet</h2>
      <p>{wallet.currency} {formatMinor(wallet.balance_minor, wallet.currency)}</p>
      <Link to={'/wallets/' + wallet.id + '/history'}>History</Link>
      {' · '}<Link to={'/deposit?wallet_id=' + encodeURIComponent(wallet.id)}>Deposit</Link>
    </article>)}
    {wallets && available.length > 0 && <form onSubmit={create}>
      <label>New wallet currency
        <select name="currency">{available.map(code => <option key={code}>{code}</option>)}</select>
      </label>
      <button disabled={creating}>{creating ? 'Creating…' : 'Create wallet'}</button>
    </form>}
  </section>;
}
