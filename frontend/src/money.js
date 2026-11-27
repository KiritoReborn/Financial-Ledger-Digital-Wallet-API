// B05: convert between what people type and integer minor units (FR-1.4, TQ-6).
import { currencyExponents } from '../currencies.js';

export const MAX_MINOR = 10 ** 12;

export function exponentOf(currency) {
  const exponent = currencyExponents[currency];
  if (!Number.isInteger(exponent)) throw new Error('Unsupported currency.');
  return exponent;
}

// "12.50" INR -> 1250, "500" JPY -> 500. Uses string arithmetic, never floats.
export function toMinorUnits(text, currency) {
  const exponent = exponentOf(currency);
  const value = String(text).trim();
  const pattern = exponent === 0 ? /^\d+$/ : new RegExp(`^\\d+(\\.\\d{1,${exponent}})?$`);
  if (!pattern.test(value)) {
    throw new Error(exponent === 0
      ? `Enter a whole number of ${currency}.`
      : `Enter an amount with at most ${exponent} decimal places.`);
  }
  const [whole, fraction = ''] = value.split('.');
  const minor = BigInt(whole + fraction.padEnd(exponent, '0'));
  if (minor < 1n) throw new Error('Enter an amount greater than zero.');
  if (minor > BigInt(MAX_MINOR)) throw new Error('That amount is too large.');
  return Number(minor);
}

// 1250 INR -> "12.50", 500 JPY -> "500".
export function formatMinor(minor, currency) {
  const exponent = exponentOf(currency);
  const sign = minor < 0 ? '-' : '';
  const digits = String(Math.abs(minor)).padStart(exponent + 1, '0');
  if (exponent === 0) return sign + digits;
  return `${sign}${digits.slice(0, -exponent)}.${digits.slice(-exponent)}`;
}
