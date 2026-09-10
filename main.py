import argparse
import itertools
import os
import platform
import random
import re
from pathlib import Path

import numpy as np
import requests
from dotenv import load_dotenv
from PIL import Image
from moviepy import (
    CompositeVideoClip,
    ImageClip,
    TextClip,
    VideoFileClip,
    concatenate_videoclips,
)
from moviepy.video.fx import Crop, Loop

load_dotenv()


def default_font_path() -> str:
    # OSごとに標準で入っている日本語フォントを探す。
    # (.envのFONT_PATHが他OS向けのパスで無効な場合のフォールバックにも使う)
    system = platform.system()
    if system == "Windows":
        candidates = ["C:/Windows/Fonts/meiryo.ttc", "C:/Windows/Fonts/YuGothM.ttc"]
    elif system == "Darwin":
        candidates = [
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
            "/System/Library/Fonts/ヒラギノ角ゴシック W4.ttc",
            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        ]
    else:
        candidates = [
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJKjp-Regular.otf",
        ]
    for c in candidates:
        if Path(c).exists():
            return c
    return candidates[0]


def resolve_font_path() -> str:
    env_path = os.getenv("FONT_PATH", "").strip()
    if env_path and Path(env_path).exists():
        return env_path
    return default_font_path()


PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")
FONT_PATH = resolve_font_path()
OUTPUT_WIDTH = int(os.getenv("OUTPUT_WIDTH", "1080"))
OUTPUT_HEIGHT = int(os.getenv("OUTPUT_HEIGHT", "1920"))
FPS = int(os.getenv("FPS", "30"))
CHARS_PER_SECOND = float(os.getenv("CHARS_PER_SECOND", "6"))
MIN_SEGMENT_DURATION = float(os.getenv("MIN_SEGMENT_DURATION", "1.5"))

FALLBACK_KEYWORDS = itertools.cycle(
    ["calm nature landscape", "abstract geometric pattern", "quiet sky clouds",
     "slow motion water", "soft light bokeh abstract"]
)

# 台本の単語から背景映像の検索語を自動推定するためのマッピング。
# [keyword: ...]タグが無い段落はここでヒットした語(複数可)をPexelsのクエリにする。
# 人物や顔が映り込みやすい語は避け、風景・自然・抽象/幾何学模様のみになるようにする。
JP_KEYWORD_MAP = {
    "幸せ": "golden sunlight nature",
    "家族": "warm cozy light home",
    "自由": "open sky flying birds",
    "好意": "soft warm light bokeh",
    "お金": "gold coins texture macro",
    "安心": "calm water nature",
    "不安": "dark storm clouds",
    "怖": "dark fog forest",
    "嫌": "rain window abstract",
    "イライラ": "storm lightning clouds",
    "ワクワク": "colorful lights bokeh abstract",
    "ドキドキ": "colorful abstract motion",
    "きゅん": "soft pink light bokeh",
    "ほっと": "calm sunrise nature",
    "言葉": "paper texture writing abstract",
    "解釈": "maze abstract pattern",
    "フィルター": "light through glass prism",
    "世界": "earth landscape aerial",
    "反応": "ripple water abstract",
    "感じ": "soft light abstract texture",
    "現実": "glass reflection abstract",
    "過去": "vintage film grain texture",
    "思い込み": "maze pattern abstract",
}


def infer_keyword(text: str):
    matched = []
    for jp, en in JP_KEYWORD_MAP.items():
        if jp in text and en not in matched:
            matched.append(en)
    return " ".join(matched) if matched else None

WORK_DIR = Path(__file__).parent / "work"

TAG_RE = re.compile(r"^\[(keyword|duration):\s*(.*?)\s*\]$")


def parse_script(path: Path):
    return parse_script_text(path.read_text(encoding="utf-8"))


def parse_script_text(text: str):
    blocks = re.split(r"\n\s*\n", text.strip())
    segments = []
    for block in blocks:
        lines = block.strip().splitlines()
        keyword = None
        duration = None
        while lines:
            m = TAG_RE.match(lines[0].strip())
            if not m:
                break
            if m.group(1) == "keyword":
                keyword = m.group(2)
            else:
                duration = float(m.group(2))
            lines = lines[1:]
        body = "\n".join(l for l in lines if l.strip())
        if body.strip():
            segments.append({"text": body.strip(), "keyword": keyword, "duration": duration})
    return segments


