#!/usr/bin/env bash
# Final mix for the judges' video: the vp picture + the music mix, loudness-normalised to the targets in garis.json
# ("akhir": LUFS and true peak), then measured. Usage: bash docs/media/video/muktamad.sh
set -euo pipefail
cd "$(dirname "$0")"
read -r I TP < <(python3 -c 'import json;a=json.load(open("garis.json"))["akhir"];print(a["lufs"],a["dbtp"])')
src=keluar/pelita-demo-desktop-16x9-muzik.mp4
out=keluar/pelita-demo.mp4
m=$(ffmpeg -hide_banner -i work/audio-muzik.wav -af "loudnorm=I=$I:TP=$TP:LRA=11:print_format=json" -f null - 2>&1 | sed -n '/^{/,/^}/p')
p=$(python3 -c 'import json,sys;d=json.load(sys.stdin);print(":".join(f"measured_{k}={d[v]}" for k,v in (("I","input_i"),("TP","input_tp"),("LRA","input_lra"),("thresh","input_thresh")))+":offset="+d["target_offset"])' <<<"$m")
ffmpeg -v error -y -i "$src" -i work/audio-muzik.wav -map 0:v -map 1:a -c:v copy \
  -af "loudnorm=I=$I:TP=$TP:LRA=11:$p:linear=true,aresample=48000" -c:a aac -b:a 192k -shortest -movflags +faststart "$out"
ffprobe -v error -show_entries stream=codec_type,width,height,duration -of csv=p=0 "$out"
ffmpeg -hide_banner -i "$out" -af ebur128=peak=true -f null - 2>&1 | grep -A14 Summary | grep -E 'I:|Peak:'
