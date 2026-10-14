#!/usr/bin/env bash
# 制作パイプラインの依存をそろえる (初回のみ)
set -euo pipefail
cd "$(dirname "$0")"

pip install -q matplotlib pillow numpy pyopenjtalk-plus

# Noto Sans JP (SIL Open Font License) を npm 経由で取得
if [ ! -f fonts/NotoSansJP_800ExtraBold.ttf ]; then
  tmp=$(mktemp -d)
  (cd "$tmp" && npm pack @expo-google-fonts/noto-sans-jp --silent >/dev/null && tar xzf ./*.tgz)
  mkdir -p fonts
  cp "$tmp"/package/500Medium/NotoSansJP_500Medium.ttf "$tmp"/package/800ExtraBold/NotoSansJP_800ExtraBold.ttf fonts/
  rm -rf "$tmp"
fi

command -v ffmpeg >/dev/null || { echo "ffmpeg をインストールしてください"; exit 1; }
echo "setup OK"
