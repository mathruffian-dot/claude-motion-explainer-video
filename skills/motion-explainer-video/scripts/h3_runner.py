"""Reference runner: one MiniMax H3 clip from a shot spec, on a ComfyUI server (local or remote).

ai_video.py calls it through video_config.json (see templates/video_config.example.json):
  python h3_runner.py {spec} --out {out} --prompt {prompt} --first-frame {first_frame} [--comfy URL]
Stand-alone:
  python h3_runner.py spec.json --out <dir> [--prompt prompt.txt]        # prompt defaults to <dir>/prompt.txt,
                                                                       # else it is built from the spec
  python h3_runner.py spec.json --out <dir> --dry-run    # write workflow_api.json only (no server)
  python h3_runner.py --check [--comfy URL]              # is the server up, with the nodes and model files?
  python h3_runner.py --lint prompt.txt [--duration 5]   # check a hand-written prompt (official 6-section layout)

What it builds: the graph of ComfyUI's official "MiniMax H3 Reference to Video" template
(MiniMaxH3ReferenceToVideo + res_multistep + simple scheduler), with the first frame passed as
<Picture 1> AND pinned at frame 0 (MiniMaxH3AddGuide), so the clip starts exactly on the still.
Everything goes through ComfyUI's HTTP API (upload the stills, queue, poll, download), so the
server may run on another machine (e.g. a cloud GPU) — no shared folders. Python stdlib only.

Spec keys it reads (the rest belongs to the prompt): duration (s; frames = 17n+5 at 24 fps),
size [w, h], seed, steps (default 20, the official template), first_frame / last_frame (paths
relative to the spec), "draft": true (official Lightning LoRA, 4 steps: about 4x faster, for
previews), "lora": {"name", "strength"} or a list (your own LoRAs), "sampler".

Models (defaults = the official template's files from huggingface.co/Comfy-Org/MiniMax-H3; put them in
ComfyUI's models/ folders): override with --unet / --clip / --video-vae / --audio-vae / --draft-lora,
or env H3_UNET, H3_CLIP, H3_VIDEO_VAE, H3_AUDIO_VAE, H3_DRAFT_LORA. Server: --comfy or env COMFY_URL.
Measured on an RTX 5090 (32 GB): ~26 GB VRAM while generating; a 5 s clip at 1344x768 takes about a
minute in draft mode
(measured: 76 s draft vs 297 s at 20 steps, model already loaded). H3 is under the MiniMax H3 Community License — read it before use.
Writes <out>/clip.mp4 (H.264 + H3's own audio; muted later when placed), workflow_api.json, meta.json.
"""
import argparse
import json
import mimetypes
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
sys.stdout.reconfigure(errors="replace")  # never crash printing Chinese or accented names on a non-UTF-8 console

FPS = 24
SECTIONS = ["subject_definitions", "summary", "retention_analysis", "detailed_description",
            "overall_soundscape", "non_diegetic_music"]
DEFAULTS = {
    "unet": "minimax_h3_ref2va_pruned_int8_convrot.safetensors",
    "clip": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
    "video_vae": "minimax_h3_video_vae_int8_convrot.safetensors",
    "audio_vae": "minimax_h3_audio_vae_fp32.safetensors",
    "draft_lora": "minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors",
}
NODES = ["UNETLoader", "CLIPLoader", "VAELoader", "MiniMaxH3ReferenceToVideo", "MiniMaxH3AddGuide", "LoadImage",
         "RandomNoise", "KSamplerSelect", "BasicScheduler", "BasicGuider", "SamplerCustomAdvanced", "VAEDecode",
         "VAEDecodeAudio", "CreateVideo", "SaveVideo", "LoraLoaderModelOnly"]


def frames_for(duration):
    """H3 wants 17n + 5 frames: the smallest such count covering the duration at 24 fps."""
    n = 0
    while 17 * n + 5 < duration * FPS:
        n += 1
    return 17 * n + 5


