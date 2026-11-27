# ADR 0017: The page opens on the product in device frames, with generated tokens and light and dark themes

Date: 27 Nov 2026
Status: accepted

## Context

The live page was tidy (lamp glyph, amber, warm dark) but the first screen showed a large lamp illustration, not the
product. It had no light theme, three font families, a forced-capitals label above the heading, and no call to action.
Judges compare entry pages side by side, and the strongest rival page in the event opens on its product with two
actions and a live proof line.

## Decision

- **Tokens are generated, not written by hand.** `web/css/token.css` is produced from the shared entry design tokens
  plus `brand/identity.json` (name, the existing amber `#F2A93B` as the one accent, the existing 14 px radius). Its
  comment is written by the generator and kept byte for byte. Every other stylesheet uses `var(--…)` only; the role
  names in `site.css` (`--surface`, `--ash`, …) are mixes of the token colours, so both themes follow automatically.
  Amber fails contrast as text on the light background, so it is used as a fill (flames, buttons, dots, rules) and
  links are text-coloured with an amber underline.
- **Two fonts:** Figtree for headings and text, Geist Mono for addresses, hashes, numbers and commands, both
  self-hosted (OFL). Newsreader, Public Sans and IBM Plex Mono are removed.
- **Light and dark:** the system preference by default, a switch in the header (44 px) that is remembered.
  `web/js/theme-boot.js` sets `data-tema` on `<html>` before the first paint; it is a file, not an inline script,
  because the Content-Security-Policy allows `'self'` scripts only. The lamp glyph keeps its meaning in both themes:
  amber flame = lit, grey body without flame = dark.
- **Hero = the real product.** A CSS browser frame (desktop page) and a CSS phone frame (phone page) sit on an amber
  slab that carries the big lamp as a quiet mark. The images are named in `web/site.json` `shots` with their sizes;
  a test keeps the page, the settings and the files in step. The first shots are captures of the previous page; they
  are replaced by captures of this look once it is live. The heading is unchanged; the lede is taken from the README
  (who it is for, what happens, and that nothing is billed while nothing goes dark). Two actions: try it yourself
  (`#try`) and read the code (`links.repo`).
- **Live proof row** under the hero = the existing stats (lit, dark, last relight, relights, Keeper tank) with
  designed states: reading, live, nothing watched yet, data unavailable. `?keadaan=muat|kosong|ralat` forces a state
  so each one can be checked in a browser.
- The pill above the heading is in sentence case; no stylesheet uses `text-transform: uppercase`.
- Images under `img/` are versioned like the other assets (`deploy/stamp.py`), because Cloudflare caches by URL.

## Consequences

- One more stylesheet (`frames.css`: header, hero, frames, proof row) keeps `site.css` short.
- Section order, FAQ and demo come in a later change; this one keeps the existing sections and restyles them.

## Rollback

`bash deploy/deploy.sh --rollback` returns the previous image. In the repository, revert the commit that adds this
record; the previous fonts and `site.css` come back with it.
