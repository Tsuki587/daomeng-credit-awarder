"""图形界面入口。"""
import os
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from .window import MainWindow


def main() -> int:
    # 打包成无控制台的 exe 后 stdout 是 None，rich 一写日志就炸
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")

    app = QApplication(sys.argv)
    app.setApplicationName("到梦空间批量发分")
    # 和 .desktop 文件对上，任务栏才认这个图标
    app.setDesktopFileName("daomeng")
    window = MainWindow(Path(sys.argv[0]).resolve().parent)
    window.show()
    return app.exec()
