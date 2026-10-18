# claude-motion-explainer-video

**用一句話，讓 coding agent 做出一支「動畫講原理、照片當證據、AI 影片帶情緒」的解說影片。** 這是 [claude-motion-explainer](https://github.com/mathruffian-dot/claude-motion-explainer) 系列的影片加強版：

| 版本 | 內容 |
|---|---|
| [基本版](https://github.com/mathruffian-dot/claude-motion-explainer) | 動畫 + 中文旁白 + 字幕 + 三色主題 |
| [圖片加強版](https://github.com/mathruffian-dot/claude-motion-explainer-images) | ＋ 網路授權照片、Codex 生成示意圖 |
| **影片加強版（本 repo）** | ＋ **MiniMax H3 AI 生成影片**、修正唸錯的字 |

**影片素材以 AI 生成為主。** 新聞畫面、廠商宣傳片、圖庫影片幾乎都有版權，教學片不能隨便剪進來；拍不到、找不到的畫面，就用 [MiniMax H3](https://github.com/MiniMax-AI/MiniMax-H3) 生成。每段影片都從一張 Codex 生成、符合主題配色的圖開始動，所以和動畫的風格一致。畫面上一律標「AI 生成影片」。

> 與 Anthropic 官方的 Claude Motion 無關。這是社群做的開源工作流。

## 範例

〈Tesla Roadster 的三個神奇配備〉，105 秒，用了 3 段 H3 影片：

- **開場背景**：跑車倒掛在環形軌道上疾駛，鏡頭跟著衝下來。
- **第 6 格影片卡**：噴氣停掉，車子落回地面。落地的那一刻剛好對上旁白「只能**跳一下**」。
- **收尾背景**：跑車在霧氣中懸浮，鏡頭慢慢推近。

本機 RTX 5090 用快速模式生成，三段共約 3.7 分鐘。

## 包含的 skills

| Skill | 做什麼 |
|---|---|
| [`motion-explainer-video`](skills/motion-explainer-video/SKILL.md) | 主流程：研究 → 需求訪談（三色＋字型）→ 分鏡與子句化旁白 → TTS → 每格平行製作 → 字幕 → 套色 → 圖片層 → **AI 影片層** → 審查 → 輸出 |
| [`motion-design`](skills/motion-design/SKILL.md) | 品味規則：緩動、節奏、閱讀停留、繁體中文排版、三色配色 |
| [`review-loop`](skills/review-loop/SKILL.md) | 自我審查：在每個旁白子句截一格拼成 contact sheet，逐張檢查 |

- AI 影片的完整規則：什麼場景該用、怎麼生成、怎麼檢查、HyperFrames 的影片硬規則，見 [`ai-video.md`](skills/motion-explainer-video/references/ai-video.md)。
- 圖片規則見 [`images.md`](skills/motion-explainer-video/references/images.md)，動畫踩過的坑見 [`lessons.md`](skills/motion-explainer-video/references/lessons.md)。

## 新增的工具

- `ai_video.py prompt / run / check`：
  - `prompt`：把 shot spec 組成 H3 官方六段格式的 prompt。
  - `run`：呼叫你這台電腦設定的生成器，寫在 `video_config.json` 的 `runner`，本機腳本或 ComfyUI 都可以。
- `h3_runner.py`：**參考 runner**，直接可用。透過 ComfyUI 的 HTTP API 生成一段 H3 影片：用官方「MiniMax H3 Reference to Video」模板的設定，第一格固定成你給的那張圖；`"draft": true` 改用官方 4 步 Lightning LoRA，快約 4 倍（RTX 5090 實測，5 秒片段：76 秒對 297 秒），適合先看動作對不對。ComfyUI 可以在本機，也可以在別台電腦（例如雲端 GPU）。先跑 `python h3_runner.py --check` 確認伺服器、節點和模型檔都在。
  - `check`：每段平均抽 8 格，拼成 contact sheet 給你檢查。
- `place_media.py`：把圖片或影片放進每一格。它會自動遵守 HyperFrames 的影片規則：video 一定要有 id、不能放在有計時的元素裡、播放由框架控制、影片播完前把卡片淡出。
- `fix_voice.py audition / apply`：整支片做完才發現某個字唸錯（例如「Roadster」「倒掛」「輪胎」）時使用。
  - `audition`：把多個候選的關鍵片段串成一個試聽檔，讓你用耳朵選。
  - `apply`：把選中的那一句**整句等比伸縮回原本的長度**（通常只差 ±5%），音量對齊原本那一句，再重算那一句的字幕時間。每一格的長度都不變，動畫不用重做。

## 需要的環境

- Node.js 22+、ffmpeg、Python 3 + Pillow + fonttools；HyperFrames（`npm install -g hyperframes`）。
- **AI 影片（選配）**：MiniMax H3，在本機用 ComfyUI 跑（見[官方說明](https://github.com/MiniMax-AI/MiniMax-H3)，授權為 MiniMax H3 Community License）。需要大顯示記憶體的 NVIDIA GPU：本機實測生成時用了約 26 GB。設定方式：裝好 ComfyUI（0.36 以上，內建 H3 節點），把官方模型檔（[Comfy-Org/MiniMax-H3](https://huggingface.co/Comfy-Org/MiniMax-H3)：`minimax_h3_ref2va_pruned_int8_convrot`、`qwen3vl_32b_minimax_h3_nvfp4_awq`、兩個 VAE，選配 Lightning LoRA）放進它的 `models/`，再把 `templates/video_config.example.json` 複製成專案的 `video_config.json`，它預設就是呼叫 `h3_runner.py`。想用自己的生成方式，runner 規格見 [`ai-video.md`](skills/motion-explainer-video/references/ai-video.md)。沒有 H3 也能用這個技能：AI 影片改成只給 prompt、用靜態圖代替，或不放。
  - 沒有這種硬體的話，可以用 `ai_video.py prompt` 產生 prompt，再拿到別的地方生成，把 `clip.mp4` 放回專案。
- 生成圖（選用）：Codex CLI（測試版本 0.162.1），先用 `codex login` 登入，使用它內建的 image_gen，不需要另外的 API key。如果你用的 agent 本身就是 Codex，可以直接在對話裡用 image_gen 產圖，存進 `assets/images/gen/`，不必透過 `codex_images.py`。
- 旁白：edge-tts（預設，不需要 GPU）或 Breeze TTS 2（本機 GPU，僅限非商業用途）。
- 先跑 `python skills/motion-explainer-video/scripts/hw_check.py`，它會依你的硬體給建議。

## 安裝

```bash
git clone https://github.com/mathruffian-dot/claude-motion-explainer-video.git
cp -r claude-motion-explainer-video/skills/* ~/.claude/skills/        # Claude Code
# Codex / 其他 agent：複製到 ~/.agents/skills/
```

**給其他 agent（Codex、Gemini CLI 等）**：這些 skill 只用到終端機指令和一般的讀寫檔案，沒有 Claude 專屬的工具。兩個要注意的地方，`SKILL.md` 開頭都有寫：
- 工具和 HyperFrames 官方 skill 的位置用代號 `<me>`、`<fe>` 表示，開工前先用一行指令找出實際路徑。
- 「每格派一個 sub-agent 平行做」在沒有 sub-agent 的 agent 上改成一格一格依序做，結果一樣，只是比較慢。

可以和基本版、圖片加強版一起安裝。三個 repo 共用的 `motion-design`、`review-loop` 內容完全一樣。

## 怎麼用

```text
上網查資料，做一支 90 秒、解說「為什麼飛機飛得起來」的動畫，給國中生上課用。
開場和結尾用 H3 生成影片，中間找一張真實照片當佐證。
```

## English

The video edition of the claude-motion-explainer skills: narrated, captioned HyperFrames explainer animations with a licensed-photo layer and an **AI video layer** — MiniMax H3 clips generated from on-theme Codex stills (so footage matches the film's look), placed as muted backgrounds or cards under HyperFrames' media rules. AI footage is preferred over stock/news footage to avoid copyright problems. Also includes a pronunciation-fix tool that swaps one narration line for a re-take, time-stretched as a whole onto the original line length so no frame timing changes. See `skills/motion-explainer-video/SKILL.md`.

## 授權

程式碼與文件採 [MIT](LICENSE)。`motion-design` 和 `review-loop` 改編自 [whaleyxbt/claude-motion](https://github.com/whaleyxbt/claude-motion)（MIT），其他第三方元件與模型見 [NOTICE.md](NOTICE.md)。用本工具生成的影片、下載的照片，各自遵守其模型或原作者的授權。
