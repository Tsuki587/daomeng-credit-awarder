"""任务准备：活动名称、运行目录、配置读写、adb 定位，命令行与图形界面共用。"""
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Optional

from .config import AutomationConfig
from .excel_io import read_excel


def read_activity_name(list_path: Path) -> str:
    """从录取名单里取活动名称，表格第二行第一列。"""
    frame = read_excel(list_path, usecols=["活动名称"], nrows=2, dtype=str)
    return str(frame.iloc[1, 0])


def new_output_dir(base_dir: Path, activity_name: str) -> Path:
    """用「活动名-时间戳」建本次运行的目录。"""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    name = activity_name.replace("“", "").replace("”", "").replace('"', "")
    out = base_dir / f"{name}-{stamp}"
    out.mkdir(parents=True, exist_ok=True)
    return out


def save_config(config: AutomationConfig, output_dir: Path) -> None:
    path = output_dir / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump({
            "device": config.device,
            "additional_list": str(config.additional_list) if config.additional_list else None,
            "file_dir": [(str(p), pts) for pts, p in config.file_dir.items()] if config.file_dir else None,
            "accounts": config.accounts if config.accounts else None,
            "yiban_mapping": str(config.yiban_mapping) if config.yiban_mapping else None,
            "click_other_tab": config.click_other_tab,
        }, f, ensure_ascii=False, indent=4)


def load_config(config_path: Path) -> dict:
    """读 config.json，把路径类字段还原成 Path。"""
    with config_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    data["additional_list"] = Path(data["additional_list"]) if data.get("additional_list") else None
    data["accounts"] = data.get("accounts") if data.get("accounts") else None
    data["yiban_mapping"] = Path(data["yiban_mapping"]) if data.get("yiban_mapping") else None
    data["click_other_tab"] = bool(data.get("click_other_tab", False))
    return data


def _bundled_adb() -> Optional[Path]:
    """打包后的 exe 旁边或临时解包目录里带的 adb。"""
    exe = "adb.exe" if os.name == "nt" else "adb"
    roots = [Path(sys.argv[0]).resolve().parent]
    if getattr(sys, "_MEIPASS", None):
        roots.insert(0, Path(sys._MEIPASS))
    for root in roots:
        for rel in (Path("vendor") / "platform-tools" / exe, Path("adb") / exe):
            path = root / rel
            if path.is_file():
                return path
    return None


def resolve_adb() -> str:
    """优先用随包附带的 adb，其次用环境变量和 PATH 里的。"""
    adb = _bundled_adb()
    if adb is None:
        found = os.environ.get("ADBUTILS_ADB_PATH") or shutil.which("adb")
        adb = Path(found) if found else None
    if adb is None or not adb.is_file():
        raise FileNotFoundError("找不到 adb；请安装 Android platform-tools 并确认 adb 在 PATH 中。")
    os.environ["ADBUTILS_ADB_PATH"] = str(adb)
    return str(adb)
