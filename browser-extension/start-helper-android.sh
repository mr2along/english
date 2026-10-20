#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

helper_dir="$(cd "$(dirname "$0")" && pwd)"
repo_dir="$(cd "$helper_dir/.." && pwd)"
environment_dir="$helper_dir/.venv-android"

if ! command -v pkg >/dev/null 2>&1; then
  echo "Hãy chạy script này trong Termux trên Android."
  exit 1
fi

pkg install -y python ffmpeg

if [ ! -d "$HOME/storage/downloads" ]; then
  termux-setup-storage
  echo "Nếu Android hiện yêu cầu quyền lưu trữ, hãy chấp nhận rồi chạy lại lệnh này."
  exit 1
fi

mkdir -p "$HOME/storage/downloads/English Lab Videos"

if [ ! -x "$environment_dir/bin/python" ]; then
  python -m venv "$environment_dir"
  "$environment_dir/bin/python" -m pip install --upgrade pip
  "$environment_dir/bin/python" -m pip install -r "$helper_dir/requirements.txt"
fi

export ENGLISH_LAB_DOWNLOAD_DIR="$HOME/storage/downloads/English Lab Videos"
export PATH="$PREFIX/bin:$PATH"
cd "$repo_dir"
echo "Mở Chrome trên điện thoại tại http://127.0.0.1:8765"
echo "Giữ Termux đang chạy trong lúc tải. Nhấn Ctrl+C để dừng bộ trợ giúp."
exec "$environment_dir/bin/python" "$helper_dir/local_video_helper.py"
