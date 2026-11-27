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

## Addendum (27 Nov 2026): sections, FAQ, Demo and footer

- **Order** follows the story a visitor needs: hero, how it works, fleet (live proof), try it yourself, fuel gauge,
  dark list, cost and limits, questions, demo, footer. The cost, limits and reading links moved out of "How it works"
  into their own section, so the diagram stands alone right under the hero.
- **Nav:** How it works, Fleet, Try it, FAQ, Demo. On phones the same links sit in a `<details>` menu that opens without
  JS; `js/page.js` only closes it after a jump, on Escape and on an outside tap. No sticky or glass header.
- **FAQ:** seven `<details>` questions in English and Malay, answered only from the README and the measured results.
  Answers carry no figures (the cost block reads them from `measured.json`), so they cannot go stale.
- **Demo:** the real poster of the demo video, linked to `links.video` once it is set, and to the README section
  "Cause an outage yourself" (`site.json pages.outage`) until then; the play mark shows only when there is a video.
  An outbound link, never an iframe (the Content-Security-Policy allows no frames).
- **Footer:** the mark, the event line, GitHub and the MIT licence, with targets read from `site.json`.
- `scripts/web-smoke.py` now checks Chromium 1440 and WebKit iPhone 13 and 320 px, each in light and dark, in English
  and Malay: no overflow with every answer open or with the menu open after scrolling, touch targets of at least
  44 px, the theme switch, each forced proof state, and a 10 s wait in WebKit.

## Rollback

`bash deploy/deploy.sh --rollback` returns the previous image. In the repository, revert the commit that adds this
record; the previous fonts and `site.css` come back with it.
