// Loaded synchronously in <head> so the saved theme applies before the first paint (CSP allows no inline script).
// No saved choice = follow the system (prefers-color-scheme in token.css).
(function () {
  try {
    var v = localStorage.getItem("pelita.theme");
    if (v === "terang" || v === "gelap") document.documentElement.dataset.tema = v;
  } catch (e) { /* storage blocked: follow the system */ }
})();
