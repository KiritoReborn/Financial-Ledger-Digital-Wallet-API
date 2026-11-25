// FR-1.4: use the same minor-unit precision as wallet validation and startup.
import exponents from "../backend/app/currency_exponents.json" with { type: "json" };

export const currencyExponents = Object.freeze(exponents);