# ------------------------------------------------------------------------------------------ server
class Comfy:
    def __init__(self, url):
        self.url = url.rstrip("/")

    def get(self, path, timeout=60):
        with urllib.request.urlopen(self.url + path, timeout=timeout) as r:
            return r.read()

    def json(self, path, data=None, timeout=60):
        req = urllib.request.Request(self.url + path, headers={"Content-Type": "application/json"},
                                     data=json.dumps(data).encode() if data is not None else None)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())

    def upload(self, path, name):
        """POST /upload/image (multipart). Returns the LoadImage value "subfolder/name"."""
        boundary = uuid.uuid4().hex
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{name}"\r\n'
                 f"Content-Type: {ctype}\r\n\r\n".encode() + Path(path).read_bytes() + b"\r\n"]
        for k, v in (("subfolder", "h3_runner"), ("type", "input"), ("overwrite", "true")):
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
        body = b"".join(parts) + f"--{boundary}--\r\n".encode()
        req = urllib.request.Request(self.url + "/upload/image", data=body,
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        with urllib.request.urlopen(req, timeout=120) as r:
            d = json.loads(r.read().decode())
        return f'{d["subfolder"]}/{d["name"]}' if d.get("subfolder") else d["name"]

    def options(self, node, field):
        info = self.json(f"/object_info/{node}", timeout=20).get(node, {})
        spec = info.get("input", {}).get("required", {}).get(field)
        if not spec:
            return []
        return spec[0] if isinstance(spec[0], list) else spec[1].get("options", [])


# ------------------------------------------------------------------------------------------ graph
def build_graph(spec, prompt, models, images, tag):
    """images: {"first": LoadImage value or None, "last": ... or None}."""
    w, h = spec.get("size", [1344, 768])
    length = frames_for(float(spec["duration"]))
    steps = spec.get("steps", 20)
    loras = spec.get("lora") or []
    loras = loras if isinstance(loras, list) else [loras]
    if spec.get("draft"):
        loras = [{"name": models["draft_lora"], "strength": 1.0}] + loras
        steps = 4
    g = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": models["unet"], "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": models["clip"], "type": "minimax", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": models["video_vae"]}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": models["audio_vae"]}},
        "6": {"class_type": "MiniMaxH3ReferenceToVideo", "inputs": {
            "clip": ["2", 0], "vae": ["3", 0], "audio_vae": ["4", 0], "prompt": prompt,
            "width": w, "height": h, "length": length, "ref_image_size": "match"}},
        "7": {"class_type": "RandomNoise", "inputs": {"noise_seed": int(spec.get("seed", 42))}},
        "8": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": spec.get("sampler", "res_multistep")}},
        "12": {"class_type": "VAEDecode", "inputs": {"samples": ["11", 0], "vae": ["3", 0]}},
        "13": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["11", 0], "vae": ["4", 0]}},
        "14": {"class_type": "CreateVideo", "inputs": {"images": ["12", 0], "audio": ["13", 0], "fps": FPS}},
        "15": {"class_type": "SaveVideo", "inputs": {"video": ["14", 0], "filename_prefix": f"h3_runner/{tag}",
                                                     "format": "mp4", "codec": "h264"}},
    }
    model = ["1", 0]
    for i, lr in enumerate(loras):
        nid = str(80 + i)
        g[nid] = {"class_type": "LoraLoaderModelOnly",
                  "inputs": {"model": model, "lora_name": lr["name"], "strength_model": lr.get("strength", 1.0)}}
        model = [nid, 0]
    g["9"] = {"class_type": "BasicScheduler", "inputs": {"model": model, "scheduler": "simple", "steps": steps, "denoise": 1.0}}
    cond, latent = ["6", 0], ["6", 1]
    if images.get("first"):   # <Picture 1> for the prompt, and pinned at frame 0
        g["5"] = {"class_type": "LoadImage", "inputs": {"image": images["first"]}}
        g["6"]["inputs"]["ref_images.ref_image_0"] = ["5", 0]
        g["40"] = {"class_type": "MiniMaxH3AddGuide", "inputs": {"positive": cond, "latent": latent, "vae": ["3", 0],
                                                                 "image": ["5", 0], "frame_idx": 0}}
        cond = ["40", 0]
    if images.get("last"):    # optional fixed end state
        g["43"] = {"class_type": "LoadImage", "inputs": {"image": images["last"]}}
        g["42"] = {"class_type": "MiniMaxH3AddGuide", "inputs": {"positive": cond, "latent": latent, "vae": ["3", 0],
                                                                 "image": ["43", 0], "frame_idx": -1}}
        cond = ["42", 0]
    g["10"] = {"class_type": "BasicGuider", "inputs": {"model": model, "conditioning": cond}}
    g["11"] = {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["7", 0], "guider": ["10", 0], "sampler": ["8", 0],
                                                                 "sigmas": ["9", 0], "latent_image": latent}}
    return g, length, steps


