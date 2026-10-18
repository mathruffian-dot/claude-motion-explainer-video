"""Place media into built frames: evidence cards and full-bleed backgrounds, as stills or AI video clips.

Reads "placements" from media.json (or the older images.json) and injects, into each target frame:
  - an absolutely positioned element (card or background) inside the composition root
  - a <script> that appends its entrance tween to the frame's registered GSAP timeline
Idempotent: a previous injection (between the PLACE markers) is replaced on every run, so run it
after theme.py (theme.py restores pre-theme copies and would drop the injection) and before
subset_fonts.py (captions/credits add characters).

media.json "placements": [
  {"frame": "03-suction", "image": "speirling", "mode": "card",
   "box": [640, 96, 540, 351], "at": 12.0,
   "label": "前例：McMurtry Spéirling 風扇吸地車（2022）",
   "credit": "Photo: Calreyn88 · CC BY-SA 4.0 · Wikimedia Commons"},
  {"frame": "01-hook", "image": "hook-loop", "mode": "background", "after": "01-hook-bg",
   "opacity": 0.42, "at": 0.0, "credit": "AI 生成示意圖"},
  {"frame": "06-limits", "video": "assets/videos/gen/v-landing/clip.mp4", "mode": "card",
   "box": [90, 90, 560, 315], "at": 1.7, "duration": 5.0, "out": 6.2, "label": "…", "credit": "AI 生成影片"}
]
video placements: "duration" (s on screen), optional "rate", "media_start", "brightness"; "out" fades the
whole placement before the clip ends (a finished clip is hidden and would leave an empty frame).
"hide": ids of drawn elements the media replaces; "hide_at": when to hide them.
box = [x, y, w, h] of the image in canvas px (the card's label sits under it).
  python place_media.py --project <dir>
"""
import sys
import argparse
import json
import re
from pathlib import Path
sys.stdout.reconfigure(errors="replace")  # never crash printing Chinese or accented names on a non-UTF-8 console

START, END = "<!-- PLACE:start -->", "<!-- PLACE:end -->"
JS_START, JS_END = "<!-- PLACE-JS:start -->", "<!-- PLACE-JS:end -->"


def strip_previous(t):
    t = re.sub(re.escape(START) + r".*?" + re.escape(END) + r"\n?", "", t, flags=re.S)
    return re.sub(re.escape(JS_START) + r".*?" + re.escape(JS_END) + r"\n?", "", t, flags=re.S)


def media(p, k, extra_style=""):
    """The picture inside a card/background: a treated still, or a muted video clip.

    Videos follow the HyperFrames media contract: <video class="clip" muted> with its own
    data-start / data-duration (frame-local seconds); the framework owns playback, so the
    entrance/fade tweens only ever touch the untimed wrapper, never the <video>.
    """
    if p.get("video"):
        at = float(p.get("at", 0))
        dur = float(p["duration"])
        rate = f' data-playback-rate="{p["rate"]}"' if p.get("rate") else ""
        mstart = f' data-media-start="{p["media_start"]}"' if p.get("media_start") else ""
        # id is required: the renderer discovers media by id (without one the clip renders frozen)
        return (f'<video id="{p["frame"]}-place-{k}-video" class="clip" src="{p["video"]}" muted playsinline data-start="{at}" '
                f'data-duration="{dur}" data-track-index="{30 + k}"{rate}{mstart} '
                f'style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover;{extra_style}"></video>')
    src = f"assets/images/treated/{p['image']}.jpg"
    return f'<div style="position:absolute;inset:0;background:url(\'{src}\') center/cover no-repeat;{extra_style}"></div>'


def element(p, k, theme):
    pid = f"{p['frame']}-place-{k}"
    fg, bg = theme["fg"], theme["bg"]
    fam = (theme.get("font") or {}).get("family")  # theme.json "font" wins, like all other text
    LABEL = (f"\'{fam}\'," if fam else "") + "\'Hanken Grotesk\',\'NotoSansTC\',sans-serif"
    MONO = (f"\'{fam}\'," if fam else "") + "\'DM Mono\',\'NotoSansTC\',monospace"
    if p["mode"] == "background":
        credit = ""
        if p.get("credit"):
            credit = (f'<div style="position:absolute;right:80px;top:72px;font:500 15px {MONO};'
                      f'letter-spacing:0.06em;color:{fg};opacity:0.7;">{p["credit"]}</div>')
        bright = f"filter:brightness({p['brightness']});" if p.get("brightness") else ""
        return pid, (f'<div id="{pid}" style="position:absolute;inset:0;z-index:0;opacity:0;">'
                     f'{media(p, k, bright)}{credit}</div>')
    x, y, w, h = p["box"]
    label = p.get("label", "")
    credit = p.get("credit", "")
    frame_box = (f'<div style="position:relative;flex:none;width:{w}px;height:{h}px;border:2px solid {fg};'
                 f'background:{bg};overflow:hidden;">{media(p, k)}</div>')
    if p.get("label_side") == "right":
        tw = p.get("text_width", 420)
        return pid, (
            f'<div id="{pid}" style="position:absolute;left:{x}px;top:{y}px;display:flex;gap:22px;align-items:flex-end;z-index:40;opacity:0;">'
            f'{frame_box}'
            f'<div style="width:{tw}px;padding-bottom:4px;">'
            f'<div style="font:600 22px {LABEL};color:{fg};line-height:1.35;">{label}</div>'
            f'<div style="margin-top:8px;font:400 14px {MONO};letter-spacing:0.04em;color:{fg};opacity:0.72;line-height:1.4;">{credit}</div>'
            f"</div></div>")
    html = (
        f'<div id="{pid}" style="position:absolute;left:{x}px;top:{y}px;width:{w}px;z-index:40;opacity:0;">'
        f'{frame_box}'
        f'<div style="margin-top:10px;font:600 21px {LABEL};color:{fg};line-height:1.3;">{label}</div>'
        f'<div style="margin-top:4px;font:400 14px {MONO};letter-spacing:0.04em;color:{fg};opacity:0.72;">{credit}</div>'
        f"</div>"
    )
    return pid, html


