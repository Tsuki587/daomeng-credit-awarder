import logging

from rich.console import Group
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from .batch import BatchHooks, run_session
from .config import AutomationConfig, Student, progress_
from .device_controller import DeviceController


class _RichHooks(BatchHooks):
    """命令行界面：rich 进度条 + Live 面板。"""

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger
        self._progress = progress_()
        self._status = Text("准备开始...", style="italic dim")
        self._live = None
        self._controller = None
        self._total_task = None
        self._point_task = None

    def on_loop_start(self, controller: DeviceController) -> None:
        self._controller = controller
        self._live = Live(
            Panel(Group(self._progress, self._status)),
            refresh_per_second=10,
            transient=False,
        )
        self._live.start()
        # Live 交给控制器，需要人工干预时它会先暂停显示
        controller.set_live(self._live)
        self._total_task = self._progress.add_task("总进度", total=0)

    def on_total(self, total: int) -> None:
        self._progress.update(self._total_task, total=total)

    def on_point(self, point: float, count: int) -> None:
        self._point_task = self._progress.add_task(f"颁发 {point:.1f} 分", total=count)

    def on_student(self, student: Student) -> None:
        self._status.plain = f"当前处理学生: {student.student_id}，姓名: {student.name}，学分: {student.points:.1f}"

    def on_done(self, student: Student) -> None:
        self._progress.update(self._total_task, advance=1)
        self._progress.update(self._point_task, advance=1)

    def on_point_end(self, point: float) -> None:
        self._progress.remove_task(self._point_task)

    def on_loop_end(self) -> None:
        self._status.plain = "全部完成 ✅"
        self._controller.set_live(None)
        self._live.stop()


class AutomationApp:
    def __init__(self, config: AutomationConfig, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger

    def run(self) -> int:
        try:
            run_session(self.config, self.logger, _RichHooks(self.logger))
            return 0
        except Exception as e:
            self.logger.error("=" * 60)
            self.logger.error(f"自动化任务失败: {e}")
            self.logger.exception("详细错误信息:")
            self.logger.error("=" * 60)
            return 1
