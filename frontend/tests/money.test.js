// B05: amounts typed in the UI become integer minor units (FR-1.4, TQ-6).
import test from 'node:test';
import assert from 'node:assert/strict';
import { formatMinor, MAX_MINOR, toMinorUnits } from '../src/money.js';

test('converts using each currency exponent', () => {
  assert.equal(toMinorUnits('12.50', 'INR'), 1250);
  assert.equal(toMinorUnits('12.5', 'USD'), 1250);
  assert.equal(toMinorUnits('12', 'INR'), 1200);
  assert.equal(toMinorUnits(' 0.01 ', 'INR'), 1);
  assert.equal(toMinorUnits('500', 'JPY'), 500);
});

test('never uses floating point', () => {
  assert.equal(toMinorUnits('0.29', 'INR'), 29); // 0.29 * 100 is 28.999999999999996 in floats.
  assert.equal(toMinorUnits('1.10', 'USD'), 110);
  assert.equal(toMinorUnits('10000000000.00', 'INR'), MAX_MINOR);
});

for (const [text, currency, message] of [
  ['', 'INR', /decimal places/],
  ['abc', 'INR', /decimal places/],
  ['1.234', 'INR', /at most 2 decimal places/],
  ['-5', 'INR', /decimal places/],
  ['1e3', 'INR', /decimal places/],
  ['1,000', 'INR', /decimal places/],
  ['.5', 'INR', /decimal places/],
  ['12.5', 'JPY', /whole number of JPY/],
  ['0', 'INR', /greater than zero/],
  ['0.00', 'USD', /greater than zero/],
  ['10000000000.01', 'INR', /too large/],
  ['1000000000001', 'JPY', /too large/],
]) {
  test(`rejects ${JSON.stringify(text)} in ${currency}`, () => {
    assert.throws(() => toMinorUnits(text, currency), message);
  });
}

test('rejects unsupported currencies', () => {
  assert.throws(() => toMinorUnits('1', 'EUR'), /Unsupported currency/);
});

test('formats minor units for display', () => {
  assert.equal(formatMinor(1250, 'INR'), '12.50');
  assert.equal(formatMinor(5, 'USD'), '0.05');
  assert.equal(formatMinor(0, 'INR'), '0.00');
  assert.equal(formatMinor(-2500, 'INR'), '-25.00');
  assert.equal(formatMinor(500, 'JPY'), '500');
});

test('formatting and parsing round-trip', () => {
  for (const minor of [1, 99, 100, 123456, MAX_MINOR]) {
    for (const currency of ['INR', 'USD', 'JPY']) {
      assert.equal(toMinorUnits(formatMinor(minor, currency), currency), minor);
    }
  }
});
