// Number, time and amount formatting shared by the page modules.
import { t, lang } from "./i18n.js";

const WEI = 1e18;

export function duration(seconds) {
  const s = Math.max(0, Math.round(seconds));
  if (s < 90) return t("unit.s", { n: s });
  if (s < 90 * 60) return t("unit.min", { n: Math.round(s / 60) });
  if (s < 48 * 3600) return t("unit.h", { n: round1(s / 3600) });
  return t("unit.d", { n: round1(s / 86400) });
}

export function ago(seconds) { return t("unit.ago", { t: duration(seconds) }); }

function round1(x) { return new Intl.NumberFormat(lang(), { maximumFractionDigits: x < 10 ? 1 : 0 }).format(x); }

export function count(n) { return new Intl.NumberFormat(lang()).format(n); }

export function amount(wei, symbol) {
  const v = Number(wei) / WEI;
  const digits = v === 0 ? 0 : v < 0.001 ? 6 : v < 1 ? 4 : 2;
  return `${new Intl.NumberFormat(lang(), { maximumFractionDigits: digits }).format(v)} ${symbol}`;
}

export function etherString(wei) {
  // exact decimal for copy-paste commands (BigInt, no float rounding)
  const w = BigInt(wei);
  const whole = w / 10n ** 18n;
  const frac = (w % 10n ** 18n).toString().padStart(18, "0").replace(/0+$/, "");
  return frac ? `${whole}.${frac}` : `${whole}`;
}

export function short(addr) { return `${addr.slice(0, 6)}…${addr.slice(-4)}`; }

export function clock(ts) {
  return new Intl.DateTimeFormat(lang(), { dateStyle: "medium", timeStyle: "short", timeZone: "UTC" }).format(new Date(ts * 1000)) + " UTC";
}
