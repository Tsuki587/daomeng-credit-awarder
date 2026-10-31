import re

from pandas import read_excel as _pandas_read_excel


def read_excel(path, **kwargs):
    """读取 Excel 表格，自动识别 xlsx 与老式 xls。"""
    # xlsx 是 zip 包，老式 xls 是 OLE2 复合文档，靠文件头区分
    # 学校导出的表格常被直接改成 .xlsx 后缀，openpyxl 打开会报 BadZipFile
    with open(path, "rb") as f:
        is_xls = f.read(8) == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    return _pandas_read_excel(path, engine="xlrd" if is_xls else "openpyxl", **kwargs)


_ALIASES = {
    "名字": "姓名",
    "学生姓名": "姓名",
    "学生学号": "学号",
    "活动": "活动名称",
}


def clean_columns(frame) -> None:
    """把「1、姓名」这类带序号的表头改成「姓名」，顺便统一几种别名。"""
    names = [re.sub(r"^\s*\d+\s*[、.．,，:：)）]?\s*", "", str(name)).strip() for name in frame.columns]
    frame.columns = [_ALIASES.get(name, name) for name in names]
