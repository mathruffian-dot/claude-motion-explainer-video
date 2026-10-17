# AI 影片層：什麼時候用、怎麼生成、怎麼放

**影片素材以 AI 生成為主。** 新聞畫面、廠商宣傳片、YouTube 片段、圖庫影片幾乎都有版權，教學片不能隨便剪進來。只有確定可以自由使用的影片才考慮放：公有領域，例如 NASA 的部分素材，或明確採 CC 授權的影片。其他一律用 AI 生成，並在畫面上標「AI 生成影片」。

## 什麼場景值得放 AI 影片

動畫的線稿負責講原理，AI 影片負責「讓人相信、讓人想看」。每支片 **2–4 段**就夠了：

| 適合 | 例子 | 擺法 |
|---|---|---|
| 開場的鉤子 | 跑車倒掛在環形軌道上疾駛 | `background`，透明度 0.5–0.55 |
| 一個「拍不到」的動作，正好對上旁白 | 噴氣停掉、車子落回地面（對上「只能跳一下」） | `card`，放在該格空著的地方 |
| 收尾的情緒 | 跑車在霧氣中懸浮，鏡頭慢慢推近 | `background`，透明度 0.45，同時藏起原本的線稿 |

不適合：需要精確數字或受力方向的畫面（交給線稿）、真實人物、真實品牌的產品外型。

## 生成：MiniMax H3

- 官方：[MiniMax-AI/MiniMax-H3](https://github.com/MiniMax-AI/MiniMax-H3)（MiniMax H3 Community License，使用前請讀授權條款）。可以用 ComfyUI 的官方模板跑（R2V／T2V）。
- 規格：每段 **4–15 秒**、24 fps、短邊預設 768（例如 1344×768）。會一起生成原生聲音，但放進片子時一律靜音，聲音只用旁白。
- **用一張圖當第一格**（`first_frame`）：先用 Codex 生成符合主題配色的靜態圖，再交給 H3 讓它動起來。這樣影片的風格、配色和片子一致，而且同一張圖可以生成好幾段不同的動作。
- prompt 用官方的六段格式。`ai_video.py prompt` 會自動組好；有官方 linter 的話可以拿來檢查。
- 生成器不寫死在技能裡：每台電腦在 `video_config.json` 設定自己的 `runner`（本機腳本、ComfyUI API 都可以），技能只負責給它 spec 和輸出資料夾。

**本機實測（RTX 5090 32 GB，DMAD 4 步快速模式，只給第一格）**：8.5 秒的片段約 91 秒、5 秒約 58 秒、6 秒約 75 秒；生成時顯示記憶體用了約 26 GB。

## 檢查（一定要親眼看）

`ai_video.py check` 會在每段影片平均抽 8 格，拼成 contact sheet。逐張看：

- 物體有沒有變形或改變形狀（車身在轉彎時會微微變形，當半透明背景通常可以接受）
- 有沒有多出輪子、手腳，或零件憑空出現。實例：車子懸浮時，輪子被噴氣擋住；落地後輪子才「長」出來。放在小卡片裡不明顯，但當主畫面就不行。
- 有沒有冒出文字、logo、浮水印（H3 偶爾會在角落留下很淡的類似浮水印的痕跡）
- 動作的時間點能不能對上旁白，例如落地的那一刻是不是剛好在「跳一下」

不合格就刪掉 `clip.mp4`，換一個 seed 重跑。

## 擺放（`media.json` 的 `placements`）

```json
{ "frame": "06-limits", "video": "assets/videos/gen/v-landing/clip.mp4", "mode": "card",
  "label_side": "right", "box": [90, 90, 560, 315], "at": 1.7, "duration": 5.0, "out": 6.5,
  "label": "氣瓶一空，推力就沒了：只能「跳一下」", "credit": "AI 生成影片（H3）· 示意" }
```

HyperFrames 對影片的硬規則（`place_media.py` 都處理好了，手寫時要注意）：

1. `<video>` **一定要有 `id`**，否則 renderer 找不到它，輸出時會**凍結成一張圖**。
2. `<video>` 用 `class="clip"`、`muted`，加上自己的 `data-start`／`data-duration`（以該格為準的秒數）。**不能放在另一個有計時的元素裡面**，否則播放的畫面和時間會對不上。背景影片要放在背景圖層的**後面（同層）**，不是裡面。
3. 播放由 HyperFrames 負責，script 不能 play、pause、seek。淡入淡出、移動都只動外層沒有計時的 wrapper。
4. 影片比那一格短的話，播完會被隱藏，留下空框。用 `out` 在影片結束前把整張卡淡出。
5. 影片放進去以後，跑 `hyperframes lint`（`media_missing_id`、`video_nested_in_timed_element` 都是 error）和 `hyperframes check`（疊在影片上的字，對比度要過）。

## 執行順序

```bash
# 1. 第一格用的靜態圖（Codex）：見 images.md
python scripts/codex_images.py --project .
# 2. 寫 assets/videos/gen/specs/<name>.json（見 templates/video-specs/）
python scripts/ai_video.py prompt --project .
python scripts/ai_video.py run --project .        # 需要 video_config.json 的 runner
python scripts/ai_video.py check --project .      # 看每一張 check-1.png
# 3. 在 media.json 加 placements，然後：
python scripts/theme.py --project .
python scripts/place_media.py --project .
hyperframes lint && hyperframes check
```
