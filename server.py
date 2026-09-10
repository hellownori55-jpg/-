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
import uuid
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

# 動画生成は数十秒〜数分かかる。1本のHTTPリクエストで待たせ続けると、
# 大学のネットワークやセキュリティソフトなどが「応答のない通信」とみなして
# 途中で切断し、ブラウザ側で「Failed to fetch」になることがある。
# そのため生成は裏スレッドで実行し、フロント側は/status/<job_id>を
# 数秒おきに確認するポーリング方式にする。
JOBS = {}
JOBS_LOCK = threading.Lock()


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
    # .mp4の判定をOSのレジストリ任せにすると、環境によっては
    # video/mp4と認識されずブラウザのプレビューが再生を拒否することがあるため、
    # 明示的に指定する。
    return send_from_directory(OUTPUT_DIR, filename, mimetype="video/mp4")


def run_generation(job_id, segments, mouse_path):
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = OUTPUT_DIR / f"video_{timestamp}.mp4"
        render_video(segments, output_path, mouse_image_path=mouse_path)
        with JOBS_LOCK:
            JOBS[job_id] = {"status": "done", "video_url": f"/output/{output_path.name}"}
    except Exception as e:  # noqa: BLE001 - フォームに理由を返すため広めに捕捉する
        with JOBS_LOCK:
            JOBS[job_id] = {"status": "error", "error": f"生成に失敗しました: {e}"}


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
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": f"台本の解析に失敗しました: {e}"}), 400
    if not segments:
        return jsonify({"error": "台本から文章を読み取れませんでした。"}), 400

    # 生成は裏スレッドで開始し、このリクエスト自体はすぐ返す
    # (長時間の通信を張ったままにしないため)。
    job_id = uuid.uuid4().hex
    with JOBS_LOCK:
        JOBS[job_id] = {"status": "running"}
    threading.Thread(
        target=run_generation, args=(job_id, segments, mouse_path), daemon=True
    ).start()

    return jsonify({"job_id": job_id})


@app.route("/status/<job_id>")
def job_status(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if job is None:
        return jsonify({"error": "不明なジョブIDです。"}), 404
    return jsonify(job)


def open_browser():
    time.sleep(1.0)
    webbrowser.open("http://127.0.0.1:5000")


if __name__ == "__main__":
    threading.Timer(0.5, open_browser).start()
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
