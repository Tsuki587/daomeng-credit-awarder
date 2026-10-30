import argparse
import time
import json
import os
import shutil
import sys
from pandas import notna
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from rich import print

from .automation_app import AutomationApp
from .config import AutomationConfig
from .excel_io import read_excel
from .logging_utils import get_logger


@dataclass
class CLIOptions:
    """命令行解析结果。"""

    device: Optional[str]
    pair: Optional[list[str]]
    additional_list: Optional[Path]
    console_log_level: str
    file_log_level: str
    file_dir: dict[float, Path]
    init_device: bool
    recovered: Optional[Path]
    accounts: Optional[dict[str, str]]
    yiban_mapping: Optional[Path]
    click_other_tab: bool
    

def _save_to_json(config: AutomationConfig, config_path: Path) -> None:
    path = config_path / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump({
            "device": config.device,
            "additional_list": str(config.additional_list) if config.additional_list else None,
            "file_dir": [(str(path), pts) for pts, path in config.file_dir.items()] if config.file_dir else None,
            "accounts": config.accounts if config.accounts else None,
            "yiban_mapping": str(config.yiban_mapping) if config.yiban_mapping else None,
            "click_other_tab": config.click_other_tab,
        }, f, ensure_ascii=False, indent=4)
        
        
def _load_from_json(config_path: Path) -> dict:
    path = config_path
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    data["additional_list"] = Path(data["additional_list"]) if data.get("additional_list") else None
    data["accounts"] = data.get("accounts") if data.get("accounts") else None
    data["yiban_mapping"] = Path(data["yiban_mapping"]) if data.get("yiban_mapping") else None
    data["click_other_tab"] = bool(data.get("click_other_tab", False))
    return data


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="daomeng-automation",
        description="到梦空间自动化脚本",
    )
    parser.add_argument("-d", help="无线调试 IP:端口，不传入则尝试有线连接。", metavar='IP:PORT')
    parser.add_argument("-p", help="无线调试配对 IP:端口 配对码。", metavar=("IP:PORT", "CODE"), nargs=2)
    parser.add_argument("-a", help="额外添加名单。", type=Path, metavar='PATH')
    parser.add_argument(
        "-cl",
        default="WARNING",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        type=str.upper,
        help="控制台日志级别，默认 WARNING。"
    )
    parser.add_argument(
        "-fl",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        type=str.upper,
        help="文件日志级别，默认 INFO。",
    )
    parser.add_argument(
        "-f",
        nargs=2,
        action="append",
        metavar=("PATH", "POINTS"),
        help="传入 文件绝对路径 和 分值，可重复。录取名单分值设置为 0。",
    )
    parser.add_argument(
        "-i",
        action="store_true",
        help="初始化设备，第一次连接或链接异常时使用。",
    )
    parser.add_argument(
        "-r",
        type=Path,
        help="恢复上次未完成任务，传入上次任务结果文件夹绝对路径。注意：恢复模式下不允许修改 -f、-a、-yb 参数，但可以修改 -d 和 -u 参数。",
        metavar='PATH'
    )
    parser.add_argument(
        "-u",
        type=Path,
        help="传入 账号信息 文件绝对路径。",
        metavar='PATH'
    )
    parser.add_argument(
        "-yb",
        type=Path,
        help="传入 易班导出学生信息 CSV文件绝对路径，包含姓名、学号、易班ID三列。",
        metavar='PATH'
    )
    parser.add_argument(
        "--click-other-tab",
        action="store_true",
        help="在发分搜索前，先点击“已获得其他学分”tab再进行搜索。"
    )
    return parser


