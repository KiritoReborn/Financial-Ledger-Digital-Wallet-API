import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Link, NavLink, useParams } from 'react-router-dom';
import { api } from './api.js';
import { createTransferPair, getHistoryPage, sendTransferPair, UUID4 } from './ledger-demo.js';
import { formatMinor, toMinorUnits } from './money.js';
import './ledger-pages.css';

const entryTypes = { DEPOSIT: 'Deposit', TRANSFER: 'Transfer', REVERSAL: 'Reversal' };
const dateTime = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' });

function useOwnedWallets() {
  const [state, setState] = useState({ wallets: null, error: null });
  useEffect(() => {
    const controller = new AbortController();
    api('/wallets', { signal: controller.signal }).then(({ data }) => {
      if (!controller.signal.aborted) setState({ wallets: data.wallets, error: null });
    }).catch(error => {
      if (!controller.signal.aborted) setState({ wallets: null, error });
    });
    return () => controller.abort();
  }, []);
  return state;
}

function WalletChoices({ wallets }) {
  return <nav aria-label="Wallet histories" className="ledger-wallet-choices">
    {wallets.map(wallet => <NavLink key={wallet.id} to={`/wallets/${wallet.id}/history`}>
      {wallet.currency} wallet
    </NavLink>)}
  </nav>;
}

function HistoryEntries({ walletId }) {
  const [entries, setEntries] = useState([]);
  const [cursor, setCursor] = useState(null);
  const [pending, setPending] = useState(true);
  const [error, setError] = useState(null);
  const active = useRef(null);

  const load = useCallback(async beforeId => {
    if (active.current) return;
    const controller = new AbortController();
    active.current = controller;
    setPending(true);
    setError(null);
    try {
      const page = await getHistoryPage(walletId, beforeId, controller.signal);
      if (!controller.signal.aborted) {
        setEntries(previous => beforeId === null ? page.entries : [...previous, ...page.entries]);
        setCursor(page.next_before_id);
      }
    } catch (failure) {
      if (!controller.signal.aborted) setError(failure.message || 'Wallet history could not be loaded.');
    } finally {
      if (active.current === controller) {
        active.current = null;
        setPending(false);
      }
    }
  }, [walletId]);

  useEffect(() => {
    load(null);
    return () => {
      active.current?.abort();
      active.current = null;
    };
  }, [load]);

  return <>
    {entries.length > 0 && <div className="ledger-table-scroll">
      <table className="ledger-history-table" aria-label="Wallet transactions">
        <thead><tr><th scope="col">Transaction</th><th scope="col">Date</th>
          <th scope="col">Amount</th></tr></thead>
        <tbody>{entries.map(entry => (
          <tr key={entry.id}>
            <td><strong>{entryTypes[entry.type]}</strong>
              <small>{entry.direction === 'CREDIT' ? 'Credit' : 'Debit'}</small></td>
            <td><time dateTime={entry.created_at}>
              {dateTime.format(new Date(entry.created_at))}
            </time></td>
            <td className={entry.direction === 'CREDIT' ? 'ledger-credit' : undefined}>
              {entry.direction === 'CREDIT' ? '+' : '\u2212'}
              {formatMinor(entry.amount_minor, entry.currency)} {entry.currency}
            </td>
          </tr>
        ))}</tbody>
      </table>
    </div>}
    {pending && <p role="status">Loading transactions.</p>}
    {error && <p role="alert">{error}</p>}
    {!pending && !error && entries.length === 0 && <p>No transactions yet.</p>}
    {!pending && (error || cursor !== null) &&
      <button type="button" onClick={() => load(cursor)}>{error ? 'Retry' : 'Load older entries'}</button>}
  </>;
}

export function WalletHistoryPage() {
  const { id } = useParams();
  const { wallets, error } = useOwnedWallets();
  return <section className="ledger-read-page">
    <h1>Wallet history</h1>
    {wallets?.length > 0 && <WalletChoices wallets={wallets}/>}
    {id ? <HistoryEntries key={id} walletId={id}/> : <>
      {!wallets && !error && <p role="status">Loading wallets.</p>}
      {error && <p role="alert">{error.message}</p>}
      {wallets?.length === 0 && <p>Create a wallet to view its history.</p>}
      {wallets?.length > 0 && <p>Choose a wallet to view its transactions.</p>}
    </>}
  </section>;
}

