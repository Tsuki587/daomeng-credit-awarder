import logging
from pathlib import Path
from typing import Optional
from rich.logging import RichHandler


def get_logger(
    console_log_level: str = "WARNING",
    log_file: Optional[Path] = None,
    file_log_level: str = "INFO",
    extra_handlers: Optional[list[logging.Handler]] = None,
) -> logging.Logger:
    """配置根日志记录器并返回 logger。"""
    console_level = getattr(logging, console_log_level.upper(), logging.WARNING)
    file_level = getattr(logging, file_log_level.upper(), logging.INFO)
    console_format = "%(message)s"
    handlers = _build_handlers(console_level, file_level, log_file, extra_handlers)
    logging.basicConfig(level=logging.NOTSET, format=console_format, handlers=handlers, force=True)
    logger = logging.getLogger()
    logger.debug(f"日志初始化完成，控制台级别={console_log_level}，文件级别={file_log_level}，文件={log_file}")
    return logger


def _build_handlers(
    console_level: int,
    file_level: int,
    log_file: Optional[Path],
    extra_handlers: Optional[list[logging.Handler]] = None,
) -> list[logging.Handler]:
    """构建日志处理器列表。"""
    console_handler = RichHandler(level=console_level, markup=True, rich_tracebacks=True)

    handlers: list[logging.Handler] = [console_handler]

    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(file_level)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] (%(filename)s:%(lineno)d): %(message)s")
        )
        handlers.append(file_handler)

    if extra_handlers:
        handlers.extend(extra_handlers)

    return handlers

