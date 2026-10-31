#!/usr/bin/env bash
# 在应用列表和桌面上放一个图标，点一下打开图形界面
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python="$here/.venv/bin/python"
if [ ! -x "$python" ]; then
    echo "还没装好运行环境，先执行 ./install-linux.sh"
    exit 1
fi

apps="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
desktop_dir="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
entry_name="到梦空间批量发分.desktop"
mkdir -p "$apps" "$desktop_dir"

write_entry() {
    cat > "$1" <<EOF
[Desktop Entry]
Type=Application
Name=到梦空间批量发分
Comment=按名单在手机上逐人发分
Exec="$python" "$here/DM-gui.py"
Path=$here
Icon=$here/assets/daomeng.png
Terminal=false
Categories=Utility;
StartupWMClass=daomeng
EOF
    chmod +x "$1"
}

write_entry "$apps/daomeng.desktop"
write_entry "$desktop_dir/$entry_name"

# GNOME 需要标记为可信，桌面上才肯直接双击启动
gio set "$desktop_dir/$entry_name" metadata::trusted true 2>/dev/null || true
update-desktop-database "$apps" 2>/dev/null || true

echo "图标已放好："
echo "  应用列表：搜「到梦空间批量发分」"
echo "  桌面：$desktop_dir/$entry_name"
