// Page chrome that is not chain data: the phone menu and the Demo and footer links. Links come from site.json.
import { t } from "./i18n.js";

const $ = (id) => document.getElementById(id);

// The phone menu is a <details>: it opens without JS. JS only closes it after a jump, on Escape and on an outside tap.
export function initMenu() {
  const menu = $("mnav");
  if (!menu) return;
  menu.addEventListener("click", (e) => { if (e.target.closest("a")) menu.open = false; });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && menu.open) { menu.open = false; menu.querySelector("summary").focus(); }
  });
  document.addEventListener("click", (e) => { if (menu.open && !menu.contains(e.target)) menu.open = false; });
}

// Demo: the video once links.video is set, the README's "Cause an outage yourself" until then. Never a dead link.
export function renderPageLinks(site) {
  const video = site.links.video;
  const href = video || site.pages.outage;
  $("demo-link").href = href;
  $("demo-link").textContent = t(video ? "demo.watch" : "demo.readme");
  $("demo-poster").href = href;
  $("demo-play").hidden = !video;  // a play mark only when there is a video to play
  $("foot-repo").href = site.links.repo;
  $("foot-license").href = site.pages.license;
}
