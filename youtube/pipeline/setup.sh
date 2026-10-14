#!/usr/bin/env bash
# 制作パイプラインの依存をそろえる (初回のみ)
set -euo pipefail
cd "$(dirname "$0")"

pip install -q matplotlib pillow numpy pyopenjtalk-plus skia-python
# skia-python が libEGL を要求する環境向け (Debian/Ubuntu)
python3 -c "import skia" 2>/dev/null || { apt-get install -y -q libegl1 >/dev/null || sudo apt-get install -y -q libegl1; }

fetch_npm() {  # $1 = パッケージ名, $2 = 展開先
  local tmp
  tmp=$(mktemp -d)
  (cd "$tmp" && npm pack "$1" --silent >/dev/null && tar xzf ./*.tgz)
  mkdir -p "$2"
  cp -r "$tmp"/package/. "$2"/
  rm -rf "$tmp"
}

# Noto Sans JP (SIL Open Font License)
if [ ! -f fonts/NotoSansJP_800ExtraBold.ttf ]; then
  fetch_npm @expo-google-fonts/noto-sans-jp vendor/noto
  mkdir -p fonts
  cp vendor/noto/500Medium/NotoSansJP_500Medium.ttf vendor/noto/800ExtraBold/NotoSansJP_800ExtraBold.ttf fonts/
  rm -rf vendor/noto
fi
# Material Design Icons (Apache License 2.0)
[ -d vendor/icons ] || fetch_npm @material-design-icons/svg vendor/icons
# 世界地図 world-atlas (Natural Earth, パブリックドメイン)
[ -d vendor/world-atlas ] || fetch_npm world-atlas vendor/world-atlas

command -v ffmpeg >/dev/null || { echo "ffmpeg をインストールしてください"; exit 1; }
echo "setup OK"