# ------------------------------------------------------------------------------------------ lint
def lint(prompt, duration=None):
    """(errors, warnings) against the official Ref2VA prompt layout (MiniMax-H3 h3-prompt-writing skill)."""
    E, W = [], []
    heads = [(m.group(1), m.group(2), m.start()) for m in re.finditer(r"^([a-z_]+)(:?)[ \t]*$", prompt, re.M)
             if m.group(1) in SECTIONS]
    if [h[0] for h in heads] != SECTIONS:
        E.append(f"sections must be exactly {SECTIONS} in this order; found {[h[0] for h in heads]}")
    E += [f"section '{n}' must end with a colon" for n, colon, _ in heads if not colon]
    body = {}
    for i, (n, _, p) in enumerate(heads):
        end = heads[i + 1][2] if i + 1 < len(heads) else len(prompt)
        body[n] = prompt[p:end].split("\n", 1)[1] if "\n" in prompt[p:end] else ""
    defs = body.get("subject_definitions", "")
    defined = set(re.findall(r"^(<(?:Subject|Picture|Video|Audio) \d+>) is", defs, re.M))
    defined |= set(re.findall(r"<(?:Picture|Video) \d+>", defs))
    E += [f"label {x} is used but never defined in subject_definitions"
          for x in sorted(set(re.findall(r"<(?:Subject|Picture|Video|Audio) \d+>", prompt))) if x not in defined]
    if prompt.count("<d>") != prompt.count("</d>"):
        E.append("unbalanced <d> dialogue tags")
    for n in ("overall_soundscape", "non_diegetic_music"):
        if "<d>" in body.get(n, ""):
            E.append(f"{n} must not contain dialogue")
    dd = body.get("detailed_description", "")
    shots = re.findall(r"\[Shot (\d+)\]( At (\d+):(\d+\.\d+))?", dd)
    if not shots:
        E.append("detailed_description needs [Shot 1]")
    prev = 0.0
    for k, (num, has_t, mm, ss) in enumerate(shots, start=1):
        if int(num) != k:
            E.append(f"shot numbers must be sequential: [Shot {num}] at position {k}")
        if k > 1:
            if not has_t:
                E.append(f"[Shot {num}] needs 'At MM:SS.mmm,'")
                continue
            t = int(mm) * 60 + float(ss)
            if t <= prev or (duration and t >= duration):
                E.append(f"[Shot {num}] cut time {t}s must increase and stay inside the clip")
            prev = t
    if re.search(r"[一-鿿]", re.sub(r"<d>.*?</d>", "", prompt, flags=re.S)):
        W.append("Chinese outside <d>…</d>: write the prompt in English, keep only spoken lines in Chinese")
    if len(dd.split()) < 40:
        W.append(f"detailed_description is short ({len(dd.split())} words); concrete detail helps")
    return E, W


# ------------------------------------------------------------------------------------------ main
def models_from(a):
    return {k: getattr(a, k) or os.environ.get(f"H3_{k.upper()}") or v for k, v in DEFAULTS.items()}


