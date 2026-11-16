// Fleet cards and head totals from snapshot.fleet + snapshot.events (shape written by ops/indexer.py).
import { lamp } from "./lamp.js";
import { t } from "./i18n.js";
import { duration, amount, short } from "./format.js";

const RELIGHT = new Set(["Refueled", "Relit"]);
const LOOP_ORDER = ["WentDark", "Refueled", "RefuelRequested", "Relit"];

function chainByName(chains, name) {
  return Object.entries(chains.chains).find(([key, c]) => key === name || c.name === name)?.[1];
}

export function fleetTotals(snap, chains) {
  const out = { wards: 0, lit: 0, dark: 0, relights: 0, lastRelightTs: 0, keeperWei: null, keeperSymbol: "" };
  for (const [key, view] of Object.entries(snap.fleet || {})) {
    for (const w of view.wards) {
      if (w.role !== "guarded") continue;
      out.wards += 1;
      if (w.debt_wei > 0) out.dark += 1; else out.lit += 1;
    }
    if (view.own?.role === "keeper") {
      out.keeperWei = view.own.balance_wei;
      out.keeperSymbol = chains.chains[key]?.native_symbol || "";
    }
  }
  for (const e of snap.events || []) {
    if (!RELIGHT.has(e.event)) continue;
    out.relights += 1;
    if (e.ts && e.ts > out.lastRelightTs) out.lastRelightTs = e.ts;
  }
  return out;
}

function lastLoop(events, target) {
  const mine = events.filter((e) => e.target === target);
  const start = mine.map((e) => e.event).lastIndexOf("WentDark");
  return start < 0 ? [] : mine.slice(start).filter((e) => LOOP_ORDER.includes(e.event));
}

function card(chains, chain, w, events) {
  const dark = w.debt_wei > 0;
  const el = document.createElement("article");
  el.className = `card ${dark ? "is-dark" : "is-lit"}`;
  el.innerHTML = `
    <div class="card-head">
      ${lamp(!dark)}
      <div><div class="card-name"></div><div class="card-chain"></div></div>
      <span class="pill ${dark ? "dark" : "lit"}"></span>
    </div>
    <span class="role ${w.role}"></span>
    <dl class="kv"></dl>
    <div class="addr"><a rel="noopener"></a></div>`;
  el.querySelector(".card-name").textContent = w.name || short(w.address);
  el.querySelector(".card-chain").textContent = chain.name;
  el.querySelector(".pill").textContent = dark ? t("fleet.darkFor", { t: duration(w.dark_seconds || 0) }) : t("fleet.lit");
  el.querySelector(".role").textContent = t(w.role === "control" ? "fleet.control" : "fleet.guarded");
  const kv = el.querySelector(".kv");
  for (const [k, v] of [["fleet.debt", amount(w.debt_wei, chain.native_symbol)], ["fleet.reserves", amount(w.reserves_wei, chain.native_symbol)]]) {
    const dt = document.createElement("dt"); dt.textContent = t(k);
    const dd = document.createElement("dd"); dd.textContent = v;
    kv.append(dt, dd);
  }
  const a = el.querySelector(".addr a");
  a.href = `${chain.explorer}/address/${w.address}`; a.textContent = short(w.address); a.title = w.address;
  const loop = lastLoop(events, w.address);
  const title = document.createElement("p");
  title.className = "loop-title"; title.textContent = t("fleet.loop");
  const ol = document.createElement("ol");
  ol.className = "loop";
  if (!loop.length) {
    const li = document.createElement("li"); li.textContent = t("fleet.noLoop"); ol.append(li);
  }
  for (const e of loop) {
    const li = document.createElement("li");
    li.className = e.event === "WentDark" ? "" : "ok";
    const span = document.createElement("span"); span.textContent = t(`event.${e.event}`);
    const link = document.createElement("a");
    const ec = chainByName(chains, e.chain) || chain;
    link.href = `${ec.explorer_tx}${e.tx}`; link.textContent = short(e.tx); link.rel = "noopener";
    li.append(span, link); ol.append(li);
  }
  el.append(title, ol);
  return el;
}

export function renderFleet(root, snap, chains) {
  root.replaceChildren();
  const views = Object.entries(snap?.fleet || {});
  if (!views.length) {
    const p = document.createElement("p"); p.className = "empty"; p.textContent = t("fleet.empty"); root.append(p); return;
  }
  for (const [key, view] of views) {
    for (const w of view.wards) root.append(card(chains, chains.chains[key], w, snap.events || []));
  }
}
