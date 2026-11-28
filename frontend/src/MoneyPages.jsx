// B05 deposit and transfer screens (FR-1.6, FR-1.7, FR-2.4 to FR-2.9).
import React, { useCallback, useEffect, useState } from 'react';
import { api } from './api.js';
import { formatMinor, toMinorUnits } from './money.js';
import { newOperation, sendOperation } from './operation.js';
import './money-pages.css';

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function useWallets() {
  const [state, setState] = useState({ wallets: null, error: null });
  const load = useCallback(signal => api('/wallets', { signal })
    .then(({ data }) => setState({ wallets: data.wallets, error: null }))
    .catch(error => { if (!signal?.aborted) setState({ wallets: [], error }); }), []);
  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal);
    return () => controller.abort();
  }, [load]);
  return { ...state, reload: () => load() };
}

// One operation at a time: a new key per Submit, the same key for "Send again".
function useOperation(onDone) {
  const [operation, setOperation] = useState(null);
  const [result, setResult] = useState(null);
  const [pending, setPending] = useState(false);

  async function run(next) {
    setOperation(next);
    setPending(true);
    const outcome = await sendOperation(next);
    setPending(false);
    setResult(outcome);
    if (outcome.outcome === 'done') onDone();
  }

  return {
    operation, result, pending,
    uncertain: result?.outcome === 'uncertain',
    start: (path, body) => run(newOperation(path, body)),
    resend: () => run(operation),
    discard: () => { setOperation(null); setResult(null); },
  };
}

function WalletOptions({ wallets }) {
  return wallets.map(wallet => <option key={wallet.id} value={wallet.id}>
    {wallet.currency} wallet · {formatMinor(wallet.balance_minor, wallet.currency)} {wallet.currency}
  </option>);
}

function OperationPanel({ op, describe }) {
  const { operation, result, pending } = op;
  if (!operation) return null;
  return <div className="operation" aria-live="polite">
    {pending && <p role="status">Sending… Do not close this page.</p>}
    {!pending && result?.outcome === 'done' && <div className="outcome done">
      <p><strong>{describe(result.data)}</strong>
        {result.replayed && <span className="badge">Replayed</span>}</p>
      <p className="detail">Transaction {result.data.id}</p>
    </div>}
    {!pending && result?.outcome === 'uncertain' && <div className="outcome uncertain" role="alert">
      <p><strong>{result.code}</strong> · {result.message}</p>
      <p>Send it again with the same key. If it already went through, the stored result
        comes back and no money moves twice.</p>
    </div>}
    {!pending && result?.outcome === 'rejected' && <div className="outcome rejected" role="alert">
      <p><strong>{result.code}</strong> · {result.message}</p>
      <p>Nothing was moved. Fix the form and submit again.</p>
    </div>}
    <p className="detail">Idempotency-Key <code>{operation.key}</code></p>
    {result && result.outcome !== 'rejected' && <div className="actions">
      <button type="button" onClick={op.resend} disabled={pending}>Send again with same key</button>
      {op.uncertain && <button type="button" className="secondary" onClick={op.discard}
        disabled={pending}>Discard and start a new operation</button>}
    </div>}
  </div>;
}

function useAmount(currency) {
  const [text, setText] = useState('');
  let minor = null;
  let error = null;
  if (text && currency) {
    try { minor = toMinorUnits(text, currency); } catch (problem) { error = problem.message; }
  }
  return { text, setText, minor, error };
}

function AmountField({ amount, currency }) {
  return <>
    <label htmlFor="amount">Amount{currency ? ` (${currency})` : ''}</label>
    <input id="amount" inputMode="decimal" autoComplete="off" value={amount.text}
      onChange={event => amount.setText(event.target.value)}
      aria-invalid={Boolean(amount.error)} aria-describedby="amount-help"/>
    <p id="amount-help" className={amount.error ? 'field-error' : 'detail'}>
      {amount.error || (currency === 'JPY' ? 'Whole yen only.' : 'Up to two decimal places.')}
    </p>
  </>;
}