def estimate_duration(text: str) -> float:
    char_count = len(re.sub(r"\s", "", text))
    return max(MIN_SEGMENT_DURATION, char_count / CHARS_PER_SECOND)


def search_pexels_video(query: str):
    if not PEXELS_API_KEY:
        raise RuntimeError("PEXELS_API_KEYが設定されていません(.envを確認してください)。")
    headers = {"Authorization": PEXELS_API_KEY}
    params = {"query": query, "orientation": "portrait", "per_page": 15}
    r = requests.get(
        "https://api.pexels.com/videos/search", headers=headers, params=params, timeout=20
    )
    r.raise_for_status()
    videos = r.json().get("videos", [])
    if not videos:
        return None
    video = random.choice(videos[: min(5, len(videos))])
    files = sorted(video["video_files"], key=lambda f: f.get("height") or 0)
    for f in files:
        if f.get("height") and f["height"] >= OUTPUT_HEIGHT:
            return f["link"]
    return files[-1]["link"] if files else None


def download_file(url: str, path: Path):
    r = requests.get(url, stream=True, timeout=60)
    r.raise_for_status()
    with open(path, "wb") as f:
        for chunk in r.iter_content(8192):
            f.write(chunk)


def cover_resize_crop(clip, w, h):
    src_ratio = clip.w / clip.h
    target_ratio = w / h
    if src_ratio > target_ratio:
        resized = clip.resized(height=h)
    else:
        resized = clip.resized(width=w)
    return resized.with_effects(
        [Crop(width=w, height=h, x_center=resized.w / 2, y_center=resized.h / 2)]
    )


def fit_duration(clip, duration):
    if clip.duration < duration:
        clip = clip.with_effects([Loop(duration=duration)])
    else:
        clip = clip.subclipped(0, duration)
    return clip.with_duration(duration)


def build_background_clip(video_path: Path, duration: float):
    video = VideoFileClip(str(video_path), audio=False)
    video = cover_resize_crop(video, OUTPUT_WIDTH, OUTPUT_HEIGHT)
    return fit_duration(video, duration)


def build_caption_clip(text: str, start: float, duration: float):
    caption_width = int(OUTPUT_WIDTH * 0.85)
    caption_kwargs = dict(
        font=FONT_PATH,
        text=text,
        font_size=64,
        color="white",
        stroke_color="black",
        stroke_width=2,
        method="caption",
        text_align="center",
    )
    # moviepyのcaption自動高さ計算は複数行テキストで実際より低く見積もり、
    # 最下行が描画時に欠けることがあるため、余裕を持たせた高さで再生成する。
    probe = TextClip(size=(caption_width, None), **caption_kwargs)
    safe_height = int(probe.h * 1.6) + 20
    probe.close()
    caption = TextClip(size=(caption_width, safe_height), **caption_kwargs)

    center_y = OUTPUT_HEIGHT * 0.22
    y = center_y - caption.h / 2
    y = max(OUTPUT_HEIGHT * 0.08, min(y, OUTPUT_HEIGHT - caption.h - 80))
    return caption.with_start(start).with_duration(duration).with_position(("center", y))


def remove_white_background(image_path: Path, white_threshold: int = 248) -> np.ndarray:
    """白背景のネズミ画像を読み込み、白背景を透過させたRGBA配列を返す。

    ピクセルのR/G/Bの最小値が white_threshold 以下なら不透明、
    255(純白)なら完全透明、その間は線形補間でなめらかに透過させる
    (輪郭のギザギザやハロを防ぐため)。
    """
    rgb = np.array(Image.open(image_path).convert("RGB")).astype(np.float32)
    min_channel = rgb.min(axis=2)
    alpha = np.clip((255.0 - min_channel) / (255.0 - white_threshold), 0.0, 1.0) * 255.0
    return np.dstack([rgb, alpha]).astype(np.uint8)


