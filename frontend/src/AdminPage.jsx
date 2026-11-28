// D05 admin reconciliation & confirmed reversal page (EI-UI-6, EI-UI-4, EI-UI-7).
import React, { useState } from 'react';
import {
  RECONCILE_CHECKS,
  formatMismatchValue,
  isUuidV4,
  newReversalOperation,
  runReconciliation,
  sendReversal,
} from './admin.js';
import { formatMinor } from './money.js';
import './money-pages.css';
import './admin-page.css';

function CredentialsGate({ onUnlock }) {
  const [token, setToken] = useState('');
  const [key, setKey] = useState('');
  const [error, setError] = useState('');

  function submit(event) {
    event.preventDefault();
    const trimmedToken = token.trim();
    const trimmedKey = key.trim();
    if (!trimmedToken || !trimmedKey) {
      setError('Enter both the admin bearer token and X-Admin-Key.');
      return;
    }
    setError('');
    setToken('');
    setKey('');
    onUnlock({ token: trimmedToken, key: trimmedKey });
  }

  return (
    <form onSubmit={submit}>
      <p className="detail">
        Admin credentials are kept in page memory only for this session and are never
        persisted in browser storage or bundled into the frontend.
      </p>
      <label htmlFor="admin-token">
        Admin bearer token
        <input
          id="admin-token"
          name="admin-token"
          type="password"
          value={token}
          onChange={event => setToken(event.target.value)}
          required
          autoComplete="off"
        />
      </label>
      <label htmlFor="admin-key">
        X-Admin-Key
        <input
          id="admin-key"
          name="admin-key"
          type="password"
          value={key}
          onChange={event => setKey(event.target.value)}
          required
          autoComplete="off"
        />
      </label>
      {error && <p role="alert" className="field-error">{error}</p>}
      <button type="submit">Start admin session</button>
    </form>
  );
}