def _parse_args(argv: Optional[list[str]] = None) -> CLIOptions:
    parser = _build_parser()
    args = parser.parse_args(argv)
    file_dir: list[list[str]] = []
    file_dir_c: dict[float, Path] = {}
    device: Optional[str] = args.d
    additional_list: Optional[Path] = args.a
    accounts: Optional[dict[str, str]] = None
    yiban_mapping: Optional[Path] = None
    click_other_tab: bool = args.click_other_tab
    
    if args.f is None and args.r is None:
        raise ValueError("必须指定 -r 或 -f 参数。")
    
    if args.f and args.r:
        raise ValueError("参数 -r 与 -f 不能同时使用。恢复模式下会自动使用原任务的配置。")
    
    if args.a and args.r:
        raise ValueError("参数 -a 与 -r 不能同时使用。恢复模式下会自动使用原任务的配置。")
    
    if args.yb and args.r:
        raise ValueError("参数 -yb 与 -r 不能同时使用。恢复模式下会自动使用原任务的配置。")

    if args.r:
        config_path = args.r / "config.json"
        if not config_path.exists():
            raise FileNotFoundError(f"指定的恢复路径无效，未找到配置文件: {config_path}")
        recovered_config = _load_from_json(config_path)
        
        # 恢复模式下只允许修改设备连接参数和账号信息
        device = args.d if args.d else recovered_config.get("device", "")
        additional_list = recovered_config.get("additional_list")
        file_dir = recovered_config.get("file_dir", [])
        click_other_tab = recovered_config.get("click_other_tab", False)
        
        # 账号信息：允许传入新的账号信息覆盖
        if args.u:
            # 将在后续处理
            pass
        else:
            accounts = recovered_config.get("accounts")
        
        # 易班映射：使用恢复的配置
        yiban_mapping_str = recovered_config.get("yiban_mapping")
        yiban_mapping = Path(yiban_mapping_str) if yiban_mapping_str else None
    
    file_dir = args.f if args.f else file_dir
    if file_dir:
        if len(file_dir) == 0:
            raise ValueError("文件路径列表不能为空。")

    for path_str, pts_str in file_dir:
        p = Path(path_str)
        pts = float(pts_str)
        if not p.exists():
            raise FileNotFoundError(f"指定的文件路径不存在: {p}")
        if p in file_dir_c.values():
            raise ValueError(f"检测到重复的文件路径: {p}")
        if pts in file_dir_c.keys():
            raise ValueError(f"检测到重复的分值: {pts}")
        file_dir_c[pts] = p
        
    if file_dir_c.get(0) is None:
        raise ValueError("必须指定分值为 0 的录取名单文件。")
    
    # 处理账号信息：新传入的覆盖恢复的（恢复模式和新任务模式都支持）
    if args.u:
        accounts_path = args.u
        if not accounts_path.exists():
            raise FileNotFoundError(f"指定的账号信息文件不存在: {accounts_path}")
        try:
            accounts_df = read_excel(accounts_path, usecols=["账号", "密码"], dtype=str)
            accounts = {row["账号"]: row["密码"] for _, row in accounts_df.iterrows() if notna(row["账号"]) and notna(row["密码"])}
        except Exception as e:
            raise ValueError(f"读取账号信息文件失败: {e}")
    
    # 处理易班ID映射：仅在非恢复模式下处理新传入的映射
    if args.yb and not args.r:
        yiban_mapping = args.yb
    
    if yiban_mapping and not yiban_mapping.exists():
        raise FileNotFoundError(f"指定的易班ID映射文件不存在: {yiban_mapping}")
    
    if args.p and len(args.p) != 2:
        raise ValueError("参数 -p 需要传入两个值：IP:端口 和 配对码。")
            
        
    return CLIOptions(
        device = device if args.r else args.d,
        pair = args.p,
        additional_list = additional_list if args.r else args.a,
        console_log_level = args.cl,
        file_log_level = args.fl,
        file_dir = file_dir_c,
        init_device = args.i,
        recovered = args.r,
        accounts = accounts if accounts else None,
        yiban_mapping = yiban_mapping if yiban_mapping else None,
        click_other_tab = click_other_tab,
    )


def run_cli(argv: Optional[list[str]] = None) -> int:
    print("[bold cyan]到梦空间自动化脚本[/bold cyan]")
    print("="*60)
    
    try:
        options = _parse_args(argv)
    except Exception as e:
        print(f"[bold red]命令行参数解析失败:[/bold red] {e}")
        return 1
    
    activity_name = str(read_excel(
        options.file_dir.get(0),
        usecols=["活动名称"],
        nrows=2,
        dtype=str,
    ).iloc[1, 0])

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    base_dir = Path(sys.argv[0]).resolve().parent
    if options.recovered is None:
        print(f"[bold yellow]活动名称:[/bold yellow] [bold green]{activity_name}[/bold green]")
        output_dir = (
            base_dir
            / f"{activity_name.replace('“', '').replace('”', '').replace('"', '')}-{timestamp}"
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        print(f"[bold yellow]输出目录:[/bold yellow] {output_dir}")
    else:
        output_dir = options.recovered
        print(f"[bold yellow]恢复任务:[/bold yellow] {output_dir}")
    log_file = output_dir / "automation.log"
    
    logger = get_logger(
        console_log_level=options.console_log_level,
        file_log_level=options.file_log_level,
        log_file=log_file
    )
    
    logger.info("="*60)
    logger.info("启动到梦空间自动化脚本")
    logger.info(f"活动名称: {activity_name}")
    logger.info(f"输出目录: {output_dir}")
    logger.info(f"日志文件: {log_file}")
    logger.info(f"控制台日志级别: {options.console_log_level}")
    logger.info(f"文件日志级别: {options.file_log_level}")
    logger.info("="*60)
    
    config = AutomationConfig(
        device=options.device,
        pair=options.pair,
        additional_list=options.additional_list,
        console_log_level=options.console_log_level,
        file_log_level=options.file_log_level,
        file_dir=options.file_dir,
        output_dir=output_dir,
        init_device=options.init_device,
        accounts=options.accounts,
        activity_name=activity_name,
        yiban_mapping=options.yiban_mapping,
        click_other_tab=options.click_other_tab,
    )
    
    _save_to_json(config, output_dir)
    logger.info("配置信息已保存到 config.json")
    logger.debug(f"当前配置: {config}")

    # 优先使用用户指定的路径，否则查找系统安装的命令
    adb_path = os.environ.get("ADBUTILS_ADB_PATH") or shutil.which("adb")
    if not adb_path or not Path(adb_path).is_file():
        raise FileNotFoundError("找不到 adb；请安装 Android platform-tools 并确认 adb 在 PATH 中。")
    
    os.environ['ADBUTILS_ADB_PATH'] = adb_path
    logger.info(f"配置 ADB 路径: {adb_path}")

    app = AutomationApp(
        config=config,
        logger=logger,
    )
    
    print("[bold green]开始执行自动化任务...[/bold green]")
    print("="*60)

    return app.run()
