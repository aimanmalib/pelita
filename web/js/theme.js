// Theme switch: flips light/dark and remembers the choice. The button's name comes from the two hidden labels
// in the page (theme.toDark / theme.toLight in web/lang), shown by CSS for the current theme.
const KEY = "pelita.theme";
const root = document.documentElement;
const button = document.getElementById("theme");

function isDark() {
  return root.dataset.tema ? root.dataset.tema === "gelap" : matchMedia("(prefers-color-scheme: dark)").matches;
}

// The hero shots come in light and dark (<source data-shot-dark>). The media query follows the system; a chosen
// theme overrides it so the screens in the frames match the page around them.
const SYSTEM = "(prefers-color-scheme: dark)";
function syncShots() {
  const media = root.dataset.tema ? (root.dataset.tema === "gelap" ? "all" : "not all") : SYSTEM;
  for (const source of document.querySelectorAll("source[data-shot-dark]")) source.media = media;
}
syncShots();

if (button) {
  button.addEventListener("click", () => {
    root.dataset.tema = isDark() ? "terang" : "gelap";
    try { localStorage.setItem(KEY, root.dataset.tema); } catch (_) { /* storage blocked: the theme holds for this visit */ }
    syncShots();
  });
}