function ReconcilePanel({ credentials }) {
  const [pending, setPending] = useState(false);
  const [report, setReport] = useState(null);
  const [error, setError] = useState(null);

  async function handleRun() {
    setPending(true);
    setError(null);
    try {
      const data = await runReconciliation(credentials);
      setReport(data);
    } catch (err) {
      setError({
        code: err?.code || 'NETWORK_ERROR',
        message: err?.code ? err.message : 'Could not reach the API.',
      });
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="admin-panel" aria-live="polite">
      <h2>Ledger reconciliation</h2>
      <p className="detail">
        Runs all four read-only invariant checks inside one consistent snapshot.
      </p>
      <button type="button" onClick={handleRun} disabled={pending}>
        {pending ? 'Running reconciliation…' : 'Run reconciliation'}
      </button>

      {error && (
        <div className="outcome rejected" role="alert">
          <p><strong>{error.code}</strong> · {error.message}</p>
        </div>
      )}

      {report && (
        <>
          <div className={`outcome ${report.ok ? 'done' : 'rejected'}`}>
            <p>
              <strong>{report.ok ? 'Balanced' : 'Mismatches found'}</strong>
              {' '}({report.mismatches.length} mismatch{report.mismatches.length === 1 ? '' : 'es'})
            </p>
          </div>
          <ul className="check-list">
            {RECONCILE_CHECKS.map(({ key, label }) => {
              const passed = Boolean(report.checks?.[key]);
              return (
                <li key={key} className="check-row">
                  <span>{label} (<code>{key}</code>)</span>
                  <span className={`status-pill ${passed ? 'pass' : 'fail'}`}>
                    {passed ? 'PASS' : 'FAIL'}
                  </span>
                </li>
              );
            })}
          </ul>
          {report.mismatches.length > 0 && (
            <div className="mismatch-list" role="region" aria-label="Reconciliation mismatches">
              {report.mismatches.map((item, idx) => (
                <div key={`${item.check}-${idx}`} className="mismatch-card">
                  <p><strong>{item.check}</strong></p>
                  {item.currency && <p>Currency: <code>{item.currency}</code></p>}
                  {item.wallet_id && <p>Wallet: <code>{item.wallet_id}</code></p>}
                  {item.txn_id && <p>Transaction: <code>{item.txn_id}</code></p>}
                  <p>Expected: <code>{formatMismatchValue(item.expected)}</code></p>
                  <p>Actual: <code>{formatMismatchValue(item.actual)}</code></p>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function ReversalPanel({ credentials }) {
  const [txnIdInput, setTxnIdInput] = useState('');
  const [confirmingId, setConfirmingId] = useState('');
  const [operation, setOperation] = useState(null);
  const [result, setResult] = useState(null);
  const [pending, setPending] = useState(false);

  const trimmedId = txnIdInput.trim();
  const idValid = isUuidV4(trimmedId);
  const idError = trimmedId && !idValid ? 'Enter a valid UUID v4 transaction ID.' : '';
  const uncertain = result?.outcome === 'uncertain';

  async function execute(nextOp) {
    setOperation(nextOp);
    setPending(true);
    const outcome = await sendReversal(nextOp, credentials);
    setPending(false);
    setResult(outcome);
    if (outcome.outcome === 'done' || outcome.outcome === 'rejected') {
      setConfirmingId('');
    }
  }

  function review(event) {
    event.preventDefault();
    if (!idValid) return;
    setConfirmingId(trimmedId);
  }

  function confirmReversal() {
    if (!confirmingId) return;
    execute(newReversalOperation(confirmingId));
  }

  function discard() {
    setOperation(null);
    setResult(null);
    setConfirmingId('');
  }

  return (
    <div className="admin-panel" aria-live="polite">
      <h2>Transaction reversal</h2>
      <p className="detail">
        Reverses an eligible deposit or transfer once by appending mirrored entries.
      </p>
      <form onSubmit={review}>
        <label htmlFor="reverse-txn-id">
          Transaction ID (UUID v4)
          <input
            id="reverse-txn-id"
            value={txnIdInput}
            onChange={event => {
              setTxnIdInput(event.target.value);
              setConfirmingId('');
            }}
            aria-invalid={Boolean(idError)}
            aria-describedby="reverse-txn-help"
            autoComplete="off"
            disabled={pending || uncertain}
          />
        </label>
        <p id="reverse-txn-help" className={idError ? 'field-error' : 'detail'}>
          {idError || 'Enter the original DEPOSIT or TRANSFER transaction UUID v4.'}
        </p>
        <button type="submit" disabled={pending || uncertain || !idValid}>
          Review reversal
        </button>
      </form>

      {confirmingId && (
        <div className="confirm-box" role="region" aria-label="Confirm reversal">
          <p>
            <strong>Confirm reversal?</strong> This appends a permanent reversal for
            transaction <code>{confirmingId}</code>.
          </p>
          <div className="actions">
            <button type="button" onClick={confirmReversal} disabled={pending}>
              {pending ? 'Reversing…' : 'Confirm reversal'}
            </button>
            <button
              type="button"
              className="secondary"
              onClick={() => setConfirmingId('')}
              disabled={pending}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {operation && (
        <div className="operation">
          {pending && <p role="status">Sending reversal… Do not close this page.</p>}
          {!pending && result?.outcome === 'done' && (
            <div className="outcome done">
              <p>
                <strong>Reversal posted</strong>
                {result.replayed && <span className="badge">Replayed</span>}
              </p>
              <p className="detail">Reversal ID: <code>{result.data.id}</code></p>
              <p className="detail">Reverses: <code>{result.data.reverses_txn_id}</code></p>
              {Array.isArray(result.data.entries) && result.data.entries.map(entry => (
                <p key={entry.id ?? `${entry.wallet_id}-${entry.direction}`} className="detail">
                  {entry.direction} · {formatMinor(entry.amount_minor, entry.currency)} {entry.currency}
                  {' '}· wallet <code>{entry.wallet_id}</code>
                </p>
              ))}
            </div>
          )}
          {!pending && result?.outcome === 'uncertain' && (
            <div className="outcome uncertain" role="alert">
              <p><strong>{result.code}</strong> · {result.message}</p>
              <p>
                Send again with the same key. If the reversal already committed, the stored
                response returns without reversing twice.
              </p>
            </div>
          )}
          {!pending && result?.outcome === 'rejected' && (
            <div className="outcome rejected" role="alert">
              <p><strong>{result.code}</strong> · {result.message}</p>
              <p>No ledger records were changed.</p>
            </div>
          )}
          <p className="detail">Idempotency-Key <code>{operation.key}</code></p>
          {result && result.outcome !== 'rejected' && (
            <div className="actions">
              <button type="button" onClick={() => execute(operation)} disabled={pending}>
                Send again with same key
              </button>
              {uncertain && (
                <button type="button" className="secondary" onClick={discard} disabled={pending}>
                  Discard and start a new operation
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function AdminPage() {
  const [credentials, setCredentials] = useState(null);

  return (
    <section className="admin-grid">
      <div>
        <h1>Administration</h1>
        <p className="admin-banner">
          Simulated funds only · Demonstration-level authentication · Database-enforced
          append-only ledger (not a tamper-evident hash chain).
        </p>
      </div>

      {!credentials ? (
        <CredentialsGate onUnlock={setCredentials} />
      ) : (
        <>
          <div className="session-bar">
            <p><strong>Admin session active</strong> (credentials in memory only)</p>
            <button
              type="button"
              className="secondary"
              onClick={() => setCredentials(null)}
            >
              End admin session
            </button>
          </div>
          <ReconcilePanel credentials={credentials} />
          <ReversalPanel credentials={credentials} />
        </>
      )}
    </section>
  );
}
