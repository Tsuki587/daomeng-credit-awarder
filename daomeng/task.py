"""任务准备：活动名称、运行目录、配置读写、adb 定位，命令行与图形界面共用。"""
import json
import os
import re
import shutil
import sqlite3
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

from .config import AutomationConfig
from .excel_io import clean_columns, read_excel


def read_activity_name(list_path: Path) -> str:
    """从录取名单里取活动名称，表格第二行第一列。"""
    frame = read_excel(list_path, nrows=2, dtype=str)
    clean_columns(frame)
    if "活动名称" not in frame.columns:
        raise ValueError(f"{list_path.name} 里没有「活动名称」列，没法确定活动")
    return str(frame["活动名称"].iloc[1])


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


def _read_ids(path: Path) -> Dict[str, str]:
    """读一份名单的学号与姓名。"""
    frame = read_excel(path, dtype=str)
    clean_columns(frame)
    if "学号" not in frame.columns:
        raise ValueError(f"{path.name} 里没有「学号」列")
    names = frame["姓名"].tolist() if "姓名" in frame.columns else [""] * len(frame)
    ids: Dict[str, str] = {}
    for student_id, name in zip(frame["学号"].tolist(), names):
        if not isinstance(student_id, str):
            continue
        student_id = student_id.strip().removeprefix("`")
        if student_id:
            ids[student_id] = (name or "").strip() if isinstance(name, str) else ""
    return ids


def _sample(items: List[str], limit: int = 8) -> str:
    """最多列 limit 条，其余折成「等 N 人」。"""
    shown = "、".join(items[:limit])
    return shown if len(items) <= limit else f"{shown} 等 {len(items)} 人"


def compare_resume(run_dir: Path, files: Dict[float, Path]) -> List[str]:
    """续跑前核对名单与进度，返回差异说明；空列表表示一致。"""
    problems: List[str] = []
    saved: Dict[float, Dict[str, str]] = {}
    pending: Dict[float, int] = {}
    with sqlite3.connect(run_dir / "students.db") as conn:
        query = "SELECT student_id, name, points, status FROM students"
        for student_id, name, points, status in conn.execute(query):
            key = round(float(points), 2)
            saved.setdefault(key, {})[str(student_id)] = str(name)
            if status == "未处理":
                pending[key] = pending.get(key, 0) + 1

    handled: set[float] = set()
    for points, path in sorted(files.items()):
        key = round(float(points), 2)
        if key == 0.0:  # 录取名单只用来核对姓名和活动名，不发分，库里也没有它的记录
            continue
        handled.add(key)
        sheet = _read_ids(path)
        stored = saved.pop(key, {})
        if not stored:
            problems.append(f"{key:g} 分：表里 {len(sheet)} 人，但进度库里没有这个分值")
            continue
        added = [f"{sid} {sheet[sid]}".strip() for sid in sheet if sid not in stored]
        lost = [f"{sid} {name}".strip() for sid, name in stored.items() if sid not in sheet]
        renamed = [
            f"{sid} {stored[sid]}→{sheet[sid]}"
            for sid in sheet
            if sid in stored and sheet[sid] and stored[sid] and sheet[sid] != stored[sid]
        ]
        if not (added or lost or renamed):
            continue
        lines = [f"{key:g} 分：表里 {len(sheet)} 人，进度库里 {len(stored)} 人"]
        if added:
            lines.append(f"  表里多出 {len(added)} 人：{_sample(added)}")
        if lost:
            lines.append(f"  表里少了 {len(lost)} 人：{_sample(lost)}")
        if renamed:
            lines.append(f"  姓名对不上 {len(renamed)} 人：{_sample(renamed)}")
        problems.append("\n".join(lines))

    for points, count in pending.items():
        if count and points not in handled:
            problems.append(f"{points:g} 分：进度库里还有 {count} 人没发，这次没有对应的名单，他们会被跳过")

    expected = re.sub(r"-\d{8}-\d{6}$", "", run_dir.name)
    actual = read_activity_name(files[sorted(files)[0]])
    if _plain(actual) != _plain(expected):
        problems.append(f"活动名对不上：目录是「{expected}」，录取名单里是「{actual}」")
    return problems


def _plain(name: str) -> str:
    """去掉引号，和建目录时的处理保持一致。"""
    return name.replace("“", "").replace("”", "").replace('"', "")