function TransferResult({ result }) {
  if (result.outcome === 'done') {
    return <><strong>Posted{result.replayed ? ' · Replayed' : ''}</strong>
      <small>{result.data.id}</small></>;
  }
  return <><strong>{result.outcome === 'uncertain' ? 'Outcome unknown' : 'Rejected'}</strong>
    <small>{result.code} · {result.message}</small></>;
}

function ConcurrencyForm({ wallets }) {
  const [senderId, setSenderId] = useState(wallets[0].id);
  const [pending, setPending] = useState(false);
  const [attempts, setAttempts] = useState([]);
  const [error, setError] = useState(null);
  const running = useRef(false);
  const sender = wallets.find(wallet => wallet.id === senderId);
  const uncertain = attempts.some(attempt => attempt.result.outcome === 'uncertain');

  async function run(pair) {
    if (running.current) return;
    running.current = true;
    setPending(true);
    setError(null);
    try {
      setAttempts(await sendTransferPair(pair));
    } finally {
      running.current = false;
      setPending(false);
    }
  }

  function submit(event) {
    event.preventDefault();
    if (running.current || uncertain) return;
    const fields = new FormData(event.currentTarget);
    const receiver = String(fields.get('receiver')).trim().toLowerCase();
    if (!UUID4.test(receiver) || receiver === senderId.toLowerCase()) {
      setError('Enter a valid recipient wallet ID different from the sender.');
      return;
    }
    let amountMinor;
    try {
      amountMinor = toMinorUnits(fields.get('amount'), sender.currency);
    } catch (failure) {
      setError(failure.message);
      return;
    }
    const pair = createTransferPair({
      from_wallet_id: senderId,
      to_wallet_id: receiver,
      amount_minor: amountMinor,
      currency: sender.currency,
    });
    setAttempts([]);
    run(pair);
  }

  return <>
    <form className="ledger-demo-form" onSubmit={submit}>
      <fieldset disabled={pending || uncertain}>
        <label htmlFor="demo-sender">Sender wallet</label>
        <select id="demo-sender" value={senderId} onChange={event => setSenderId(event.target.value)}>
          {wallets.map(wallet => <option key={wallet.id} value={wallet.id}>{wallet.currency}</option>)}
        </select>
        <label htmlFor="demo-receiver">Recipient wallet ID</label>
        <input id="demo-receiver" name="receiver" required spellCheck={false} autoComplete="off"/>
        <label htmlFor="demo-amount">Amount per transfer ({sender.currency})</label>
        <input id="demo-amount" name="amount" required inputMode="decimal"/>
        <button type="submit">Send two simulated transfers</button>
      </fieldset>
    </form>
    {error && <p role="alert">{error}</p>}
    {pending && <p role="status">Waiting for transfer results.</p>}
    {attempts.length > 0 && <div aria-live="polite">
      <ol className="ledger-demo-results" aria-label="Transfer results">
        {attempts.map(({ operation, result }, index) => (
          <li key={operation.key}>Transfer {index + 1} · <TransferResult result={result}/></li>
        ))}
      </ol>
      {uncertain && <button type="button" disabled={pending} onClick={() => run(attempts)}>
        Send again with same key
      </button>}
      <p><Link to={`/wallets/${attempts[0].operation.body.from_wallet_id}/history`}>
        View sender history
      </Link></p>
    </div>}
  </>;
}

export function TransferConcurrencyPage() {
  const { wallets, error } = useOwnedWallets();
  return <section className="ledger-read-page">
    <h1>Concurrent transfer demo</h1>
    <p>Send two simulated transfers from the same wallet at the same time.</p>
    {!wallets && !error && <p role="status">Loading wallets.</p>}
    {error && <p role="alert">{error.message}</p>}
    {wallets?.length === 0 && <p>Create and fund a wallet to run the demo.</p>}
    {wallets?.length > 0 && <ConcurrencyForm wallets={wallets}/>}
  </section>;
}