function NeedsWallets({ state, children }) {
  if (!state.wallets) return <p role="status">Loading wallets…</p>;
  if (state.error) return <p role="alert">{state.error.code || 'REQUEST_FAILED'} · {state.error.message}</p>;
  if (!state.wallets.length) return <p>Create a wallet first.</p>;
  return children;
}

export function DepositPage() {
  const wallets = useWallets();
  const [walletId, setWalletId] = useState(() => new URLSearchParams(window.location.search).get('wallet_id') || '');
  const wallet = wallets.wallets?.find(item => item.id === walletId) || wallets.wallets?.[0];
  const amount = useAmount(wallet?.currency);
  const op = useOperation(wallets.reload);

  function submit(event) {
    event.preventDefault();
    if (amount.minor === null || !wallet) return;
    op.start(`/wallets/${wallet.id}/deposit`, { amount_minor: amount.minor });
  }

  return <section><h1>Deposit</h1>
    <p className="detail">Simulated funds only. No real money is involved.</p>
    <NeedsWallets state={wallets}>
      <form onSubmit={submit}>
        <label htmlFor="wallet">Wallet</label>
        <select id="wallet" value={wallet?.id || ''} onChange={event => setWalletId(event.target.value)}>
          <WalletOptions wallets={wallets.wallets || []}/>
        </select>
        <AmountField amount={amount} currency={wallet?.currency}/>
        <button disabled={op.pending || op.uncertain || amount.minor === null}>Deposit</button>
      </form>
      <OperationPanel op={op} describe={data => {
        const credit = data.entries.find(entry => entry.direction === 'CREDIT');
        return `Deposited ${formatMinor(credit.amount_minor, credit.currency)} ${credit.currency}`;
      }}/>
    </NeedsWallets>
  </section>;
}

export function TransferPage() {
  const wallets = useWallets();
  const [fromId, setFromId] = useState('');
  const [toId, setToId] = useState('');
  const [description, setDescription] = useState('');
  const source = wallets.wallets?.find(item => item.id === fromId) || wallets.wallets?.[0];
  const amount = useAmount(source?.currency);
  const op = useOperation(wallets.reload);
  const target = toId.trim();
  const targetError = target && !UUID_PATTERN.test(target) ? 'Enter a wallet ID (UUID).'
    : target && target.toLowerCase() === source?.id ? 'Choose a different wallet.' : null;

  function submit(event) {
    event.preventDefault();
    if (amount.minor === null || !source || !target || targetError) return;
    const body = { from_wallet_id: source.id, to_wallet_id: target, amount_minor: amount.minor,
      currency: source.currency };
    if (description.trim()) body.description = description.trim();
    op.start('/transfers', body);
  }

  return <section><h1>Transfer</h1>
    <p className="detail">Simulated funds only. No real money is involved.</p>
    <NeedsWallets state={wallets}>
      <form onSubmit={submit}>
        <label htmlFor="from">From your wallet</label>
        <select id="from" value={source?.id || ''} onChange={event => setFromId(event.target.value)}>
          <WalletOptions wallets={wallets.wallets || []}/>
        </select>
        <label htmlFor="to">To wallet ID</label>
        <input id="to" value={toId} autoComplete="off" spellCheck="false"
          onChange={event => setToId(event.target.value)} aria-invalid={Boolean(targetError)}
          aria-describedby="to-help"/>
        <p id="to-help" className={targetError ? 'field-error' : 'detail'}>
          {targetError || `The receiving ${source?.currency || ''} wallet, from its owner.`}</p>
        <AmountField amount={amount} currency={source?.currency}/>
        <label htmlFor="description">Description (optional)</label>
        <input id="description" maxLength={200} value={description}
          onChange={event => setDescription(event.target.value)}/>
        <button disabled={op.pending || op.uncertain || amount.minor === null || !target
          || Boolean(targetError)}>Transfer</button>
      </form>
      <OperationPanel op={op} describe={data =>
        `Sent ${formatMinor(data.amount_minor, data.currency)} ${data.currency}`}/>
    </NeedsWallets>
  </section>;
}
