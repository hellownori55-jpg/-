"""
ショート動画自動生成のローカルWebサーバー。

起動すると http://127.0.0.1:5000 でフォームが開き、
1. ネズミ画像を1枚選ぶ
2. 台本を書く
3. 「動画を作成」ボタンを押す
だけで main.py の生成処理が走り、できた動画をブラウザ上でそのまま再生できる。
"""

import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_from_directory

from main import parse_script_text, render_video

BASE_DIR = Path(__file__).parent
MOUSE_DIR = BASE_DIR / "ネズミ画像"
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

app = Flask(__name__)


def list_mouse_images():
    if not MOUSE_DIR.exists():
        return []
    exts = {".jpg", ".jpeg", ".png"}
    return sorted(p.name for p in MOUSE_DIR.iterdir() if p.suffix.lower() in exts)


@app.route("/")
def index():
    return render_template("index.html", images=list_mouse_images())


@app.route("/mouse_images/<path:filename>")
def mouse_image(filename):
    return send_from_directory(MOUSE_DIR, filename)


@app.route("/output/<path:filename>")
def output_file(filename):
    return send_from_directory(OUTPUT_DIR, filename)


@app.route("/generate", methods=["POST"])
def generate():
    script_text = (request.form.get("script_text") or "").strip()
    mouse_filename = request.form.get("mouse_image") or ""

    if not script_text:
        return jsonify({"error": "台本が入力されていません。"}), 400

    mouse_path = None
    if mouse_filename:
        if mouse_filename not in list_mouse_images():
            return jsonify({"error": "選択されたネズミ画像が見つかりません。"}), 400
        mouse_path = MOUSE_DIR / mouse_filename

    try:
        segments = parse_script_text(script_text)
        if not segments:
            return jsonify({"error": "台本から文章を読み取れませんでした。"}), 400

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = OUTPUT_DIR / f"video_{timestamp}.mp4"

        render_video(segments, output_path, mouse_image_path=mouse_path)
    except Exception as e:  # noqa: BLE001 - フォームに理由を返すため広めに捕捉する
        return jsonify({"error": f"生成に失敗しました: {e}"}), 500

    return jsonify({"video_url": f"/output/{output_path.name}"})


def open_browser():
    time.sleep(1.0)
    webbrowser.open("http://127.0.0.1:5000")


if __name__ == "__main__":
    threading.Timer(0.5, open_browser).start()
    app.run(host="127.0.0.1", port=5000, debug=False)
