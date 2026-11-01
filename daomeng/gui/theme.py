"""界面的配色和样式表。"""
from pathlib import Path

from PySide6.QtGui import QIcon

PRIMARY = "#6C5CE7"
PRIMARY_HOVER = "#5B4BD6"
SUCCESS = "#18A058"
WARNING = "#E08A00"
ERROR = "#D03050"
MUTED = "#8B90A0"
TEXT = "#2D3142"

STYLESHEET = f"""
QWidget {{
    font-size: 14px;
    color: {TEXT};
}}
QMainWindow, QWidget#root {{
    background: #F4F5F9;
}}
QFrame#card {{
    background: #FFFFFF;
    border: 1px solid #E4E6EF;
    border-radius: 10px;
}}
QLabel#cardTitle {{
    font-size: 15px;
    font-weight: 600;
}}
QLabel#h1 {{
    font-size: 18px;
    font-weight: 600;
}}
QLabel#hint {{
    color: {MUTED};
    font-size: 12px;
}}
QLabel#chip {{
    border-radius: 11px;
    padding: 4px 12px;
    font-size: 12px;
    background: #EEF0F6;
    color: #6B7280;
}}
QLabel#chip[state="running"] {{
    background: {PRIMARY};
    color: white;
}}
QLabel#chip[state="paused"] {{
    background: #FFF3E0;
    color: {WARNING};
}}
QLineEdit, QDoubleSpinBox {{
    border: 1px solid #DDE0EA;
    border-radius: 6px;
    padding: 5px 8px;
    background: #FFFFFF;
    selection-background-color: {PRIMARY};
}}
QLineEdit:focus, QDoubleSpinBox:focus {{
    border-color: {PRIMARY};
}}
QLineEdit:disabled, QDoubleSpinBox:disabled {{
    background: #F7F8FB;
    color: #B7BBC8;
}}
QPushButton {{
    border: 1px solid #DDE0EA;
    border-radius: 6px;
    padding: 6px 14px;
    background: #FFFFFF;
}}
QPushButton:hover {{
    background: #F5F6FF;
    border-color: #C9CDF0;
}}
QPushButton:pressed {{
    background: #ECEAFF;
}}
QPushButton:disabled {{
    color: #B7BBC8;
    background: #F7F8FB;
    border-color: #EDEFF5;
}}
QPushButton#primary {{
    background: {PRIMARY};
    border-color: {PRIMARY};
    color: white;
    font-weight: 600;
}}
QPushButton#primary:hover {{
    background: {PRIMARY_HOVER};
    border-color: {PRIMARY_HOVER};
}}
QPushButton#primary:disabled {{
    background: #C9C4F4;
    border-color: #C9C4F4;
    color: #F2F1FB;
}}
QPushButton#danger {{
    color: {ERROR};
}}
QPushButton#danger:disabled {{
    color: #B7BBC8;
}}
QCheckBox {{
    spacing: 6px;
}}
QTableWidget {{
    border: none;
    gridline-color: transparent;
    background: #FFFFFF;
    selection-background-color: #EEEBFF;
    selection-color: {TEXT};
}}
QHeaderView::section {{
    background: #FAFBFD;
    border: none;
    border-bottom: 1px solid #E4E6EF;
    padding: 6px;
    color: {MUTED};
    font-size: 12px;
}}
QProgressBar {{
    background: #EEF0F6;
    border: none;
    border-radius: 5px;
    min-height: 12px;
    max-height: 12px;
    text-align: center;
    font-size: 10px;
    color: {MUTED};
}}
QProgressBar::chunk {{
    background: {PRIMARY};
    border-radius: 5px;
}}
QPlainTextEdit {{
    background: #FBFBFD;
    border: 1px solid #EDEFF5;
    border-radius: 8px;
    font-family: "Noto Sans Mono CJK SC", "DejaVu Sans Mono", monospace;
    font-size: 12px;
}}
QToolButton#logToggle {{
    border: none;
    font-size: 15px;
    font-weight: 600;
    padding: 0;
}}
QToolButton#logToggle:hover {{
    color: {PRIMARY};
}}
"""


def icon() -> QIcon:
    path = Path(__file__).resolve().parent.parent.parent / "assets" / "daomeng.png"
    return QIcon(str(path)) if path.exists() else QIcon()
