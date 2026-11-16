// The lamp glyph, inlined (not <use>) so page CSS can colour and animate its parts. Amber = lit, grey = dark.
const PATHS = `
  <path class="lamp-body" d="M2.5 13.6h12.4c1.7 0 3.1-.5 4.4-1.5l1.6-1.2-.5 2.1c-.9 3.6-4.1 6.2-7.9 6.2H8.3c-3.2 0-5.8-2.4-5.8-5.6Z"/>
  <path class="lamp-body" d="M8 20.6h6.4l.8 1.9H7.2Z"/>
  <g class="lamp-flame"><path d="M20.2 2.6c1.9 2.3 2.9 4.2 2.9 5.7a2.9 2.9 0 0 1-5.8 0c0-1.5 1-3.4 2.9-5.7Z"/><path class="lamp-core" d="M20.2 6.4c.8 1 1.2 1.8 1.2 2.4a1.2 1.2 0 0 1-2.4 0c0-.6.4-1.4 1.2-2.4Z"/></g>
  <path class="lamp-wisp" d="M20.4 9.6c-1.2-1.1.9-2.1-.2-3.6"/>`;

export function lamp(lit, extra = "") {
  return `<svg class="glyph ${lit ? "is-lit" : "is-dark"} ${extra}" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${PATHS}</svg>`;
}

export function fillLamps(root) {
  root.querySelectorAll("[data-lamp]").forEach((el) => {
    el.outerHTML = lamp(el.dataset.lamp === "lit", el.dataset.lampClass || "");
  });
}
