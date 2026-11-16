// Fuel gauge: reads debt, reserves and balance of any Lasna contract straight from the Lasna RPC in the browser.
import { lamp } from "./lamp.js";
import { t } from "./i18n.js";
import { amount, etherString } from "./format.js";

const ADDRESS = /^0x[0-9a-fA-F]{40}$/;

function word(addr) { return addr.toLowerCase().replace(/^0x/, "").padStart(64, "0"); }

async function rpcBatch(url, calls) {
  const body = calls.map(([method, params], id) => ({ jsonrpc: "2.0", id, method, params }));
  const res = await fetch(url, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const out = await res.json();
  if (!Array.isArray(out)) throw new Error("not a batch reply");
  const byId = new Map(out.map((r) => [r.id, r]));
  return calls.map((_, i) => {
    const r = byId.get(i);
    if (!r || r.error || typeof r.result !== "string") throw new Error("bad reply");
    return BigInt(r.result === "0x" ? "0x0" : r.result);
  });
}

export function initGauge(ctx) {
  const form = document.getElementById("gauge-form");
  const input = document.getElementById("gauge-addr");
  const btn = document.getElementById("gauge-btn");
  const msg = document.getElementById("gauge-msg");
  const out = document.getElementById("gauge-out");

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const addr = input.value.trim();
    msg.textContent = "";
    if (!ADDRESS.test(addr)) {
      input.setAttribute("aria-invalid", "true");
      msg.textContent = t("gauge.invalid");
      input.focus();
      return;
    }
    input.removeAttribute("aria-invalid");
    const chain = ctx.chains.chains[ctx.site.gauge_chain];
    const sel = ctx.chains.selectors;
    btn.disabled = true;
    btn.textContent = t("gauge.reading");
    try {
      const [debt, reserves, balance] = await rpcBatch(chain.rpc, [
        ["eth_call", [{ to: chain.biller, data: sel["debt(address)"] + word(addr) }, "latest"]],
        ["eth_call", [{ to: chain.biller, data: sel["reserves(address)"] + word(addr) }, "latest"]],
        ["eth_getBalance", [addr, "latest"]],
      ]);
      render(out, { addr, chain, debt, reserves, balance, fee: ctx.site.median_fee_wei, fill: ctx.site.gauge_fill_wei });
    } catch (_) {
      msg.textContent = t("gauge.error");
      out.hidden = true;
    } finally {
      btn.disabled = false;
      btn.textContent = t("gauge.read");
    }
  });
}

function render(out, { addr, chain, debt, reserves, balance, fee, fill }) {
  const sym = chain.native_symbol;
  const dark = debt > 0n;
  const left = fee ? (balance / BigInt(fee)).toString() : t("gauge.leftPending");
  const value = etherString(dark ? debt + BigInt(fill) : BigInt(fill));
  const cmd = `cast send ${chain.biller} "depositTo(address)" ${addr} --value ${value}ether --rpc-url ${chain.rpc}`;
  out.replaceChildren();
  const head = document.createElement("div");
  head.className = "card-head";
  head.innerHTML = `${lamp(!dark)}`;
  const pill = document.createElement("span");
  pill.className = `pill ${dark ? "dark" : "lit"}`;
  pill.textContent = t(dark ? "fleet.dark" : "fleet.lit");
  head.append(pill);
  const kv = document.createElement("dl");
  kv.className = "kv";
  for (const [k, v] of [["gauge.debt", amount(debt, sym)], ["gauge.reserves", amount(reserves, sym)], ["gauge.balance", amount(balance, sym)], ["gauge.left", left]]) {
    const dt = document.createElement("dt"); dt.textContent = t(k);
    const dd = document.createElement("dd"); dd.textContent = v;
    if (k === "gauge.left" && !fee) dd.className = "soft";
    kv.append(dt, dd);
  }
  const p1 = document.createElement("p"); p1.textContent = t("gauge.fill");
  const pre = document.createElement("pre"); const code = document.createElement("code"); code.textContent = cmd; pre.append(code);
  const p2 = document.createElement("p"); p2.textContent = t("gauge.own");
  out.append(head, kv, p1, pre, p2);
  out.hidden = false;
}
