"""图形界面的后台线程：跑发分流程，把进度和日志转成 Qt 信号。"""
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThread, Signal

from ..batch import BatchHooks, run_session
from ..config import AutomationConfig, Student
from ..logging_utils import get_logger
from ..task import load_config, new_output_dir, read_activity_name, resolve_adb, save_config


@dataclass
class JobSpec:
    """界面上填好、交给后台线程的任务参数。"""

    resume_dir: Optional[Path]
    files: dict[float, Path]
    device: Optional[str]
    init_device: bool
    additional: Optional[Path]
    yiban: Optional[Path]
    click_other_tab: bool


class _SignalHandler(logging.Handler):
    """把每条日志转发成界面里的一行文字。"""

    def __init__(self, emit_line) -> None:
        super().__init__(logging.INFO)
        self._emit_line = emit_line
        self.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        self._emit_line(self.format(record))


class GuiWorker(QThread, BatchHooks):
    """跑一轮发分；所有回调通过信号送回界面线程。"""

    log_line = Signal(str)
    total_changed = Signal(int)
    point_started = Signal(float, int)
    student_changed = Signal(str)
    student_done = Signal(int, int)
    point_done = Signal(float)
    need_user = Signal(str)
    need_text = Signal(str, str)
    run_finished = Signal(bool, str, str)  # 是否跑完, 运行目录, 给用户看的提示

    def __init__(self, spec: JobSpec, base_dir: Path) -> None:
        super().__init__()
        self._spec = spec
        self._base = base_dir
        self._logger = None
        self._stop = threading.Event()
        self._ack = threading.Event()
        self._answer = ""
        self._total = 0
        self._done = 0
        self.output_dir: Optional[Path] = None

    # ---- 界面调用 ----

    def request_stop(self) -> None:
        self._stop.set()
        self._ack.set()  # 正卡在等人工确认时也放行

    def ack(self) -> None:
        self._ack.set()

    def answer(self, text: str) -> None:
        self._answer = text
        self._ack.set()

    def _wait_for_ui(self) -> None:
        self._ack.wait()
        self._ack.clear()

    # ---- 人工干预回调（在后台线程里阻塞，等界面唤醒）----

    def _wait_user(self, message: str) -> None:
        self.need_user.emit(message)
        self._wait_for_ui()

    def _ask_user(self, message: str, default: str) -> str:
        self.need_text.emit(message, default)
        self._wait_for_ui()
        return self._answer or default

    # ---- 主流程 ----

    def run(self) -> None:
        try:
            resolve_adb()
            config = self._build_config()
            self.output_dir = config.output_dir
            self._logger = self._build_logger(config.output_dir)
            self._logger.info(f"活动名称: {config.activity_name}")
            self._logger.info(f"输出目录: {config.output_dir}")

            run_session(config, self._logger, self)
            if self._stop.is_set():
                self.run_finished.emit(False, str(config.output_dir), "已停止，进度已保存，可以接着跑")
            else:
                self.run_finished.emit(True, str(config.output_dir), "全部完成，结果已导出")
        except Exception as err:
            logging.getLogger().exception("任务失败")
            self.run_finished.emit(False, str(self.output_dir or ""), f"任务失败: {err}")

    def _build_config(self) -> AutomationConfig:
        spec = self._spec
        if spec.resume_dir:
            saved = load_config(spec.resume_dir / "config.json")
            files = {pts: Path(path) for path, pts in (saved.get("file_dir") or [])}
            output_dir = spec.resume_dir
            additional = saved.get("additional_list")
            yiban = saved.get("yiban_mapping")
            click_tab = saved["click_other_tab"]
            accounts = saved.get("accounts")
        else:
            files = spec.files
            output_dir = None
            additional = spec.additional
            yiban = spec.yiban
            click_tab = spec.click_other_tab
            accounts = None

        activity_name = read_activity_name(files[0])
        if output_dir is None:
            output_dir = new_output_dir(self._base, activity_name)

        config = AutomationConfig(
            device=spec.device,
            pair=None,
            additional_list=additional,
            console_log_level="INFO",
            file_log_level="INFO",
            file_dir=files,
            output_dir=output_dir,
            init_device=spec.init_device,
            accounts=accounts,
            activity_name=activity_name,
            yiban_mapping=yiban,
            click_other_tab=click_tab,
        )
        save_config(config, output_dir)
        return config

    def _build_logger(self, output_dir: Path) -> logging.Logger:
        handler = _SignalHandler(self.log_line.emit)
        return get_logger(
            console_log_level="INFO",
            log_file=output_dir / "automation.log",
            file_log_level="INFO",
            extra_handlers=[handler],
        )

    # ---- BatchHooks ----

    def on_loop_start(self, controller) -> None:
        controller.set_user_hooks(wait=self._wait_user, ask=self._ask_user)

    def on_total(self, total: int) -> None:
        self._total = total
        self.total_changed.emit(total)

    def on_point(self, point: float, count: int) -> None:
        self.point_started.emit(point, count)

    def on_student(self, student: Student) -> None:
        self.student_changed.emit(f"{student.name}（{student.student_id}） {student.points:.1f} 分")

    def on_done(self, student: Student) -> None:
        self._done += 1
        self.student_done.emit(self._done, self._total)

    def on_point_end(self, point: float) -> None:
        self.point_done.emit(point)

    def should_stop(self) -> bool:
        return self._stop.is_set()

    def finished_normally(self) -> bool:
        return not self._stop.is_set()
