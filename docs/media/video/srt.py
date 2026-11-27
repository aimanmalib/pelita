"""Write keluar/pelita-demo.srt from the narration's word timings (work/data.js from `vp data`), cut like the burned-in captions:
at most 8 words, or at the end of a sentence. Run after `vp data`: python3 docs/media/video/srt.py"""
import json
import re
from pathlib import Path

HERE = Path(__file__).parent
data = json.loads(re.sub(r"^[^{]*", "", (HERE / "work" / "data.js").read_text(encoding="utf-8")).rstrip().rstrip(";"))
cues = []
for line in data["garis"]["sari_kata"] + ["tutup"]:
    cur = []
    for i, w in enumerate(data["kata"][line]):
        cur.append(w)
        if len(cur) >= 8 or (re.search(r"[.,:?!]$", w["w"]) and len(cur) >= 2) or i == len(data["kata"][line]) - 1:
            cues.append(cur)
            cur = []


def ts(s):
    ms = round(s * 1000)
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


out = []
for n, c in enumerate(cues, 1):
    end = min(c[-1]["b"] + 0.6, cues[n][0]["a"] - 0.08) if n < len(cues) else c[-1]["b"] + 0.6
    out.append(f"{n}\n{ts(c[0]['a'] - 0.08)} --> {ts(end)}\n{' '.join(w['w'] for w in c)}\n")
(HERE / "keluar").mkdir(exist_ok=True)
(HERE / "keluar" / "pelita-demo.srt").write_text("\n".join(out), encoding="utf-8")
print(len(cues), "cues")
