// Pelita page: loads site settings, chain config and the indexer snapshot, renders the six sections, polls the snapshot.
import { lamp, fillLamps } from "./lamp.js";
import { t, load, saved, lang } from "./i18n.js";
import { duration, ago, count, amount, short, clock, etherString } from "./format.js";
import { initGauge, renderGauge } from "./gauge.js";
import { renderFleet, fleetTotals } from "./fleet.js";

const ctx = { site: null, chains: null, snap: null, snapFailed: false, measured: null, darkOpen: false, gauge: null };
// ?keadaan=muat|kosong|ralat forces one state of the live proof row, so each designed state can be checked.
const FORCED = ["muat", "kosong", "ralat"].find((k) => k === new URLSearchParams(location.search).get("keadaan"));
const $ = (id) => document.getElementById(id);
const now = () => Date.now() / 1000;

async function json(url, opts) {
  const res = await fetch(url, opts);
  if (!res.ok) throw new Error(`${url}: HTTP ${res.status}`);
  return res.json();
}

function headState(tot) {
  if (FORCED) return FORCED;
  if (!ctx.snap) return ctx.snapFailed ? "ralat" : "muat";
  return tot.wards ? "ada" : "kosong";
}

function renderHead() {
  const s = FORCED === "muat" || FORCED === "ralat" ? null : ctx.snap;
  const fresh = $("fresh");
  const tot = s ? fleetTotals(s, ctx.chains) : null;
  const state = headState(tot);
  $("proof").dataset.status = state;
  fresh.classList.remove("warn");
  if (state === "muat") { fresh.textContent = t("stat.loading"); return; }
  if (state === "ralat") { fresh.textContent = t("stat.offline", { n: ctx.site.poll_seconds }); return; }
  if (state === "kosong") { fresh.textContent = t("stat.empty"); return; }
  const set = (k, v) => { document.querySelector(`#stats [data-k="${k}"]`).textContent = v; };
  set("lit", tot.wards ? count(tot.lit) : "–");
  set("dark", tot.wards ? count(tot.dark) : "–");
  set("relights", tot.wards ? count(tot.relights) : "–");
  set("last", tot.lastRelightTs ? ago(now() - tot.lastRelightTs) : t("stat.none"));
  const tank = document.querySelector('#stats [data-k="tank"]');
  if (tot.keeperWei === null) tank.textContent = "–";
  else {
    const [num, unit] = amount(tot.keeperWei, tot.keeperSymbol).split(" ");
    tank.innerHTML = '<span></span> <span class="unit"></span>';
    tank.children[0].textContent = num; tank.children[1].textContent = unit;
  }
  const age = now() - (s.generated_at || 0);
  if (age > ctx.site.stale_after_seconds) {
    fresh.classList.add("warn");
    fresh.textContent = t("stat.stale", { t: duration(age) });
  } else {
    fresh.textContent = t("stat.updated", { t: ago(age) });
  }
}

function renderTry() {
  const demo = ctx.snap?.demo;
  const box = $("cmd"), code = $("cmd-text"), copy = $("copy"), cd = $("cooldown");
  if (!demo?.beacon) {
    box.classList.add("pending"); code.textContent = t("try.pending"); copy.hidden = true; cd.textContent = ""; return;
  }
  const chain = ctx.chains.chains[demo.chain];
  box.classList.remove("pending");
  code.textContent = `cast send ${demo.beacon} "poke()" --rpc-url ${chain.rpc} --account <you>`;
  copy.hidden = false;
  const left = (demo.last_beat_ts || 0) + (demo.cooldown_seconds || 0) - now();
  cd.textContent = left > 0 ? t("try.cooldown", { t: duration(left) }) : t("try.ready");
}

