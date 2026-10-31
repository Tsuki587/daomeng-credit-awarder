"""图形界面的后台线程：按队列顺序跑发分流程，把进度和日志转成 Qt 信号。"""
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QThread, Signal

from ..batch import BatchHooks, run_session
from ..config import AutomationConfig, Student
from ..logging_utils import get_logger
from ..task import load_config, new_output_dir, read_activity_name, resolve_adb, save_config


@dataclass
class JobSpec:
    """队列里的一条任务。"""

    title: str
    files: dict[float, Path]
    device: Optional[str]
    init_device: bool
    additional: Optional[Path]
    yiban: Optional[Path]
    click_other_tab: bool
    run_dir: Optional[Path] = None  # 跑过一次后就是它的运行目录，重试时从这里接着跑


class _SignalHandler(logging.Handler):
    """把每条日志转发成界面里的一行文字。"""

    def __init__(self, emit_line) -> None:
        super().__init__(logging.INFO)
        self._emit_line = emit_line
        self.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        self._emit_line(self.format(record))


class SessionRunner(QObject, BatchHooks):
    """跑一轮发分；所有回调通过信号送回界面线程。"""

    log_line = Signal(str)
    total_changed = Signal(int)
    point_started = Signal(float, int)
    student_changed = Signal(str)
    student_done = Signal(int, int)
    point_done = Signal(float)
    need_user = Signal(str)
    need_text = Signal(str, str)
    need_choice = Signal(str, object, str)

    def __init__(self, base_dir: Path) -> None:
        super().__init__()
        self._base = base_dir
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

    def _choose(self, message: str, options, default: str) -> str:
        self.need_choice.emit(message, options, default)
        self._wait_for_ui()
        return self._answer or default

    # ---- 主流程 ----

    def run_one(self, spec: JobSpec) -> tuple[str, Optional[Path], str]:
        """跑一条任务，返回（结果, 运行目录, 说明），结果是 done / stopped / failed。"""
        self._stop.clear()
        self._ack.clear()
        self._answer = ""
        self._total = 0
        self._done = 0
        self.output_dir = None
        try:
            resolve_adb()
            config = self._build_config(spec)
            self.output_dir = config.output_dir
            logger = self._build_logger(config.output_dir)
            logger.info(f"活动名称: {config.activity_name}")
            logger.info(f"输出目录: {config.output_dir}")

            run_session(config, logger, self)
            if self._stop.is_set():
                return "stopped", config.output_dir, "已停止，进度已保存，可以接着跑"
            return "done", config.output_dir, "全部完成，结果已导出"
        except Exception as err:
            logging.getLogger().exception("任务失败")
            return "failed", self.output_dir, f"任务失败: {err}"

    def _build_config(self, spec: JobSpec) -> AutomationConfig:
        saved = {}
        if spec.run_dir is not None and (spec.run_dir / "config.json").exists():
            saved = load_config(spec.run_dir / "config.json")
            files = {pts: Path(path) for path, pts in (saved.get("file_dir") or [])}
            output_dir = spec.run_dir
        else:
            files = spec.files
            output_dir = None

        activity_name = read_activity_name(files[0])
        if output_dir is None:
            output_dir = new_output_dir(self._base, activity_name)

        config = AutomationConfig(
            device=spec.device,
            pair=None,
            additional_list=saved.get("additional_list") or spec.additional,
            console_log_level="INFO",
            file_log_level="INFO",
            file_dir=files,
            output_dir=output_dir,
            init_device=spec.init_device,
            accounts=saved.get("accounts"),
            activity_name=activity_name,
            yiban_mapping=saved.get("yiban_mapping") or spec.yiban,
            click_other_tab=saved.get("click_other_tab", spec.click_other_tab),
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

    def on_prepare(self, controller, file_manager) -> None:
        # 读名单时的「无效学号」「姓名不符」确认也走弹窗，命令行那套 input() 在界面里没有 stdin
        controller.set_user_hooks(wait=self._wait_user, ask=self._ask_user)
        file_manager.set_user_hooks(ask=self._ask_user, choose=self._choose)

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


class QueueWorker(QThread):
    """按顺序把队列里的任务跑完；某条失败就停下等界面决定。"""

    log_line = Signal(str)
    total_changed = Signal(int)
    point_started = Signal(float, int)
    student_changed = Signal(str)
    student_done = Signal(int, int)
    point_done = Signal(float)
    need_user = Signal(str)
    need_text = Signal(str, str)
    need_choice = Signal(str, object, str)

    job_started = Signal(int)
    job_status = Signal(int, str)
    job_finished = Signal(int, bool, str, str)  # 第几条, 是否成功, 运行目录, 说明
    queue_state = Signal(str)  # 运行中 / 已暂停 / 已停止 / 已结束

    def __init__(self, jobs: list[JobSpec], base_dir: Path) -> None:
        super().__init__()
        self.jobs = jobs
        self._runner = SessionRunner(base_dir)
        self._decision = "retry"
        self._action = threading.Event()
        self._stopped = threading.Event()

        self._runner.log_line.connect(self.log_line.emit)
        self._runner.total_changed.connect(self.total_changed.emit)
        self._runner.point_started.connect(self.point_started.emit)
        self._runner.student_changed.connect(self.student_changed.emit)
        self._runner.student_done.connect(self.student_done.emit)
        self._runner.point_done.connect(self.point_done.emit)
        self._runner.need_user.connect(self.need_user.emit)
        self._runner.need_text.connect(self.need_text.emit)
        self._runner.need_choice.connect(self.need_choice.emit)

    # ---- 界面调用 ----

    def request_stop(self) -> None:
        self._stopped.set()
        self._decision = "stop"
        self._action.set()
        self._runner.request_stop()

    def decide(self, action: str) -> None:
        """失败暂停后由界面决定：retry 重试这条，skip 跳过这条，stop 停止整条队列。"""
        self._decision = action
        self._action.set()

    def ack(self) -> None:
        self._runner.ack()

    def answer(self, text: str) -> None:
        self._runner.answer(text)

    def _wait_decision(self) -> str:
        self._action.wait()
        self._action.clear()
        return self._decision

    # ---- 主流程 ----

    def run(self) -> None:
        index = 0
        while index < len(self.jobs) and not self._stopped.is_set():
            job = self.jobs[index]
            self.job_started.emit(index)
            self.job_status.emit(index, "运行中")
            self.queue_state.emit("运行中")

            status, out_dir, message = self._runner.run_one(job)
            job.run_dir = out_dir
            if status == "stopped" or self._stopped.is_set():
                self.job_status.emit(index, "已停止")
                self.queue_state.emit("已停止")
                return

            self.job_finished.emit(index, status == "done", str(out_dir or ""), message)
            if status == "failed":
                self.job_status.emit(index, "失败")
                self.queue_state.emit("已暂停")
                decision = self._wait_decision()
                if decision == "stop":
                    self.queue_state.emit("已停止")
                    return
                if decision == "skip":
                    index += 1
                    continue
                continue  # retry：同一条再跑一次，这次从它的运行目录接着来

            self.job_status.emit(index, "完成")
            index += 1

        self.queue_state.emit("已结束")
