# ADR 0016: The demo video goes through the shared pipeline, with the v1 picture

Status: accepted, 27 Nov 2026

## Context

ADR 0015 decided to run the demo video through the shared video pipeline (`pakej video`) before the hand-over, so the
file the judges watch carries a `video/JANA.json` with its hash and a voice made by the owner's cloned voice (`vp`).

The pipeline has four steps: `init` (scaffold), `suara` (voice lines through `vp`, cached by hash), `bina` (render a
Hyperframes film from `video/index.tmpl`) and `akhir` (two-pass loudness to the shared target, then measure and write
`JANA.json`). `akhir --masuk <file>` finishes a picture made elsewhere.

The v1 film (`docs/media/video`) was cut by hand: nine scenes over 80 s, real captures of the page and of the explorers,
music, and the nine narration lines made by `vp` with the owner's cloned voice. The pipeline's `bina` template is a
two-scene, 8 s film; rebuilding the nine scenes in Hyperframes would redraw the same captures and timings for no gain
to the judges, and a new cut could drift from the figures `docs/measured.md` sources.

## Decision

1. `init` scaffolds `video/`. `video/skrip.json` holds the same nine lines as `docs/hantar/SKRIP-VIDEO.md` (subtitle
   and spoken text), copied from the v1 script; `video/filem.json` records the real scene windows and voice starts.
2. `suara` runs `vp` against those lines. The v1 voice files were made by `vp` with the same voice and the same text,
   so all nine lines hit the hash cache: no new voice credit, and the voice in the picture is exactly the voice the
   pipeline records (`JANA.json` `suara.penjana` = `vp`, nine line hashes).
3. `bina` is not run. `akhir --masuk docs/media/video/keluar/pelita-demo-desktop-16x9-muzik.mp4` finishes the v1
   picture (video stream copied, not re-encoded): -15.3 LUFS / -0.7 dBTP before, -16.5 LUFS / -2.2 dBTP after,
   audio 80.0 s = video 80.0 s.
4. `video/demo.mp4` is the file handed to the owner (FILE DROP `pelita-demo.mp4`, subtitles unchanged since the
   timings did not move). The mp4 and the voice cache stay out of git (`video/.gitignore`); `JANA.json` holds the
   mp4 hash, so a stale copy is caught.

The submission checklist reads both lines as passed (`video:enjin`, `video:suara_vp`), with V3 to V5 passing on
the final file.

## Rollback

The v1 file is kept at `docs/media/video/keluar/pelita-demo.mp4` (same picture, -15.3 LUFS mix). Copying it back to
the FILE DROP restores v1; the checklist then needs `enjin_sebab` with a written reason, as ADR 0015 says.
