"""主窗口：选任务、看进度、看日志。"""
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .worker import GuiWorker, JobSpec


class MainWindow(QMainWindow):
    def __init__(self, base_dir: Path) -> None:
        super().__init__()
        self._base = base_dir
        self._worker: Optional[GuiWorker] = None
        self._out_dir: Optional[Path] = None
        self._dialog: Optional[QMessageBox] = None
        self.setWindowTitle("到梦空间批量发分")
        self.resize(900, 760)
        self._build_ui()
        self._set_running(False)

    # ---- 界面搭建 ----

    def _build_ui(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(self._build_task_box())
        layout.addWidget(self._build_device_box())
        layout.addLayout(self._build_buttons())
        layout.addWidget(self._build_progress_box())
        layout.addWidget(QLabel("运行日志"))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)
        layout.addWidget(self.log, 1)
        self.setCentralWidget(central)

    def _build_task_box(self) -> QGroupBox:
        box = QGroupBox("任务")
        layout = QVBoxLayout(box)

        self.mode_new = QRadioButton("新建任务")
        self.mode_resume = QRadioButton("继续上次任务")
        self.mode_new.setChecked(True)
        modes = QHBoxLayout()
        modes.addWidget(self.mode_new)
        modes.addWidget(self.mode_resume)
        modes.addStretch()
        layout.addLayout(modes)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_new_page())
        self.pages.addWidget(self._build_resume_page())
        layout.addWidget(self.pages)

        self.mode_new.toggled.connect(self._on_mode_changed)
        return box

    def _build_new_page(self) -> QWidget:
        page = QWidget()
        grid = QGridLayout(page)
        grid.setContentsMargins(0, 0, 0, 0)

        self.entry_zero = self._add_file_row(grid, 0, "录取名单（0 分）")
        self.entry_first = self._add_file_row(grid, 1, "1 分名单")
        self.entry_second = self._add_file_row(grid, 2, "2 分名单")
        self.entry_extra = self._add_file_row(grid, 3, "额外名单（可选）")
        self.entry_yiban = self._add_file_row(grid, 4, "易班映射表（可选）")

        self.check_tab = QCheckBox("搜索前先切到「已获得其他学分」")
        grid.addWidget(self.check_tab, 5, 1, 1, 2)
        return page

    def _build_resume_page(self) -> QWidget:
        page = QWidget()
        grid = QGridLayout(page)
        grid.setContentsMargins(0, 0, 0, 0)

        self.entry_resume = QLineEdit()
        self.entry_resume.setPlaceholderText("上次自动生成的运行目录，里面有 students.db 和 config.json")
        button = QPushButton("选择目录...")
        button.clicked.connect(self._pick_resume_dir)
        grid.addWidget(QLabel("运行目录"), 0, 0)
        grid.addWidget(self.entry_resume, 0, 1)
        grid.addWidget(button, 0, 2)

        hint = QLabel("表格路径改过、文件被删时，续跑会报「指定的文件路径不存在」。")
        hint.setWordWrap(True)
        grid.addWidget(hint, 1, 1, 1, 2)
        return page

    def _build_device_box(self) -> QGroupBox:
        box = QGroupBox("设备")
        grid = QGridLayout(box)

        self.entry_device = QLineEdit()
        self.entry_device.setPlaceholderText("例如 192.168.1.10:5555，留空则用数据线连接")
        grid.addWidget(QLabel("无线调试地址"), 0, 0)
        grid.addWidget(self.entry_device, 0, 1)

        self.check_init = QCheckBox("首次连接，初始化设备（安装 uiautomator2）")
        grid.addWidget(self.check_init, 1, 1)
        return box

    def _build_buttons(self) -> QHBoxLayout:
        self.btn_start = QPushButton("开始")
        self.btn_start.clicked.connect(self._start)
        self.btn_stop = QPushButton("停止")
        self.btn_stop.clicked.connect(self._stop)
        self.btn_open = QPushButton("打开运行目录")
        self.btn_open.clicked.connect(self._open_output)

        row = QHBoxLayout()
        row.addWidget(self.btn_start)
        row.addWidget(self.btn_stop)
        row.addWidget(self.btn_open)
        row.addStretch()
        return row

    def _build_progress_box(self) -> QGroupBox:
        box = QGroupBox("进度")
        grid = QGridLayout(box)

        self.label_state = QLabel("准备就绪")
        self.label_point = QLabel("当前分值：-")
        self.bar_total = QProgressBar()
        self.bar_total.setFormat("%v / %m 人")
        self.bar_total.setMaximum(1)
        self.bar_point = QProgressBar()
        self.bar_point.setFormat("%v / %m 人")
        self.bar_point.setMaximum(1)

        grid.addWidget(self.label_state, 0, 0)
        grid.addWidget(self.label_point, 0, 1)
        grid.addWidget(QLabel("总进度"), 1, 0)
        grid.addWidget(self.bar_total, 1, 1)
        grid.addWidget(QLabel("本分值"), 2, 0)
        grid.addWidget(self.bar_point, 2, 1)
        grid.setColumnStretch(1, 1)
        return box

    def _add_file_row(self, grid: QGridLayout, row: int, title: str) -> QLineEdit:
        entry = QLineEdit()
        button = QPushButton("浏览...")
        button.clicked.connect(lambda: self._pick_file(entry))
        grid.addWidget(QLabel(title), row, 0)
        grid.addWidget(entry, row, 1)
        grid.addWidget(button, row, 2)
        return entry

    # ---- 选择文件 ----

    def _pick_file(self, entry: QLineEdit) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择 Excel 表格", str(self._base), "表格 (*.xlsx *.xls)")
        if path:
            entry.setText(path)

    def _pick_resume_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择运行目录", str(self._base))
        if path:
            self.entry_resume.setText(path)

    def _on_mode_changed(self) -> None:
        self.pages.setCurrentIndex(0 if self.mode_new.isChecked() else 1)

    # ---- 开始 / 停止 ----

    def _start(self) -> None:
        try:
            spec = self._collect_spec()
        except ValueError as err:
            QMessageBox.warning(self, "还不能开始", str(err))
            return

        self.log.clear()
        self.bar_total.setValue(0)
        self.bar_point.setValue(0)
        self._set_running(True)
        self.label_state.setText("正在启动...")

        self._worker = GuiWorker(spec, self._base)
        self._worker.log_line.connect(self.log.appendPlainText)
        self._worker.total_changed.connect(self._on_total)
        self._worker.point_started.connect(self._on_point)
        self._worker.student_changed.connect(self._on_student)
        self._worker.student_done.connect(self._on_done)
        self._worker.point_done.connect(self._on_point_done)
        self._worker.need_user.connect(self._on_need_user)
        self._worker.need_text.connect(self._on_need_text)
        self._worker.run_finished.connect(self._on_finished)
        self._worker.start()

    def _collect_spec(self) -> JobSpec:
        device = self.entry_device.text().strip() or None
        if self.mode_resume.isChecked():
            text = self.entry_resume.text().strip()
            if not text:
                raise ValueError("请先选择上次的运行目录")
            return JobSpec(
                resume_dir=Path(text),
                files={},
                device=device,
                init_device=False,
                additional=None,
                yiban=None,
                click_other_tab=False,
            )

        files: dict[float, Path] = {}
        for points, entry in ((0.0, self.entry_zero), (1.0, self.entry_first), (2.0, self.entry_second)):
            text = entry.text().strip()
            if text:
                files[points] = Path(text)
        if 0.0 not in files:
            raise ValueError("请先选择录取名单（0 分）")
        if len(files) < 2:
            raise ValueError("再选一份「1 分名单」或「2 分名单」才有分可发")

        return JobSpec(
            resume_dir=None,
            files=files,
            device=device,
            init_device=self.check_init.isChecked(),
            additional=Path(self.entry_extra.text().strip()) if self.entry_extra.text().strip() else None,
            yiban=Path(self.entry_yiban.text().strip()) if self.entry_yiban.text().strip() else None,
            click_other_tab=self.check_tab.isChecked(),
        )

    def _stop(self) -> None:
        if self._dialog is not None:
            self._dialog.close()
        if self._worker is not None:
            self._worker.request_stop()
            self.label_state.setText("正在停止，处理完手上这个学生就停...")
            self.btn_stop.setEnabled(False)

    def _open_output(self) -> None:
        if self._out_dir is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._out_dir)))

    # ---- 后台线程的信号 ----

    def _on_total(self, total: int) -> None:
        self.bar_total.setMaximum(max(total, 1))
        self.bar_total.setValue(0)
        self.label_state.setText(f"共 {total} 人待处理")

    def _on_point(self, point: float, count: int) -> None:
        self.label_point.setText(f"当前分值：{point:.1f} 分")
        self.bar_point.setMaximum(max(count, 1))
        self.bar_point.setValue(0)

    def _on_student(self, text: str) -> None:
        self.label_state.setText(f"正在处理：{text}")

    def _on_done(self, done: int, total: int) -> None:
        self.bar_total.setValue(done)
        self.bar_point.setValue(self.bar_point.value() + 1)
        self.label_state.setText(f"已完成 {done} / {total} 人")

    def _on_point_done(self, point: float) -> None:
        self.label_point.setText(f"{point:.1f} 分处理完成")

    def _on_need_user(self, message: str) -> None:
        # 用非模态框，否则窗口被挡住就点不到「停止」
        self._dialog = QMessageBox(self)
        self._dialog.setWindowTitle("需要你在手机上操作")
        self._dialog.setText(message)
        self._dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
        self._dialog.setWindowModality(Qt.WindowModality.NonModal)
        self._dialog.finished.connect(self._on_dialog_closed)
        self._dialog.show()  # open() 会把模态改回 WindowModal

    def _on_dialog_closed(self, _result: int) -> None:
        self._dialog = None
        if self._worker is not None:
            self._worker.ack()

    def _on_need_text(self, message: str, default: str) -> None:
        text, ok = QInputDialog.getText(self, "需要输入", message, text=default)
        self._worker.answer(text if ok else default)

    def _on_finished(self, ok: bool, out_dir: str, message: str) -> None:
        self._set_running(False)
        self.label_state.setText(message)
        if out_dir:
            self._out_dir = Path(out_dir)
            self.btn_open.setEnabled(True)
        QMessageBox.information(self, "任务结束", message)

    def _set_running(self, running: bool) -> None:
        self.btn_start.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        self.pages.setEnabled(not running)
        self.mode_new.setEnabled(not running)
        self.mode_resume.setEnabled(not running)
        self.check_init.setEnabled(not running)
        self.entry_device.setReadOnly(running)

    # ---- 关窗 ----

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._worker is not None and self._worker.isRunning():
            answer = QMessageBox.question(self, "还在跑", "任务还在跑，确定要停止并退出吗？")
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._worker.request_stop()
            self._worker.wait(30000)
        event.accept()