function renderDark() {
  const c = ctx.snap?.census?.lasna;
  const agg = $("agg"), grid = $("lampgrid"), table = $("darktable"), more = $("dark-more"), asof = $("dark-asof");
  agg.replaceChildren(); grid.replaceChildren(); table.replaceChildren();
  if (!c) { asof.textContent = t("dark.empty"); more.hidden = true; return; }
  const tiles = [["dark.outages", count(c.outages)], ["dark.still", count(c.still_dark)]];
  if (c.dark_age_seconds?.count) tiles.push(["dark.medianAge", duration(c.dark_age_seconds.median)]);
  if (c.recovery_seconds?.count) tiles.push(["dark.medianRecover", duration(c.recovery_seconds.median)]);
  const sym = ctx.chains.chains.lasna.native_symbol;
  if (c.debt_wei?.count) tiles.push(["dark.medianDebt", amount(c.debt_wei.median, sym)]);
  for (const [k, v] of tiles) {
    const d = document.createElement("div");
    d.innerHTML = `<dd></dd><dt></dt>`;
    const dd = d.querySelector("dd");
    if (k === "dark.medianDebt") {
      const [num, unit] = v.split(" ");
      dd.innerHTML = '<span></span> <span class="unit"></span>';
      dd.children[0].textContent = num; dd.children[1].textContent = unit;
    } else dd.textContent = v;
    d.querySelector("dt").textContent = t(k);
    agg.append(d);
  }
  const lamps = Math.min(c.dark.length, ctx.site.dark_grid_max);
  grid.innerHTML = lamp(false).repeat(lamps);
  const explorer = ctx.chains.chains.lasna.explorer;
  const rows = ctx.darkOpen ? c.dark : c.dark.slice(0, ctx.site.dark_table_rows);
  const head = document.createElement("thead");
  head.innerHTML = `<tr><th scope="col"></th><th scope="col" class="num"></th><th scope="col" class="num"></th></tr>`;
  const ths = head.querySelectorAll("th");
  ths[0].textContent = t("dark.colAddress"); ths[1].textContent = t("dark.colFor"); ths[2].textContent = t("dark.colDebt");
  const body = document.createElement("tbody");
  for (const r of rows) {
    const tr = document.createElement("tr");
    const a = document.createElement("a");
    a.href = `${explorer}/address/${r.address}`; a.textContent = short(r.address); a.title = r.address; a.rel = "noopener";
    const td0 = document.createElement("td"); td0.append(a);
    const td1 = document.createElement("td"); td1.className = "num"; td1.textContent = duration(r.dark_seconds);
    const td2 = document.createElement("td"); td2.className = "num"; td2.textContent = r.debt_wei ? amount(r.debt_wei, sym) : "–";
    tr.append(td0, td1, td2); body.append(tr);
  }
  table.append(head, body);
  more.hidden = c.dark.length <= ctx.site.dark_table_rows;
  more.textContent = ctx.darkOpen ? t("dark.less") : t("dark.more", { n: count(c.dark.length) });
  asof.textContent = t("dark.asOf", { b: count(c.to_block), t: clock(c.as_of_ts) });
}

function renderCost() {
  // H5 medians from web/measured.json, written by scripts/measure/report.py beside docs/measured.md
  const dl = $("cost"), pending = $("cost-pending");
  const r = ctx.measured?.relight || {};
  dl.replaceChildren();
  for (const [side, f] of Object.entries(r)) {
    if (!f.reaction || !ctx.chains.chains[side]) continue;
    const div = document.createElement("div");
    const dt = document.createElement("dt"); dt.textContent = t(`cost.${side}`);
    const dd = document.createElement("dd");
    const parts = [[f.reaction, "lREACT"]];
    if (f.callback) parts.push([f.callback, ctx.chains.chains[side].native_symbol]);
    parts.forEach(([v, unit], i) => {
      if (i) dd.append(" + ");
      const n = document.createElement("span"); n.className = "mono"; n.textContent = v;
      const u = document.createElement("span"); u.className = "unit"; u.textContent = ` ${unit}`;
      const amt = document.createElement("span"); amt.className = "amt"; amt.append(n, u);
      dd.append(amt);
    });
    const note = document.createElement("dd"); note.className = "note";
    note.textContent = t(f.callback ? "cost.withCallback" : "cost.reactionOnly", { n: count(f.samples) });
    div.append(dt, dd, note); dl.append(div);
  }
  pending.hidden = dl.children.length > 0;
}

function renderLinks() {
  const ul = $("links");
  ul.replaceChildren();
  for (const [k, url] of Object.entries(ctx.site.links)) {
    if (!url) continue;
    const li = document.createElement("li");
    const a = document.createElement("a");
    a.href = url; a.rel = "noopener"; a.textContent = t(`link.${k}`);
    li.append(a); ul.append(li);
  }
}

function renderAll() {
  renderHead();
  renderFleet($("cards"), ctx.snap, ctx.chains);
  renderTry();
  renderDark();
  renderCost();
  renderLinks();
  renderGauge(ctx);
}

async function poll() {
  try {
    ctx.snap = await json(ctx.site.snapshot_url, { cache: "no-store" });
    ctx.snapFailed = false;
  } catch (_) {
    ctx.snapFailed = true;
    // keep the last snapshot on screen; the freshness line tells the reader
  }
  renderAll();
}

async function main() {
  fillLamps(document);
  ctx.site = await json("site.json", { cache: "no-cache" });
  ctx.chains = await json(ctx.site.chains_url, { cache: "no-cache" });
  try { ctx.measured = await json(ctx.site.measured_url, { cache: "no-cache" }); } catch (_) { /* cost block shows its pending line */ }
  $("cta-repo").href = ctx.site.links.repo;
  await load(saved(ctx.site.default_lang, ctx.site.langs));
  $("lang").addEventListener("click", async () => {
    const next = ctx.site.langs[(ctx.site.langs.indexOf(lang()) + 1) % ctx.site.langs.length];
    await load(next);
    renderAll();
  });
  $("dark-more").addEventListener("click", () => { ctx.darkOpen = !ctx.darkOpen; renderDark(); });
  $("copy").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText($("cmd-text").textContent);
      $("copy").textContent = t("try.copied");
      setTimeout(() => { $("copy").textContent = t("try.copy"); }, 1600);
    } catch (_) { /* clipboard blocked: the command stays selectable */ }
  });
  initGauge(ctx);
  await poll();
  setInterval(poll, ctx.site.poll_seconds * 1000);
}

main();
