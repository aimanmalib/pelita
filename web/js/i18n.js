// Text lives in web/lang/<code>.json; this module only swaps it in. Choice is remembered in localStorage when allowed.
const KEY = "pelita.lang";
let dict = {};
let code = "en";

export function t(key, vars = {}) {
  const s = dict[key] ?? key;
  return s.replace(/\{(\w+)\}/g, (_, k) => (k in vars ? String(vars[k]) : `{${k}}`));
}

export function lang() { return code; }

export function saved(fallback, allowed) {
  try {
    const v = localStorage.getItem(KEY);
    if (allowed.includes(v)) return v;
  } catch (_) { /* storage blocked: use the default */ }
  return fallback;
}

export async function load(next) {
  const res = await fetch(`lang/${next}.json`, { cache: "no-cache" });
  if (!res.ok) throw new Error(`lang ${next}: HTTP ${res.status}`);
  dict = await res.json();
  code = next;
  try { localStorage.setItem(KEY, next); } catch (_) { /* private mode */ }
  apply(document);
}

export function apply(root) {
  document.documentElement.lang = code === "ms" ? "ms" : "en";
  root.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
  root.querySelectorAll("[data-i18n-html]").forEach((el) => { el.innerHTML = t(el.dataset.i18nHtml); });
  root.querySelectorAll("[data-i18n-attr]").forEach((el) => {
    el.dataset.i18nAttr.split(";").forEach((pair) => {
      const [attr, key] = pair.split(":");
      el.setAttribute(attr, t(key));
    });
  });
}
