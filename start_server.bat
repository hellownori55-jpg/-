@echo off
cd /d %~dp0

if not exist .venv (
    echo 初回セットアップ中...仮想環境を作成します。
    python -m venv .venv
)

call .venv\Scripts\activate.bat

echo 必要なパッケージを確認・インストールしています...
pip install -r requirements.txt -q

if not exist .env (
    echo .envが見つからないため、.env.exampleからコピーします。
    copy .env.example .env
    echo .envを開いてPEXELS_API_KEYを設定してください。
    notepad .env
)

echo サーバーを起動します。ブラウザが自動で開きます。
python server.py

pause