def tween(p, pid):
    at = float(p.get("at", 0))
    # "hide": ids of drawn elements the image replaces (e.g. a line-art car under a photo of a car)
    hide_at = float(p.get("hide_at", at))
    hide = "".join(
        f'(function(e){{if(e)tl.fromTo(e,{{opacity:1}},{{opacity:0,duration:0.6,ease:"power2.in"}},{hide_at});}})'
        f'(document.getElementById("{h}"));' for h in p.get("hide", []))
    # "out": fade the whole placement away (e.g. before a video clip ends — HyperFrames hides a
    # finished clip, which would leave an empty frame behind)
    out = (f'tl.to(document.getElementById("{pid}"), {{opacity:0, duration:0.45, ease:"power3.in"}}, {float(p["out"])});'
           if p.get("out") is not None else "")
    if p["mode"] == "background":
        op = p.get("opacity", 0.4)
        return hide + (f'tl.fromTo(document.getElementById("{pid}"), {{opacity:0}}, '
                       f'{{opacity:{op}, duration:0.9, ease:"power2.out"}}, {at});') + out
    return hide + (f'tl.fromTo(document.getElementById("{pid}"), {{opacity:0, y:24, clipPath:"inset(0 100% 0 0)"}}, '
                   f'{{opacity:1, y:0, clipPath:"inset(0 0% 0 0)", duration:0.8, ease:"expo.out"}}, {at});') + out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", default=".")
    a = ap.parse_args()
    project = Path(a.project).resolve()
    theme = json.loads((project / "theme.json").read_text(encoding="utf-8"))
    spec_path = project / "media.json"
    if not spec_path.exists():
        spec_path = project / "images.json"
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    by_frame = {}
    for k, p in enumerate(spec.get("placements", [])):
        if p.get("video") and p.get("out") is not None and p.get("duration"):
            end = float(p.get("at", 0)) + float(p["duration"])
            if float(p["out"]) + 0.45 > end + 1e-6:
                print(f'warning: {p["frame"]} {p["video"]}: "out" {p["out"]} + 0.45 s fade ends after the clip '
                      f'({end:.2f} s) — the card shows an empty box; use "out" <= {end - 0.5:.2f}')
        by_frame.setdefault(p["frame"], []).append((k, p))
    for f in sorted((project / "compositions" / "frames").glob("*.html")):
        t = strip_previous(f.read_text(encoding="utf-8"))
        items = by_frame.get(f.stem, [])
        if items:
            els, tws = [], []
            for k, p in items:
                pid, html = element(p, k, theme)
                els.append((p, html))
                tws.append(tween(p, pid))
            for p, html in els:
                block = f"{START}\n{html}\n{END}\n"
                if p["mode"] == "background" and p.get("after"):
                    # insert as the anchor's next SIBLING (after its matching </div>), never inside it:
                    # the anchor is usually a timed clip, and a <video> nested in a timed element
                    # plays the wrong frames (lint: video_nested_in_timed_element)
                    m = re.search(rf'<div[^>]*id="{re.escape(p["after"])}"[^>]*>', t)
                    assert m, f"{f.name}: anchor #{p['after']} not found"
                    depth, i = 1, m.end()
                    for tag in re.finditer(r"<(/?)div\b[^>]*>", t[m.end():]):
                        depth += -1 if tag.group(1) else 1
                        if depth == 0:
                            i = m.end() + tag.end()
                            break
                    t = t[:i] + "\n" + block + t[i:]
                else:
                    m = re.search(r'<div[^>]*id="root"[^>]*>', t)
                    assert m, f"{f.name}: composition root not found"
                    t = t[:m.end()] + "\n" + block + t[m.end():]
            js = (f'{JS_START}\n<script>(function(){{var tl=window.__timelines["{f.stem}"];'
                  f'if(!tl)return;{"".join(tws)}}})();</script>\n{JS_END}\n')
            i = t.rindex("</template>")
            t = t[:i] + js + t[i:]
        f.write_text(t, encoding="utf-8")
        if items:
            print("placed", len(items), "item(s) in", f.name)


if __name__ == "__main__":
    main()
