// Theme switch: flips light/dark and remembers the choice. The button's name comes from the two hidden labels
// in the page (theme.toDark / theme.toLight in web/lang), shown by CSS for the current theme.
const KEY = "pelita.theme";
const root = document.documentElement;
const button = document.getElementById("theme");

function isDark() {
  return root.dataset.tema ? root.dataset.tema === "gelap" : matchMedia("(prefers-color-scheme: dark)").matches;
}

if (button) {
  button.addEventListener("click", () => {
    root.dataset.tema = isDark() ? "terang" : "gelap";
    try { localStorage.setItem(KEY, root.dataset.tema); } catch (_) { /* storage blocked: the theme holds for this visit */ }
  });
}
