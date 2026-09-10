#!/bin/bash
# Mac用の起動スクリプト。Finderでダブルクリックすると実行される。
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
    echo "初回セットアップ中...仮想環境を作成します。"
    python3 -m venv .venv
fi

source .venv/bin/activate

echo "必要なパッケージを確認・インストールしています..."
pip install -r requirements.txt -q

if [ ! -f ".env" ]; then
    echo ".envが見つからないため、.env.exampleからコピーします。"
    cp .env.example .env
    echo ".envを開いてPEXELS_API_KEYを設定してください。"
    open -e .env
fi

echo "サーバーを起動します。ブラウザが自動で開きます。"
python3 server.py
