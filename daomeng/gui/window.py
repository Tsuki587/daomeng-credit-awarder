"""主窗口：把要跑的活动排成队列，看进度、看日志。"""
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QCloseEvent, QColor, QDesktopServices, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
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
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..task import compare_resume, load_config, read_activity_name
from . import theme
from .worker import JobSpec, QueueWorker

LABEL_WIDTH = 88  # 表单左侧标签宽度
STATUS_COLORS = {
    "等待中": theme.MUTED,
    "运行中": theme.PRIMARY,
    "完成": theme.SUCCESS,
    "失败": theme.ERROR,
    "已停止": theme.WARNING,
}


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
        ok.setObjectName("primary")
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
        self.setWindowIcon(theme.icon())
        self.resize(1180, 820)
        self.setMinimumSize(1040, 730)
        self._build_ui()
        self._set_state("idle")

    # ---- 界面搭建 ----

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(16, 14, 16, 16)
        outer.setSpacing(12)
        outer.addLayout(self._build_header())

        body = QHBoxLayout()
        body.setSpacing(12)

        left = QWidget()
        left.setFixedWidth(440)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(12)
        self.task_box = self._build_task_card()
        left_layout.addWidget(self.task_box)
        left_layout.addWidget(self._build_device_card())
        left_layout.addStretch()
        body.addWidget(left)

        right = QVBoxLayout()
        right.setSpacing(12)
        right.addWidget(self._build_queue_card(), 3)
        right.addWidget(self._build_progress_card())
        right.addWidget(self._build_log_card(), 2)
        body.addLayout(right, 1)

        outer.addLayout(body, 1)
        self.setCentralWidget(root)

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(theme.icon().pixmap(36, 36))
        title = QLabel("到梦空间批量发分")
        title.setObjectName("h1")
        self.chip = QLabel("空闲")
        self.chip.setObjectName("chip")

        row.addWidget(logo)
        row.addSpacing(4)
        row.addWidget(title)
        row.addStretch()
        row.addWidget(self.chip)
        return row

    def _card(self, title: str, hint: str = "") -> tuple[QFrame, QVBoxLayout, QHBoxLayout]:
        frame = QFrame()
        frame.setObjectName("card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(8)
        if title:
            label = QLabel(title)
            label.setObjectName("cardTitle")
            head.addWidget(label)
        if hint:
            note = QLabel(hint)
            note.setObjectName("hint")
            head.addWidget(note)
        head.addStretch()
        layout.addLayout(head)
        return frame, layout, head

    def _build_task_card(self) -> QFrame:
        frame, layout, _ = self._card("新建任务", "活动名称和名单都在这里填")

        row = QHBoxLayout()
        row.setSpacing(8)
        label = QLabel("活动名称")
        label.setFixedWidth(LABEL_WIDTH)
        self.entry_activity = QLineEdit()
        self.entry_activity.setPlaceholderText("在 App 里看到的完整活动名")
        row.addWidget(label)
        row.addWidget(self.entry_activity, 1)
        layout.addLayout(row)

        # 发分名单的份数和分值都可以改，不写死 1 分、2 分
        self.score_rows: list[tuple[QWidget, QLineEdit, QDoubleSpinBox]] = []
        self.score_rows_layout = QVBoxLayout()
        self.score_rows_layout.setContentsMargins(0, 0, 0, 0)
        self.score_rows_layout.setSpacing(8)
        layout.addLayout(self.score_rows_layout)
        self._add_score_row("", 1.0)

        add = QPushButton("再加一份发分名单")
        add.clicked.connect(lambda: self._add_score_row("", 1.0))
        add_row = QHBoxLayout()
        add_row.addSpacing(LABEL_WIDTH)
        add_row.addWidget(add)
        add_row.addStretch()
        layout.addLayout(add_row)

        self.entry_roster = self._add_file_row(layout, "录取名单", "可选，留空就按名单里的学号直接发")
        self.entry_extra = self._add_file_row(layout, "额外名单", "可选，自带姓名、学号、分值")
        self.entry_yiban = self._add_file_row(layout, "易班映射", "可选，名单里只有易班 ID 才要")

        self.check_tab = QCheckBox("搜索前先切到「已获得其他学分」")
        self.check_tab.setContentsMargins(LABEL_WIDTH, 0, 0, 0)
        layout.addWidget(self.check_tab)

        self.btn_add = QPushButton("加入队列")
        self.btn_add.setObjectName("primary")
        self.btn_add.clicked.connect(self._add_to_queue)
        self.btn_resume = QPushButton("继续上次任务...")
        self.btn_resume.clicked.connect(self._add_resume)
        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        bottom.addSpacing(LABEL_WIDTH)
        bottom.addWidget(self.btn_add)
        bottom.addWidget(self.btn_resume)
        bottom.addStretch()
        layout.addLayout(bottom)
        return frame

    def _build_device_card(self) -> QFrame:
        frame, layout, _ = self._card("设备", "同一时间只能连一台手机")

        row = QHBoxLayout()
        row.setSpacing(8)
        label = QLabel("无线地址")
        label.setFixedWidth(LABEL_WIDTH)
        self.entry_device = QLineEdit()
        self.entry_device.setPlaceholderText("例如 192.168.1.10:5555，留空用数据线")
        row.addWidget(label)
        row.addWidget(self.entry_device, 1)
        layout.addLayout(row)

        self.check_init = QCheckBox("首次连接，初始化设备（安装 uiautomator2）")
        self.check_init.setContentsMargins(LABEL_WIDTH, 0, 0, 0)
        layout.addWidget(self.check_init)
        return frame

    def _build_queue_card(self) -> QFrame:
        frame, layout, head = self._card("等候区", "从上到下一块一块跑")
        self.btn_start = QPushButton("开始队列")
        self.btn_start.setObjectName("primary")
        self.btn_start.clicked.connect(self._start_queue)
        self.btn_stop = QPushButton("停止")
        self.btn_stop.setObjectName("danger")
        self.btn_stop.clicked.connect(self._stop)
        head.addWidget(self.btn_start)
        head.addWidget(self.btn_stop)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["活动", "分值", "状态"])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setHighlightSections(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setMinimumHeight(150)
        layout.addWidget(self.table, 1)

        self.queue_hint = QLabel("还没有任务：在左边填好活动名称和名单，点「加入队列」。")
        self.queue_hint.setObjectName("hint")
        layout.addWidget(self.queue_hint)

        self.btn_retry = QPushButton("重试这条")
        self.btn_retry.clicked.connect(lambda: self._decide("retry"))
        self.btn_skip = QPushButton("跳过这条")
        self.btn_skip.clicked.connect(lambda: self._decide("skip"))
        self.btn_up = QPushButton("上移")
        self.btn_up.clicked.connect(lambda: self._move_job(-1))
        self.btn_down = QPushButton("下移")
        self.btn_down.clicked.connect(lambda: self._move_job(1))
        self.btn_remove = QPushButton("删除选中")
        self.btn_remove.clicked.connect(self._remove_selected)
        self.btn_clear = QPushButton("清空队列")
        self.btn_clear.clicked.connect(self._clear_queue)
        self.btn_open = QPushButton("打开运行目录")
        self.btn_open.clicked.connect(self._open_output)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self.btn_up)
        row.addWidget(self.btn_down)
        row.addWidget(self.btn_remove)
        row.addWidget(self.btn_clear)
        row.addWidget(self.btn_open)
        row.addStretch()
        row.addWidget(self.btn_retry)
        row.addWidget(self.btn_skip)
        layout.addLayout(row)
        return frame

    def _build_progress_card(self) -> QFrame:
        frame, layout, head = self._card("进度")
        self.label_point = QLabel("当前分值：-")
        self.label_point.setObjectName("hint")
        head.addWidget(self.label_point)

        self.label_state = QLabel("准备就绪")
        layout.addWidget(self.label_state)

        self.bar_total = QProgressBar()
        self.bar_total.setFormat("%v / %m 人")
        self.bar_total.setMaximum(1)
        self.bar_point = QProgressBar()
        self.bar_point.setFormat("%v / %m 人")
        self.bar_point.setMaximum(1)

        total_label = QLabel("总进度")
        total_label.setFixedWidth(48)
        total_label.setObjectName("hint")
        point_label = QLabel("本分值")
        point_label.setFixedWidth(48)
        point_label.setObjectName("hint")

        total_row = QHBoxLayout()
        total_row.setSpacing(8)
        total_row.addWidget(total_label)
        total_row.addWidget(self.bar_total, 1)

        point_row = QHBoxLayout()
        point_row.setSpacing(8)
        point_row.addWidget(point_label)
        point_row.addWidget(self.bar_point, 1)

        layout.addLayout(total_row)
        layout.addLayout(point_row)
        return frame

    def _build_log_card(self) -> QFrame:
        frame, layout, head = self._card("")

        self.btn_log_toggle = QToolButton()
        self.btn_log_toggle.setObjectName("logToggle")
        self.btn_log_toggle.setText("运行日志")
        self.btn_log_toggle.setCheckable(True)
        self.btn_log_toggle.setChecked(True)
        self.btn_log_toggle.setArrowType(Qt.ArrowType.DownArrow)
        self.btn_log_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.btn_log_toggle.clicked.connect(self._toggle_log)

        self.btn_clear_log = QPushButton("清空")
        self.btn_clear_log.clicked.connect(self._clear_log)
        head.addWidget(self.btn_log_toggle)
        head.addWidget(self.btn_clear_log)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)
        self.log.setPlaceholderText("跑起来以后，这里会一行行显示进度")
        layout.addWidget(self.log, 1)
        return frame

    def _add_file_row(self, layout: QVBoxLayout, title: str, placeholder: str = "") -> QLineEdit:
        row = QHBoxLayout()
        row.setSpacing(8)
        label = QLabel(title)
        label.setFixedWidth(LABEL_WIDTH)
        entry = QLineEdit()
        entry.setPlaceholderText(placeholder)
        button = QPushButton("浏览")
        button.setFixedWidth(56)
        button.clicked.connect(lambda: self._pick_file(entry))
        row.addWidget(label)
        row.addWidget(entry, 1)
        row.addWidget(button)
        layout.addLayout(row)
        return entry

    def _add_score_row(self, path: str = "", points: float = 1.0) -> None:
        # 一份表对应一个分值，份数任意
        container = QWidget()
        column = QVBoxLayout(container)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(6)

        # 上半行写分值和删除，下半行整行放表格路径，这样路径不会被挤成几个字
        top = QHBoxLayout()
        top.setSpacing(8)
        label = QLabel("发分名单")
        label.setFixedWidth(LABEL_WIDTH)
        spin = QDoubleSpinBox()
        spin.setDecimals(1)
        spin.setRange(0.1, 100.0)
        spin.setSingleStep(0.5)
        spin.setValue(points)
        spin.setSuffix(" 分")
        spin.setFixedWidth(84)
        remove = QPushButton("删除")
        remove.setObjectName("danger")
        remove.clicked.connect(lambda: self._remove_score_row(container))
        top.addWidget(label)
        top.addWidget(spin)
        top.addWidget(remove)
        top.addStretch()

        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        entry = QLineEdit(path)
        entry.setPlaceholderText("要发分的名单")
        browse = QPushButton("浏览")
        browse.setFixedWidth(56)
        browse.clicked.connect(lambda: self._pick_file(entry))
        bottom.addSpacing(LABEL_WIDTH)
        bottom.addWidget(entry, 1)
        bottom.addWidget(browse)

        column.addLayout(top)
        column.addLayout(bottom)
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

    def _add_resume(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择上次没跑完的运行目录", str(self._base))
        if not path:
            return

        run_dir = Path(path)
        try:
            saved = load_config(run_dir / "config.json")
            files = {points: Path(item) for item, points in (saved.get("file_dir") or [])}
            if not files:
                raise ValueError("config.json 里没有名单路径")
            activity = saved.get("activity_name") or read_activity_name(files[sorted(files)[0]])
        except Exception as err:
            QMessageBox.warning(self, "这个目录不能续跑", f"{run_dir}\n\n{err}")
            return
        if not (run_dir / "students.db").exists():
            QMessageBox.warning(
                self,
                "这个目录不能续跑",
                f"{run_dir}\n\n目录里没有 students.db，没有进度可以接着跑；请用上面的表单重新建一个任务。",
            )
            return

        try:
            problems = compare_resume(run_dir, files, activity)
        except Exception as err:
            QMessageBox.warning(self, "这个目录不能续跑", f"{run_dir}\n\n{err}")
            return
        if problems:
            detail = "\n".join(problems)
            answer = QMessageBox.question(
                self,
                "名单和进度对不上",
                f"{run_dir}\n\n{detail}\n\n续跑时会按现在的名单来：新加的人补进去一起发，已经发过的不会重发。",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        else:
            self._append_log(f"已核对 {run_dir.name}：名单与进度一致")

        spec = JobSpec(
            title=f"{activity}（续跑）",
            files=files,
            activity=activity,
            device=self.entry_device.text().strip() or None,
            init_device=False,
            additional=None,
            yiban=None,
            click_other_tab=saved.get("click_other_tab", False),
            run_dir=run_dir,
        )
        self.jobs.append(spec)
        self._append_row(spec)
        self._set_state("idle")

    def _append_row(self, spec: JobSpec) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(spec.title))
        self.table.setItem(row, 1, QTableWidgetItem(self._points_text(spec)))
        status = QTableWidgetItem("等待中")
        status.setForeground(QColor(theme.MUTED))
        self.table.setItem(row, 2, status)
        self.table.setRowHeight(row, 30)
        self.queue_hint.setVisible(False)

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
        self.queue_hint.setVisible(not self.jobs)

    def _move_job(self, delta: int) -> None:
        row = self.table.currentRow()
        target = row + delta
        if row < 0 or target < 0 or target >= len(self.jobs):
            return

        self.jobs[row], self.jobs[target] = self.jobs[target], self.jobs[row]
        for column in range(3):
            first = self.table.item(row, column).text()
            second = self.table.item(target, column).text()
            self.table.item(row, column).setText(second)
            self.table.item(target, column).setText(first)
        self.table.selectRow(target)

    def _clear_queue(self) -> None:
        self.table.setRowCount(0)
        self.jobs.clear()
        self.queue_hint.setVisible(True)

    def _collect_spec(self) -> JobSpec:
        activity = self.entry_activity.text().strip()
        if not activity:
            raise ValueError("请先填活动名称（App 里那个完整名称）")

        files: dict[float, Path] = {}
        roster = self.entry_roster.text().strip()
        if roster:
            files[0.0] = Path(roster)

        for _, entry, spin in self.score_rows:
            text = entry.text().strip()
            if not text:
                continue
            points = round(spin.value(), 1)
            if points in files:
                raise ValueError(f"{points:.1f} 分出现了两份名单，请合并成一份，或用「额外名单」单独指定")
            files[points] = Path(text)

        if not files and not self.entry_extra.text().strip():
            raise ValueError("至少要选一份发分名单，或用「额外名单」直接写学号和分值")

        return JobSpec(
            title=activity,
            files=files,
            activity=activity,
            device=self.entry_device.text().strip() or None,
            init_device=self.check_init.isChecked(),
            additional=Path(self.entry_extra.text().strip()) if self.entry_extra.text().strip() else None,
            yiban=Path(self.entry_yiban.text().strip()) if self.entry_yiban.text().strip() else None,
            click_other_tab=self.check_tab.isChecked(),
        )

    def _start_queue(self) -> None:
        if not self.jobs:
            QMessageBox.warning(self, "还没有任务", "先在左边填好活动名称和名单，点「加入队列」。")
            return

        # 设备设置是全局的，开跑前统一套到还没跑过的任务上
        device = self.entry_device.text().strip() or None
        init_device = self.check_init.isChecked()
        for job in self.jobs:
            job.device = device
            if job.run_dir is None:
                job.init_device = init_device

        self._clear_log()
        self._reset_progress()
        self._set_state("running")

        self._worker = QueueWorker(self.jobs, self._base)
        self._worker.log_line.connect(self._append_log)
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

    # ---- 日志 ----

    def _append_log(self, text: str) -> None:
        color = theme.TEXT
        if any(word in text for word in ("❌", "失败", "错误", "异常", "ERROR")):
            color = theme.ERROR
        elif any(word in text for word in ("✅", "成功")):
            color = theme.SUCCESS
        elif any(word in text for word in ("⚠", "警告", "WARNING")):
            color = theme.WARNING

        cursor = self.log.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        cursor.insertText(text + "\n", fmt)
        self.log.setTextCursor(cursor)
        self.log.ensureCursorVisible()

    def _clear_log(self) -> None:
        self.log.clear()

    def _toggle_log(self, checked: bool) -> None:
        self.btn_log_toggle.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)
        self.log.setVisible(checked)

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
        self._append_log(f"———— 第 {index + 1} 条：{job.title} ————")

    def _on_job_status(self, index: int, text: str) -> None:
        item = self.table.item(index, 2)
        if item is not None:
            item.setText(text)
            item.setForeground(QColor(STATUS_COLORS.get(text, theme.TEXT)))

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
            self._append_log(f"❌ {self.jobs[index].title}：{message}")
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
        self.btn_resume.setEnabled(idle)
        self.btn_up.setEnabled(idle)
        self.btn_down.setEnabled(idle)
        self.btn_retry.setEnabled(paused)
        self.btn_skip.setEnabled(paused)
        self.check_init.setEnabled(idle)
        self.entry_device.setReadOnly(running or paused)

        self.chip.setText({"idle": "空闲", "running": "正在发分", "paused": "已暂停"}[state])
        self.chip.setProperty("state", state)
        self.chip.style().unpolish(self.chip)
        self.chip.style().polish(self.chip)

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