def check(comfy, models):
    try:
        stats = comfy.json("/system_stats", timeout=10)
    except Exception as e:
        sys.exit(f"ComfyUI not reachable at {comfy.url} ({e}) — start it, or pass --comfy http://host:port")
    print(f"ComfyUI {stats.get('system', {}).get('comfyui_version', '?')} at {comfy.url}")
    ok = True
    for n in NODES:
        if not comfy.json(f"/object_info/{n}", timeout=20):
            print(f"  missing node {n} — update ComfyUI (MiniMax H3 nodes are built in since 0.36)")
            ok = False
    have = {"unet": comfy.options("UNETLoader", "unet_name"), "clip": comfy.options("CLIPLoader", "clip_name"),
            "video_vae": comfy.options("VAELoader", "vae_name"), "audio_vae": comfy.options("VAELoader", "vae_name"),
            "draft_lora": comfy.options("LoraLoaderModelOnly", "lora_name")}
    for k, name in models.items():
        found = name in have[k]
        print(f"  {'ok     ' if found else 'MISSING'} {k:10} {name}")
        ok &= found or k == "draft_lora"
    if models["draft_lora"] not in have["draft_lora"]:
        print("  (draft mode needs the LoRA above; full-quality clips do not)")
    print("ready" if ok else "not ready — download the missing files from https://huggingface.co/Comfy-Org/MiniMax-H3")
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec", nargs="?")
    ap.add_argument("--out")
    ap.add_argument("--prompt", help="prompt file (default <out>/prompt.txt, else built from the spec)")
    ap.add_argument("--first-frame", help="first-frame still (overrides the spec's first_frame; '' = none)")
    ap.add_argument("--comfy", default=os.environ.get("COMFY_URL", "http://127.0.0.1:8188"))
    for k in DEFAULTS:
        ap.add_argument("--" + k.replace("_", "-"), dest=k, help=f"default {DEFAULTS[k]}")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--lint", metavar="PROMPT_FILE")
    ap.add_argument("--duration", type=float)
    ap.add_argument("--timeout", type=float, default=1800, help="seconds to wait for one clip")
    a = ap.parse_args()
    models, comfy = models_from(a), Comfy(a.comfy)

    if a.lint:
        E, W = lint(Path(a.lint).read_text(encoding="utf-8"), a.duration)
        print("\n".join([f"ERROR {x}" for x in E] + [f"WARN  {x}" for x in W] + ["OK" if not E else f"{len(E)} error(s)"]))
        sys.exit(1 if E else 0)
    if a.check:
        sys.exit(0 if check(comfy, models) else 1)
    if not a.spec or not a.out:
        ap.error("give a spec and --out (or --check / --lint)")

    spec_path = Path(a.spec).resolve()
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    prompt_file = Path(a.prompt) if a.prompt else out / "prompt.txt"
    if prompt_file.exists():
        prompt = prompt_file.read_text(encoding="utf-8")
    else:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from ai_video import build_prompt  # same folder; the official six-section layout
        prompt = build_prompt(spec)
        prompt_file.write_text(prompt, encoding="utf-8")
    E, W = lint(prompt, float(spec["duration"]))
    for x in E + W:
        print(("ERROR " if x in E else "WARN  ") + x)
    if E:
        sys.exit("fix the prompt first (see the errors above)")

    first = a.first_frame if a.first_frame is not None else (
        str(spec_path.parent / spec["first_frame"]) if spec.get("first_frame") else "")
    last = str(spec_path.parent / spec["last_frame"]) if spec.get("last_frame") else ""
    for p in (first, last):
        if p and not Path(p).exists():
            sys.exit(f"image not found: {p}")
    tag = f"{out.name}_{int(time.time())}"

    if a.dry_run:
        g, length, steps = build_graph(spec, prompt, models, {"first": first and Path(first).name,
                                                               "last": last and Path(last).name}, tag)
        (out / "workflow_api.json").write_text(json.dumps(g, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[dry-run] {out / 'workflow_api.json'}  {length} frames, {steps} steps")
        return

    if not check(comfy, models):
        sys.exit(1)
    images = {"first": first and comfy.upload(first, f"{tag}_first{Path(first).suffix}"),
              "last": last and comfy.upload(last, f"{tag}_last{Path(last).suffix}")}
    g, length, steps = build_graph(spec, prompt, models, images, tag)
    (out / "workflow_api.json").write_text(json.dumps(g, ensure_ascii=False, indent=1), encoding="utf-8")
    t0 = time.time()
    pid = comfy.json("/prompt", {"prompt": g, "client_id": uuid.uuid4().hex})["prompt_id"]
    print(f"[queued] {tag}: {length} frames, {steps} steps, seed {spec.get('seed', 42)}", flush=True)
    while True:
        time.sleep(4)
        hist = comfy.json(f"/history/{pid}", timeout=30)
        if pid in hist:
            break
        if time.time() - t0 > a.timeout:
            sys.exit(f"timed out after {a.timeout:.0f} s (prompt {pid} may still be running in ComfyUI)")
    e = hist[pid]
    ok = e.get("status", {}).get("status_str") == "success"
    if ok:
        o = e["outputs"]["15"]
        v = (o.get("videos") or o.get("images") or o.get("gifs"))[0]
        q = urllib.parse.urlencode({"filename": v["filename"], "subfolder": v.get("subfolder", ""), "type": v.get("type", "output")})
        (out / "clip.mp4").write_bytes(comfy.get(f"/view?{q}", timeout=300))
    else:
        print(json.dumps(e.get("status", {}), ensure_ascii=False)[:3000])
    meta = {"ok": ok, "frames": length, "steps": steps, "seed": spec.get("seed", 42), "draft": bool(spec.get("draft")),
            "models": models, "wall_s": round(time.time() - t0, 1), "comfy": comfy.url}
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[{'ok' if ok else 'FAIL'}] {out / 'clip.mp4'}  {meta['wall_s']} s", flush=True)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