def build_mouse_overlay_clip(image_path: Path, total_duration: float):
    # 動画の下部中央に、選択したネズミ画像(白背景を透過)を最初から最後まで常時表示する。
    rgba = remove_white_background(image_path)
    img = ImageClip(rgba)
    target_width = int(OUTPUT_WIDTH * 0.35)
    img = img.resized(width=target_width)
    margin_bottom = 40
    y = OUTPUT_HEIGHT - img.h - margin_bottom
    return img.with_duration(total_duration).with_position(("center", y))


def format_timestamp(seconds: float) -> str:
    m, s = divmod(seconds, 60)
    return f"{int(m):02d}:{s:05.2f}"


def write_timeline(path: Path, segments, starts):
    lines = []
    for i, (seg, start) in enumerate(zip(segments, starts)):
        end = start + seg["duration"]
        lines.append(f"[{format_timestamp(start)} - {format_timestamp(end)}] {seg['text']}")
    path.write_text("\n".join(lines), encoding="utf-8")


def render_video(segments, output_path: Path, mouse_image_path: Path = None, progress_cb=None):
    """台本セグメントから動画を生成し、output_pathに書き出す。

    progress_cb(現在のセグメント番号(1始まり), 総数, 検索クエリ)が渡されていれば、
    各セグメントの処理開始時に呼び出す(サーバー側での進捗表示用)。
    """
    if not segments:
        raise ValueError("台本が空です。")

    WORK_DIR.mkdir(exist_ok=True)

    for seg in segments:
        if seg["duration"] is None:
            seg["duration"] = estimate_duration(seg["text"])

    background_clips = []
    caption_clips = []
    starts = []
    timeline = 0.0

    for i, seg in enumerate(segments):
        duration = seg["duration"]
        starts.append(timeline)

        query = seg["keyword"] or infer_keyword(seg["text"]) or next(FALLBACK_KEYWORDS)
        if progress_cb:
            progress_cb(i + 1, len(segments), query)
        print(f"[{i + 1}/{len(segments)}] 背景映像検索中 (query={query!r}, {duration:.1f}秒)...")
        video_url = search_pexels_video(query) or search_pexels_video(next(FALLBACK_KEYWORDS))
        if not video_url:
            raise RuntimeError(f"背景映像が見つかりませんでした: {query}")
        video_path = WORK_DIR / f"video_{i}.mp4"
        download_file(video_url, video_path)

        background_clips.append(build_background_clip(video_path, duration))
        caption_clips.append(build_caption_clip(seg["text"], timeline, duration))
        timeline += duration

    print("最終合成・書き出し中...")
    video_track = concatenate_videoclips(background_clips, method="compose")
    layers = [video_track, *caption_clips]
    if mouse_image_path:
        layers.append(build_mouse_overlay_clip(mouse_image_path, timeline))
    # bg_colorを指定しないとCompositeVideoClipが透明合成扱いになり、
    # 書き出し時にlibx264が扱えない(環境によっては再生できない)yuva420pに
    # なってしまうため、不透明な黒背景を明示して通常のyuv420pで書き出す。
    final = CompositeVideoClip(layers, size=(OUTPUT_WIDTH, OUTPUT_HEIGHT), bg_color=(0, 0, 0))

    final.write_videofile(str(output_path), fps=FPS, codec="libx264")

    timeline_path = output_path.with_suffix(".timeline.txt")
    write_timeline(timeline_path, segments, starts)

    print(f"完了: {output_path}")
    print(f"ナレーション録音用タイムライン: {timeline_path}")
    return output_path, timeline_path


def main():
    parser = argparse.ArgumentParser(
        description="台本から(ナレーションなしの)背景+字幕動画を自動生成する"
    )
    parser.add_argument("script", type=Path, help="台本テキストファイル(.txt)")
    parser.add_argument("output", type=Path, help="出力動画ファイル(.mp4)")
    parser.add_argument(
        "--mouse-image", type=Path, default=None,
        help="動画の下部中央に常時表示するネズミ画像ファイル(任意)",
    )
    args = parser.parse_args()

    segments = parse_script(args.script)
    render_video(segments, args.output, mouse_image_path=args.mouse_image)


if __name__ == "__main__":
    main()
