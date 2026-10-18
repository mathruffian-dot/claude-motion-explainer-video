"""AI video clips for an explainer: MiniMax H3 shot specs -> prompts -> clips -> visual check.

AI video is the default way to bring live footage into a film: it avoids the licensing problems of
stock or news footage. Each clip starts from a still (usually the matching Codex image) pinned as
its first frame, so the clip keeps the film's look.

Shot spec — <project>/assets/videos/gen/specs/<name>.json (keep specs OUTSIDE the clip folder):
{
  "duration": 5.0, "size": [1344, 768], "seed": 2026,
  "style": "a cinematic, photoreal night-time automotive commercial shot, ...",
  "setting": "a dark wet runway at night with small orange edge lights",
  "first_frame": "../../../images/gen/hover-jets.png",      # relative to the spec file
  "subjects": [{"key": "car", "desc": "a sleek unbranded electric hypercar, no badges or text"}],
  "shots": [{"camera": "The camera holds a static shot on a tripod.",
             "action": "The car hovers ... the jets stop, the car drops and lands ...", "at": null}],
  "soundscape": "A loud hiss of compressed air that sputters out, a heavy thump ...",
  "music": "N/A"
  # runner-specific extras pass through untouched (e.g. "draft": true for a fast mode)
}

  python ai_video.py prompt --project <dir> [--only v-landing]   # official H3 prompt -> <name>/prompt.txt (no GPU)
  python ai_video.py run    --project <dir> [--only v-landing]   # generate with the runner in video_config.json
  python ai_video.py check  --project <dir> [--only v-landing]   # probe + contact sheet of each clip

video_config.json (project root) — how THIS machine generates H3 clips. Placeholders: {spec} (spec JSON),
{out} (clip folder), {prompt} (<out>/prompt.txt, the official prompt), {first_frame} (absolute path of the
still, "" if none). The runner must leave <out>/clip.mp4 (H.264 MP4, any audio — it is muted when placed):
  {"runner": ["<python of your H3 env>", "<path/to/your_h3_runner.py>", "{spec}", "--out", "{out}"]}
No runner: `prompt` still writes prompt.txt + the first frame path; generate by hand (e.g. ComfyUI's
official MiniMax H3 R2V template) and save the result as assets/videos/gen/<name>/clip.mp4.
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
sys.stdout.reconfigure(errors="replace")  # never crash printing Chinese or accented names on a non-UTF-8 console

SECTIONS = ["subject_definitions", "summary", "retention_analysis", "detailed_description",
            "overall_soundscape", "non_diegetic_music"]


def build_prompt(spec):
    """MiniMax H3 Ref2VA prompt in the official six-section layout (first frame = <Picture 1>)."""
    subs = spec.get("subjects", [])
    has_first = bool(spec.get("first_frame"))
    defs = [f"<Subject {i + 1}> is {s['desc']}{', visible in <Picture 1>' if has_first and s.get('in_first_frame', True) else ''}."
            for i, s in enumerate(subs)]
    if has_first:
        defs.append("<Picture 1> is the first frame of [Shot 1], fixing the camera position, framing, set layout and lighting.")
    shots = spec["shots"]
    one = len(shots) == 1
    summary = (f"[keyframe completion] The target video is {'one continuous shot' if one else f'{len(shots)} shots'} "
               f"set in {spec.get('setting', 'the scene')}" + (", beginning from <Picture 1>." if has_first else "."))
    keep = [f"<Subject {i + 1}> (appears in [Shot 1]): fully_preserved - identity, shape, colour and materials are retained."
            for i in range(len(subs))]
    if has_first:
        keep.append("<Picture 1> ([Shot 1] first frame): fully_preserved - camera position, framing, set layout and lighting are retained.")
    desc = [f"The target video is in the style of {spec.get('style', 'a cinematic, photoreal shot')}."]
    for k, s in enumerate(shots):
        head = f"[Shot {k + 1}]"
        if k == 0 and has_first:
            head += " The shot begins from <Picture 1>."
        elif s.get("at") is not None:
            m, sec = divmod(float(s["at"]), 60)
            head += f" At {int(m):02d}:{sec:06.3f}, the camera cuts to a new view."
        names = " ".join(f"{subs[i]['desc'].split(',')[0][0].upper()}{subs[i]['desc'].split(',')[0][1:]} is <Subject {i + 1}>."
                         for i in range(len(subs))) if k == 0 else ""
        desc.append(" ".join(x for x in [head, names, s.get("camera", ""), s.get("action", "")] if x))
    body = {
        "subject_definitions": "\n".join(defs),
        "summary": summary,
        "retention_analysis": "\n".join(keep),
        "detailed_description": "\n".join(desc),
        "overall_soundscape": spec.get("soundscape", "Quiet ambient room tone."),
        "non_diegetic_music": spec.get("music", "N/A"),
    }
    return "\n\n".join(f"{k}:\n{body[k]}" for k in SECTIONS) + "\n"


def specs(project, only):
    d = project / "assets" / "videos" / "gen" / "specs"
    out = sorted(d.glob("*.json"))
    return [p for p in out if not only or p.stem in only]


def clip_dir(project, name):
    p = project / "assets" / "videos" / "gen" / name
    p.mkdir(parents=True, exist_ok=True)
    return p


def cmd_prompt(project, only):
    for sp in specs(project, only):
        spec = json.loads(sp.read_text(encoding="utf-8"))
        if not 4 <= float(spec["duration"]) <= 15:
            print(f"! {sp.stem}: H3 clips are 4–15 s (got {spec['duration']})")
        ff = spec.get("first_frame")
        if ff and not (sp.parent / ff).exists():
            sys.exit(f"{sp.stem}: first frame not found: {(sp.parent / ff).resolve()}")
        out = clip_dir(project, sp.stem) / "prompt.txt"
        out.write_text(build_prompt(spec), encoding="utf-8")
        print(f"{sp.stem}: {out}" + (f"  (first frame {(sp.parent / ff).resolve()})" if ff else ""))


def cmd_run(project, only):
    cfg_path = project / "video_config.json"
    if not cfg_path.exists():
        sys.exit("no video_config.json — set a runner (see this script's help) or generate by hand from prompt.txt")
    runner = json.loads(cfg_path.read_text(encoding="utf-8"))["runner"]
    for sp in specs(project, only):
        out = clip_dir(project, sp.stem)
        if (out / "clip.mp4").exists():
            print(f"[skip] {sp.stem} (delete clip.mp4 to regenerate)")
            continue
        spec = json.loads(sp.read_text(encoding="utf-8"))
        prompt = out / "prompt.txt"
        if not prompt.exists():
            prompt.write_text(build_prompt(spec), encoding="utf-8")
        ff = (sp.parent / spec["first_frame"]).resolve() if spec.get("first_frame") else ""
        # runner contract: {spec} spec JSON, {out} clip folder (must end with clip.mp4 in it),
        # {prompt} the official six-section prompt, {first_frame} absolute path of the still ("" if none)
        cmd = [a.replace("{spec}", str(sp)).replace("{out}", str(out)).replace("{prompt}", str(prompt))
               .replace("{first_frame}", str(ff)) for a in runner]
        print(f"[run] {sp.stem}")
        with open(out / "gen.log", "w", encoding="utf-8") as log:
            subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        print(("[ok]   " if (out / "clip.mp4").exists() else "[fail] ") + str(out / "clip.mp4"))


def cmd_check(project, only):
    sheet = Path(__file__).resolve().parents[2] / "review-loop" / "scripts" / "sheet.py"
    for sp in specs(project, only):
        clip = project / "assets" / "videos" / "gen" / sp.stem / "clip.mp4"
        if not clip.exists():
            print(f"[missing] {clip}")
            continue
        dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                    "default=nw=1:nk=1", str(clip)], capture_output=True, text=True).stdout.strip())
        wh = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                             "-of", "csv=p=0", str(clip)], capture_output=True, text=True).stdout.strip()
        print(f"{sp.stem}: {dur:.2f}s {wh}")
        if sheet.exists() and shutil.which("ffmpeg"):
            step = max(0.2, (dur - 0.4) / 7)
            subprocess.run([sys.executable, str(sheet), "--video", str(clip), "--from", "0.2", "--to", f"{dur - 0.2:.2f}",
                            "--every", f"{step:.2f}", "--out", str(clip.parent), "--name", "check", "--width", "480"])
    print("Look at every check-1.png: morphing objects, extra wheels/limbs, text or logos, warping. Re-roll a bad clip "
          "with a new seed (delete its clip.mp4) — never ship one you have not looked at.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["prompt", "run", "check"])
    ap.add_argument("--project", default=".")
    ap.add_argument("--only", nargs="+")
    a = ap.parse_args()
    project = Path(a.project).resolve()
    {"prompt": cmd_prompt, "run": cmd_run, "check": cmd_check}[a.cmd](project, a.only)


if __name__ == "__main__":
    main()
