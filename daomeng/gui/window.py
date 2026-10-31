"""主窗口：把要跑的活动排成队列，看进度、看日志。"""
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..task import read_activity_name
from .worker import JobSpec, QueueWorker

ROW_INDENT = 175  # 左边标签列宽
ROW_TAIL = 160  # 没有分值控件的行，右侧留白与发分名单行对齐


class _TextDialog(QDialog):
    """一段说明 + 一个输入框，用来填学号、序号这些。"""

    def __init__(self, title: str, message: str, default: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        layout = QVBoxLayout(self)

        label = QLabel(message)
        label.setWordWrap(True)
        label.setMinimumWidth(460)

        self.edit = QLineEdit(default)
        ok = QPushButton("确定")
        cancel = QPushButton("取消")
        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)

        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(ok)
        buttons.addWidget(cancel)

        layout.addWidget(label)
        layout.addWidget(self.edit)
        layout.addLayout(buttons)
        self.edit.selectAll()
        self.edit.setFocus()


class MainWindow(QMainWindow):
    def __init__(self, base_dir: Path) -> None:
        super().__init__()
        self._base = base_dir
        self._worker: Optional[QueueWorker] = None
        self._out_dir: Optional[Path] = None
        self._dialog: Optional[QMessageBox] = None
        self.jobs: list[JobSpec] = []
        self.setWindowTitle("到梦空间批量发分")
        self.resize(940, 860)
        self._build_ui()
        self._set_state("idle")

    # ---- 界面搭建 ----

    def _build_ui(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        self.task_box = self._build_task_box()
        layout.addWidget(self.task_box)
        layout.addWidget(self._build_queue_box())
        layout.addWidget(self._build_device_box())
        layout.addWidget(self._build_progress_box())
        layout.addWidget(QLabel("运行日志"))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)
        layout.addWidget(self.log, 1)
        self.setCentralWidget(central)

    def _build_task_box(self) -> QGroupBox:
        box = QGroupBox("新建任务")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(9, 9, 9, 9)

        self.entry_zero = self._add_file_row(layout, "录取名单（不发放）")

        # 发分名单的份数和分值都可以改，不写死 1 分、2 分
        self.score_rows: list[tuple[QWidget, QLineEdit, QDoubleSpinBox]] = []
        self.score_rows_layout = QVBoxLayout()
        self.score_rows_layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(self.score_rows_layout)
        self._add_score_row("", 1.0)

        add = QPushButton("再加一份发分名单")
        add.clicked.connect(lambda: self._add_score_row("", 1.0))
        add_row = QHBoxLayout()
        add_row.addSpacing(ROW_INDENT)
        add_row.addWidget(add)
        add_row.addStretch()
        layout.addLayout(add_row)

        self.entry_extra = self._add_file_row(layout, "额外名单（可选，自带分值列）")
        self.entry_yiban = self._add_file_row(layout, "易班映射表（可选）")

        self.check_tab = QCheckBox("搜索前先切到「已获得其他学分」")
        self.check_tab.setContentsMargins(ROW_INDENT, 0, 0, 0)
        layout.addWidget(self.check_tab)

        self.btn_add = QPushButton("加入队列")
        self.btn_add.clicked.connect(self._add_to_queue)
        bottom = QHBoxLayout()
        bottom.addSpacing(ROW_INDENT)
        bottom.addWidget(self.btn_add)
        bottom.addStretch()
        layout.addLayout(bottom)
        return box

    def _build_queue_box(self) -> QGroupBox:
        box = QGroupBox("等候区（按顺序一条一条跑）")
        layout = QVBoxLayout(box)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["活动", "分值", "状态"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setMinimumHeight(120)
        layout.addWidget(self.table)

        self.btn_remove = QPushButton("删除选中")
        self.btn_remove.clicked.connect(self._remove_selected)
        self.btn_clear = QPushButton("清空队列")
        self.btn_clear.clicked.connect(self._clear_queue)
        self.btn_start = QPushButton("开始队列")
        self.btn_start.clicked.connect(self._start_queue)
        self.btn_stop = QPushButton("停止")
        self.btn_stop.clicked.connect(self._stop)
        self.btn_retry = QPushButton("重试这条")
        self.btn_retry.clicked.connect(lambda: self._decide("retry"))
        self.btn_skip = QPushButton("跳过这条")
        self.btn_skip.clicked.connect(lambda: self._decide("skip"))
        self.btn_open = QPushButton("打开运行目录")
        self.btn_open.clicked.connect(self._open_output)

        row = QHBoxLayout()
        row.addWidget(self.btn_start)
        row.addWidget(self.btn_stop)
        row.addWidget(self.btn_retry)
        row.addWidget(self.btn_skip)
        row.addSpacing(12)
        row.addWidget(self.btn_remove)
        row.addWidget(self.btn_clear)
        row.addWidget(self.btn_open)
        row.addStretch()
        layout.addLayout(row)
        return box

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

    def _add_file_row(self, layout: QVBoxLayout, title: str) -> QLineEdit:
        row = QHBoxLayout()
        label = QLabel(title)
        label.setFixedWidth(ROW_INDENT)
        entry = QLineEdit()
        button = QPushButton("浏览...")
        button.clicked.connect(lambda: self._pick_file(entry))
        row.addWidget(label)
        row.addWidget(entry, 1)
        row.addWidget(button)
        row.addSpacing(ROW_TAIL)
        layout.addLayout(row)
        return entry

    def _add_score_row(self, path: str = "", points: float = 1.0) -> None:
        # 一份表对应一个分值，份数任意
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)

        label = QLabel("发分名单")
        label.setFixedWidth(ROW_INDENT)
        entry = QLineEdit(path)
        browse = QPushButton("浏览...")
        browse.clicked.connect(lambda: self._pick_file(entry))
        spin = QDoubleSpinBox()
        spin.setDecimals(1)
        spin.setRange(0.1, 100.0)
        spin.setSingleStep(0.5)
        spin.setValue(points)
        spin.setSuffix(" 分")
        spin.setFixedWidth(90)
        remove = QPushButton("删除")
        remove.setFixedWidth(60)
        remove.clicked.connect(lambda: self._remove_score_row(container))

        row.addWidget(label)
        row.addWidget(entry, 1)
        row.addWidget(browse)
        row.addWidget(spin)
        row.addWidget(remove)
        self.score_rows_layout.addWidget(container)
        self.score_rows.append((container, entry, spin))

    def _remove_score_row(self, container: QWidget) -> None:
        for item in self.score_rows:
            if item[0] is container:
                self.score_rows.remove(item)
                break
        container.setParent(None)
        container.deleteLater()

    # ---- 选择文件 ----

    def _pick_file(self, entry: QLineEdit) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择 Excel 表格", str(self._base), "表格 (*.xlsx *.xls)")
        if path:
            entry.setText(path)

    # ---- 队列 ----

    def _add_to_queue(self) -> None:
        try:
            spec = self._collect_spec()
        except Exception as err:
            QMessageBox.warning(self, "还不能加入队列", str(err))
            return
        self.jobs.append(spec)
        self._append_row(spec)
        self._set_state("idle")

    def _append_row(self, spec: JobSpec) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(spec.title))
        self.table.setItem(row, 1, QTableWidgetItem(self._points_text(spec)))
        self.table.setItem(row, 2, QTableWidgetItem("等待中"))

    @staticmethod
    def _points_text(spec: JobSpec) -> str:
        scores = "、".join(f"{points:.1f}" for points in sorted(spec.files) if points > 0)
        if spec.additional is not None:
            scores = f"{scores}＋额外" if scores else "额外名单"
        return scores or "-"

    def _remove_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        self.table.removeRow(row)
        del self.jobs[row]

    def _clear_queue(self) -> None:
        self.table.setRowCount(0)
        self.jobs.clear()

    def _collect_spec(self) -> JobSpec:
        roster = self.entry_zero.text().strip()
        if not roster:
            raise ValueError("请先选择录取名单")
        files: dict[float, Path] = {0.0: Path(roster)}

        for _, entry, spin in self.score_rows:
            text = entry.text().strip()
            if not text:
                continue
            points = round(spin.value(), 1)
            if points in files:
                raise ValueError(f"{points:.1f} 分出现了两份名单，请合并成一份，或用「额外名单」单独指定")
            files[points] = Path(text)

        if len(files) == 1 and not self.entry_extra.text().strip():
            raise ValueError("至少要选一份发分名单，或用「额外名单」直接写学号和分值")

        return JobSpec(
            title=read_activity_name(files[0]),
            files=files,
            device=self.entry_device.text().strip() or None,
            init_device=self.check_init.isChecked(),
            additional=Path(self.entry_extra.text().strip()) if self.entry_extra.text().strip() else None,
            yiban=Path(self.entry_yiban.text().strip()) if self.entry_yiban.text().strip() else None,
            click_other_tab=self.check_tab.isChecked(),
        )

    def _start_queue(self) -> None:
        if not self.jobs:
            QMessageBox.warning(self, "还没有任务", "先用上面的表单填一个活动，点「加入队列」。")
            return

        # 设备设置是全局的，开跑前统一套到还没跑过的任务上
        device = self.entry_device.text().strip() or None
        init_device = self.check_init.isChecked()
        for job in self.jobs:
            if job.run_dir is None:
                job.device = device
                job.init_device = init_device

        self.log.clear()
        self._reset_progress()
        self._set_state("running")

        self._worker = QueueWorker(self.jobs, self._base)
        self._worker.log_line.connect(self.log.appendPlainText)
        self._worker.total_changed.connect(self._on_total)
        self._worker.point_started.connect(self._on_point)
        self._worker.student_changed.connect(self._on_student)
        self._worker.student_done.connect(self._on_done)
        self._worker.point_done.connect(self._on_point_done)
        self._worker.need_user.connect(self._on_need_user)
        self._worker.need_text.connect(self._on_need_text)
        self._worker.need_choice.connect(self._on_need_choice)
        self._worker.job_started.connect(self._on_job_started)
        self._worker.job_status.connect(self._on_job_status)
        self._worker.job_finished.connect(self._on_job_finished)
        self._worker.queue_state.connect(self._on_queue_state)
        self._worker.start()

    def _decide(self, action: str) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._set_state("running")
            self.label_state.setText("继续跑队列...")
            self._worker.decide(action)

    def _stop(self) -> None:
        if self._dialog is not None:
            self._dialog.close()
        if self._worker is not None and self._worker.isRunning():
            self._worker.request_stop()
            self.label_state.setText("正在停止，处理完手上这个学生就停...")
            self.btn_stop.setEnabled(False)

    def _open_output(self) -> None:
        if self._out_dir is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._out_dir)))

    # ---- 后台线程的信号 ----

    def _reset_progress(self) -> None:
        self.bar_total.setMaximum(1)
        self.bar_total.setValue(0)
        self.bar_point.setMaximum(1)
        self.bar_point.setValue(0)
        self.label_point.setText("当前分值：-")

    def _on_job_started(self, index: int) -> None:
        job = self.jobs[index]
        self._reset_progress()
        self.label_state.setText(f"第 {index + 1}/{len(self.jobs)} 条：{job.title}")
        self.log.appendPlainText(f"———— 第 {index + 1} 条：{job.title} ————")

    def _on_job_status(self, index: int, text: str) -> None:
        item = self.table.item(index, 2)
        if item is not None:
            item.setText(text)

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
        dialog = _TextDialog("需要输入", message, default, self)
        accepted = dialog.exec()
        self._worker.answer(dialog.edit.text() if accepted else default)

    def _on_need_choice(self, message: str, options, default: str) -> None:
        box, answers = self._choice_box(message, options, default)
        box.exec()
        self._worker.answer(answers.get(box.clickedButton(), default))

    def _choice_box(self, message: str, options, default: str):
        # 首行是摘要，明细收进「显示详细信息」，免得把窗口撑爆
        headline, _, detail = str(message).partition("\n\n")
        box = QMessageBox(self)
        box.setWindowTitle("需要你确认")
        box.setText(headline)
        if detail:
            box.setDetailedText(detail)

        answers = {}
        for key, text in options:
            button = box.addButton(f"{key}. {text}", QMessageBox.ButtonRole.AcceptRole)
            answers[button] = key
            if key == default:
                box.setDefaultButton(button)
        return box, answers

    def _on_job_finished(self, index: int, ok: bool, out_dir: str, message: str) -> None:
        if out_dir:
            self._out_dir = Path(out_dir)
            self.btn_open.setEnabled(True)
        if not ok:
            QMessageBox.warning(
                self,
                "这一条失败了",
                f"{self.jobs[index].title}\n\n{message}\n\n"
                "队列已经暂停。处理好手机上的情况后，可以「重试这条」接着跑，或者「跳过这条」跑下一个。",
            )

    def _on_queue_state(self, state: str) -> None:
        if state == "运行中":
            self._set_state("running")
        elif state == "已暂停":
            self._set_state("paused")
            self.label_state.setText("队列已暂停，等你决定重试还是跳过")
        elif state in ("已停止", "已结束"):
            self._set_state("idle")
            if state == "已结束":
                self.label_state.setText("队列全部跑完")
                QMessageBox.information(self, "队列结束", "队列里的任务都跑完了，结果已导出到各自的运行目录。")
            else:
                self.label_state.setText("已停止，进度已保存")

    def _set_state(self, state: str) -> None:
        running = state == "running"
        paused = state == "paused"
        idle = state == "idle"

        self.task_box.setEnabled(idle)
        self.table.setEnabled(not running)
        self.btn_remove.setEnabled(not running)
        self.btn_clear.setEnabled(not running)
        self.btn_start.setEnabled(idle and bool(self.jobs))
        self.btn_stop.setEnabled(running or paused)
        self.btn_retry.setEnabled(paused)
        self.btn_skip.setEnabled(paused)
        self.check_init.setEnabled(idle)
        self.entry_device.setReadOnly(running or paused)

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
