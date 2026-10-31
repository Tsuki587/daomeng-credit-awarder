import logging
import os
import re
import subprocess
import sys
from time import sleep
from typing import Callable, Optional
from rich.prompt import Prompt
from rich.live import Live
from contextlib import contextmanager

import uiautomator2 as u2

from .config import AutomationConfig, Student
from .selectors import DMKJ_PACKAGE_NAME, SELECTORS


class NavigationError(RuntimeError):
    """导航到不了目标界面，而且重试也没用，比如活动根本不存在。"""


class DeviceController:
    """封装设备连接与导航相关操作。"""

    def __init__(
        self,
        config: AutomationConfig,
        logger: logging.Logger,
    ) -> None:
        self._config = config
        self._logger = logger
        self.device: u2.Device = None  # type: ignore # 延迟连接
        self.score: Optional[float] = None
        self._live: Optional[Live] = None  # 用于暂停 Live 显示以进行用户交互
        self._wait_hook: Optional[Callable[[str], None]] = None  # 需要人工确认时的回调
        self._ask_hook: Optional[Callable[[str, str], str]] = None  # 需要用户输入时的回调
        
        # 编译设备连接错误的正则模式，仅匹配真正的 ADB 连接错误
        self._device_error_patterns = re.compile(
            r"device .* not found|"  # ADB: 设备未找到
            r"device offline|"        # ADB: 设备离线
            r"unable to connect|"     # 无法连接
            r"connection refused|"    # 连接被拒绝
            r"no devices?/emulators? found|"  # 没有找到设备
            r"lost connection|"       # 连接丢失
            r"adb server .* killed|"  # ADB 服务器被终止
            r"cannot connect to daemon",  # 无法连接到守护进程
            re.IGNORECASE
        )

    def _is_device_connection_error(self, exc: Exception) -> bool:
        """
        判断异常是否为设备连接错误。
        使用严格的类型和模式检查，避免误判。
        """
        # 检查异常类型
        exc_type = type(exc).__name__
        if exc_type in ('RuntimeError', 'ConnectionError', 'OSError', 'TimeoutError'):
            # 这些类型可能是连接错误，进一步检查消息
            exc_msg = str(exc)
            # 使用编译好的正则模式匹配
            if self._device_error_patterns.search(exc_msg):
                return True
        
        # 检查是否是 adbutils 的特定异常（如果导入了）
        exc_module = type(exc).__module__
        if 'adbutils' in exc_module or 'adb' in exc_module.lower():
            # adbutils 的异常很可能是连接问题
            return True
            
        return False

    def set_user_hooks(
        self,
        wait: Optional[Callable[[str], None]] = None,
        ask: Optional[Callable[[str, str], str]] = None,
    ) -> None:
        """设置需要人工干预时的回调；图形界面用它弹窗，命令行不设置则走终端输入。"""
        self._wait_hook = wait
        self._ask_hook = ask

    def _wait_user(self, message: str) -> None:
        """暂停任务等人操作完按提示继续。"""
        self._pause_live_for_prompt()
        try:
            if self._wait_hook:
                self._wait_hook(message)
            else:
                Prompt.ask(message)
        finally:
            self._resume_live()

    def _ask_user(self, message: str, default: str) -> str:
        """向用户要一段输入。"""
        if self._ask_hook:
            return self._ask_hook(message, default)
        return Prompt.ask(message, default=default)

    def set_live(self, live: Optional[Live]) -> None:
        """设置 Live 对象，用于在需要用户交互时暂停显示。
        
        Args:
            live: rich.live.Live 对象，或 None 表示不使用 Live 显示
        """
        self._live = live
        self._logger.debug(f"Live 对象已{'设置' if live else '清除'}")

    def _pause_live_for_prompt(self) -> None:
        """暂停 Live 显示并清除残留内容，为用户交互做准备。"""
        if self._live:
            self._live.stop()
            # 清除 Live 显示区域的残留内容（通过刷新一个空内容）
            self._live.console.print()
            self._live.console.print()
            self._live.console.print()
            
    def _resume_live(self) -> None:
        """恢复 Live 显示。"""
        if self._live:
            self._live.start()

    @contextmanager
    def fast_input(self):
        if not self.device:
            self._logger.error("设备未连接，无法启用快速输入模式")
            raise RuntimeError("设备未连接")
        d = self.device
        orig = d.shell("settings get secure default_input_method").output.strip()
        self._logger.debug(f"当前输入法: {orig}")
        try:
            self._logger.info("启用 AdbKeyboard 快速输入模式")
            d.set_fastinput_ime(True)
            verify = d.shell("settings get secure default_input_method").output.strip()
            if verify != "com.github.uiautomator/.AdbKeyboard":
                self._logger.error(f"切换 AdbIME 失败，当前: {verify}")
                raise RuntimeError(f"切换 AdbIME 失败，当前: {verify}")
            self._logger.debug("快速输入模式已启用")
            yield
        finally:
            self._restore_input_method(orig)

    def _restore_input_method(self, orig: str) -> None:
        d = self.device
        if not d:
            self._logger.warning("设备未连接，跳过恢复原始输入法")
            return
        try:
            self._logger.info("恢复原始输入法")
            d.set_fastinput_ime(False)
            if orig:
                d.shell(f"ime set {orig}")
                self._logger.debug(f"已恢复输入法为: {orig}")
            else:
                self._logger.warning("未记录到原始输入法，仅关闭 AdbKeyboard")
        except Exception as exc:
            self._logger.warning(f"恢复原始输入法失败，继续完成后续流程: {exc}")

    def connect(self) -> u2.Device:
        self._logger.info("开始连接设备...")
        if self._config.pair:
            self._logger.info("检测到配对参数，尝试进行无线调试配对")
            self._pair_device()
        if self._config.device:
            subprocess.run(
                [os.environ["ADBUTILS_ADB_PATH"], "connect", self._config.device],
                check=True,
            )
        if self._config.init_device:
            self._logger.info("检测到初始化参数，尝试初始化 uiautomator2")
            self._init_uiautomator()
            
        connection_target = self._config.device
        if connection_target:
            self._logger.info(f"尝试连接到指定设备: {connection_target}")
        else:
            self._logger.info("尝试连接到默认设备")
        try:
            device = u2.connect(connection_target) if connection_target else u2.connect()
        except Exception as err:
            self._logger.error(f"设备连接失败: {err}")
            raise

        if not device or not device.device_info:
            self._logger.error("无法建立设备连接，设备信息为空")
            raise RuntimeError("无法建立设备连接")

        device.settings["wait_timeout"] = 15.0
        self.device = device
        self._logger.info(f"设备连接成功: {device.device_info.get('brand', 'Unknown')} {device.device_info.get('model', 'Unknown')} (SDK: {device.device_info.get('version', 'Unknown')})")
        return device

    def _pair_device(self) -> None:
        pair: list[str] = self._config.pair if self._config.pair else []
        if len(pair) != 2:
            self._logger.error("无线调试配对参数无效，需要提供 IP:端口 和 配对码")
            raise ValueError("无线调试配对参数无效，期望两个参数")

        host = pair[0].strip()
        pairing_code = pair[1].strip()
        if not host or not pairing_code:
            self._logger.error("无线调试配对参数包含空值")
            raise ValueError("无线调试配对参数包含空值")

        self._logger.info(f"开始配对设备: {host}")
        try:
            result = subprocess.run(
                [os.environ["ADBUTILS_ADB_PATH"], "pair", host, pairing_code],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                check=True,
            )
            self._logger.info(f"无线调试配对成功: {result.stdout.strip()}")
        except subprocess.CalledProcessError as err:
            self._logger.error(f"无线调试配对失败: {err.stderr}")
            raise

    def _init_uiautomator(self) -> None:
        self._logger.info("开始初始化 uiautomator2")
        command = [sys.executable, "-m", "uiautomator2", "init"]
        if self._config.device:
            command.extend(["--serial", self._config.device])
            self._logger.debug(f"指定设备: {self._config.device}")
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                check=True,
            )
            self._logger.info(f"uiautomator2 初始化成功: {result.stdout.strip()}")
        except subprocess.CalledProcessError as err:
            self._logger.error(f"uiautomator2 初始化失败: {err.stderr}")
            raise

    def _get_current_nolog(self) -> str:
        if not self.device:
            raise RuntimeError("设备未连接")
        d = self.device
        try:
            current_package = d.app_current().get("package")
            if current_package != DMKJ_PACKAGE_NAME:
                self._logger.debug(f"当前应用包名不匹配: {current_package}")
                return "N0"
            if d(**SELECTORS["跳过"]).exists:
                self._logger.debug("检测到跳过按钮，点击跳过")
                d(**SELECTORS["跳过"]).click()
                d(**SELECTORS["加载"]).wait_gone()
            if d(**SELECTORS["登录失效提示"]).exists:
                self._logger.debug("检测到登录失效提示，点击确定")
                d(**SELECTORS["登录失效确定按钮"]).click()
            if d(**SELECTORS["关闭"]).exists:
                self._logger.debug("检测到关闭按钮，点击关闭")
                d(**SELECTORS["关闭"]).click()
            if d(**SELECTORS["登录页面标题"]).exists:
                return "登录页面"
            if d(**SELECTORS["我的活动"]).exists:
                return "我的"
            if d(**SELECTORS["首页"]).exists:
                return "首页"
            if d(**SELECTORS["活动管理tab"]).exists:
                return "活动管理"
            if d(**SELECTORS["管理列表"]).exists:
                return "管理列表"
            if d(**SELECTORS["颁发"]).exists:
                return "学分管理"
            if d(**SELECTORS["未获得任何学分"]).exists:
                return f"{self.score}分发放界面"
            return "N1"
        except Exception as exc:
            # 使用精确的错误检测方法
            if self._is_device_connection_error(exc):
                self._logger.error(f"设备连接失败: {exc}")
                try:
                    self._logger.info("尝试自动重新连接设备...")
                    self.connect()
                    self._logger.info("设备自动重连成功")
                except Exception as reconnect_err:
                    self._logger.error(f"设备自动重连失败: {reconnect_err}")
                    if not self._reconnect_with_prompt():
                        raise RuntimeError("用户选择退出") from exc
            else:
                self._logger.error(f"获取当前界面失败: {exc}")
            return "N0"
        
    def _get_current(self) -> str:
        current = self._get_current_nolog()
        self._logger.debug("当前界面: %s", current)
        return current

    def _reconnect_with_prompt(self) -> bool:
        """
        自动重连失败后提示用户输入新的连接方式。
        返回: True 表示重连成功，False 表示用户选择退出
        """
        from rich.console import Console
        console = Console()
        
        # 暂停 Live 显示并清除残留内容
        self._pause_live_for_prompt()
        
        try:
            while True:
                console.print("\n[yellow]设备连接失败，请选择重连方式:[/yellow]")
                user_input = self._ask_user(
                    "设备连接失败，输入新的 IP:端口（如 192.168.1.100:5555），留空使用有线连接，输入 'e' 退出",
                    "",
                ).strip()
                
                if user_input.lower() == 'e':
                    self._logger.warning("用户选择退出")
                    console.print("[red]用户选择退出程序[/red]")
                    return False
                
                try:
                    if user_input == "":
                        # 有线连接
                        self._logger.info("尝试使用有线连接...")
                        self._config.device = None
                        self.connect()
                        console.print("[green]✓ 有线连接成功[/green]")
                        return True
                    else:
                        # 无线连接
                        self._logger.info(f"尝试连接到无线设备: {user_input}")
                        self._config.device = user_input
                        self.connect()
                        console.print(f"[green]✓ 无线连接成功: {user_input}[/green]")
                        return True
                except Exception as err:
                    self._logger.error(f"连接失败: {err}")
                    console.print(f"[red]✗ 连接失败: {err}[/red]")
                    continue
        finally:
            # 恢复 Live 显示
            self._resume_live()
    
    def _score(self) -> Optional[float]:
        if not self.device:
            raise RuntimeError("设备未连接")
        if not self.device(**SELECTORS["筛选"]).exists:
            self._logger.debug("未在发分界面，分值缓存失效")
            self.score = None
            return None
        return self.score
    
    def navigation(self, score: float, target: str = "发分界面") -> bool:
        if not self.device:
            self._logger.error("设备未连接，无法执行导航")
            raise RuntimeError("设备未连接")
        self._logger.info(f"开始导航到目标界面: {target}，分值: {score}")
        d = self.device
        back_count = 0
        not_running = 0
        while self._get_current() != target:
            try:
                sleep(0.2)
                current = self._get_current()
                if current == "N0":
                    # 手机锁屏、断线时会一直停在这里重启应用，没人看着就永远卡住
                    not_running += 1
                    if not_running > 30:
                        raise RuntimeError("应用反复启动不成功，检查手机是否亮屏解锁、数据线是否还连着")
                    self._logger.info("应用未运行或包名不匹配，重启应用")
                    d.app_start(DMKJ_PACKAGE_NAME, stop=True)
                else:
                    not_running = 0
                if back_count > 25:
                    self._logger.error(f"已返回 {back_count} 次仍未到达目标界面，请求手动干预")
                    self._wait_user("已返回多次仍未到达目标界面，请手动操作到目标页后继续")
                if back_count % 5 == 0 and back_count > 4:
                    self._logger.warning(f"已返回 {back_count} 次，重启应用尝试重置")
                    d.app_start(DMKJ_PACKAGE_NAME, stop=True)
                if target == "发分界面":
                    if current == "登录页面":
                        if self._config.accounts:
                            self._logger.info("检测到需要登录，使用配置的账号自动登录")
                            sleep(0.5)
                            d(**SELECTORS["登录账号"]).set_text(list(self._config.accounts.keys())[0]) # TODO: 多账号支持
                            d(**SELECTORS["登录密码"]).set_text(list(self._config.accounts.values())[0])
                            d.hide_keyboard()
                            sleep(0.5)
                            d(**SELECTORS["同意协议"]).click()
                            d(**SELECTORS["登录按钮"]).click()
                            d(**SELECTORS["加载"]).wait_gone()
                            d(**SELECTORS["加载"]).wait_gone()
                            self._logger.info("自动登录完成")
                        else:
                            self._logger.warning("检测到需要登录，但未配置账号，等待手动登录")
                            self._wait_user("检测到需要登录，请在手机上登录后继续")
                    if current == "首页":
                        self._logger.debug("当前在首页，点击'我的'")
                        d(**SELECTORS["我的"]).click()
                    if current == "我的":
                        self._logger.debug("当前在'我的'页面，点击'我的活动'")
                        d(**SELECTORS["我的活动"]).click()
                        d(**SELECTORS["加载"]).wait_gone()
                    if current == "活动管理":
                        self._logger.debug(f"当前在活动管理页，搜索活动: {self._config.activity_name}")
                        d(**SELECTORS["活动管理tab"]).click()
                        d(**SELECTORS["加载"]).wait_gone()
                        d(**SELECTORS["活动搜索框"]).set_text(self._config.activity_name)
                        d.press("enter")
                        d.hide_keyboard()
                        d(**SELECTORS["加载"]).wait_gone()
                        if d(**SELECTORS["无结果"]).exists:
                            self._logger.error(f"未找到活动: {self._config.activity_name}")
                            raise NavigationError(f"未找到活动: {self._config.activity_name}")
                        if d(**SELECTORS["活动筛选"]).exists and not d(**SELECTORS["活动筛选：已结束"]).exists:
                            d(**SELECTORS["活动筛选"]).click()
                            sleep(0.3)
                            d(**SELECTORS["活动筛选：已结束"]).click()
                        d(**SELECTORS["加载"]).wait_gone()
                        d(**SELECTORS["活动管理"]).click()
                        self._logger.debug("进入活动管理页面")
                    if current == "管理列表":
                        self._logger.debug("当前在管理列表，点击'学分管理'")
                        d(**SELECTORS["学分管理"]).click()
                    if current == "学分管理":
                        self._logger.debug(f"当前在学分管理页，选择分值: {score}")
                        d(**SELECTORS["积分"], text=f"积分 {score:.1f}").click()
                        d(**SELECTORS["颁发"]).click()
                        d(**SELECTORS["加载"]).wait_gone()
                        if self._get_current() == f"{self.score}分发放界面":
                            self.score = score
                            self._logger.info(f"成功导航到 {score} 分发放界面")
                            return True
                    if current == f"{self.score}分发放界面":
                        if score == self.score:
                            self._logger.debug(f"已在目标分值 ({score}) 界面")
                            return True
                        self._logger.debug(f"当前分值 ({self.score}) 与目标分值 ({score}) 不匹配，返回 back")
                        d.press("back")
                        back_count += 1
                    if current == "N1":
                        self._logger.debug("未识别的界面，尝试返回 back")
                        d.press("back")
                        back_count += 1
            except NavigationError:
                raise
            except Exception as exc:
                # 使用精确的错误检测方法
                if self._is_device_connection_error(exc):
                    self._logger.error(f"导航时设备连接失败: {exc}")
                    try:
                        self._logger.info("尝试自动重新连接设备...")
                        self.connect()
                        d = self.device  # 更新设备引用
                        self._logger.info("设备自动重连成功，继续导航")
                    except Exception as reconnect_err:
                        self._logger.error(f"设备自动重连失败: {reconnect_err}")
                        if not self._reconnect_with_prompt():
                            raise RuntimeError("用户选择退出") from exc
                        d = self.device  # 更新设备引用
                else:
                    self._logger.error(f"导航到 {target} 时发生错误: {exc}，正在重试")
                back_count += 1
        self._logger.info(f"成功导航到目标界面: {target}")
        return True
        
    def award_points(self, student: Student) -> Student:
        if not self.device:
            self._logger.error("设备未连接，无法颁发学分")
            raise RuntimeError("设备未连接")
        self._logger.info(f"开始为学生 {student.name} ({student.student_id}) 颁发 {student.points} 分")
        d = self.device
        c = 0
        while True:
            self.score = self._score()
            if not self.score or self.score != student.points:
                self._logger.debug(f"当前界面分值 ({self.score}) 与目标分值 ({student.points}) 不匹配，需要导航")
                if not self.navigation(student.points, "发分界面"):
                    self._logger.error(f"导航到发分界面失败，无法为 {student.student_id} 颁发学分")
                    raise RuntimeError("导航到发分界面失败")
            try:
                if self._config.click_other_tab:
                    self._logger.debug("已启用点击“已获得其他学分”tab，再执行搜索")
                    if d(**SELECTORS["已获得其他学分"]).exists:
                        d(**SELECTORS["已获得其他学分"]).click()
                        d(**SELECTORS["加载"]).wait_gone()
                    else:
                        self._logger.warning("未找到“已获得其他学分”tab，继续原流程")
                row = self._search_student(student)
                if row is None:
                    return student
                self._logger.debug(f"找到学生: {student.name} ({student.student_id})，开始颁发")
                row.click()
                btn = d(**SELECTORS["颁发1人"])
                btn.wait()
                self._hide_keyboard()
                btn.click()
                d(**SELECTORS["确定"]).click()
                d(**SELECTORS["发分加载"]).wait_gone()
                d(**SELECTORS["加载"]).wait_gone()
                toast = d.toast.get_message(wait_timeout=7, default="未获取到Toast") or "未获取到Toast"
                self._logger.debug(f"颁发后获取到 Toast 消息: {toast}")
                if "成功1人" in toast:
                    self._logger.info(f"✅ 确认颁发成功: {student.name} ({student.student_id}), {student.points} 分")
                    student.status = f"成功颁发{student.points:.1f}分"
                    return student
                else:
                    self._logger.warning(f"颁发状态未知: {student.name} ({student.student_id})，Toast: {toast}")
                    student.status = f"未知(提示:{toast})"
                    return student
            except NavigationError:
                raise
            except Exception as exc:
                # 使用精确的错误检测方法
                if self._is_device_connection_error(exc):
                    self._logger.error(f"颁发学分时设备连接失败: {exc}")
                    try:
                        self._logger.info("尝试自动重新连接设备...")
                        self.connect()
                        d = self.device  # 更新设备引用
                        self._logger.info("设备自动重连成功，将重试颁发")
                    except Exception as reconnect_err:
                        self._logger.error(f"设备自动重连失败: {reconnect_err}")
                        if not self._reconnect_with_prompt():
                            student.status = "设备连接失败，用户退出"
                            raise RuntimeError("用户选择退出") from exc
                        d = self.device  # 更新设备引用
                elif c > 2:
                    self._logger.error(f"为 {student.student_id} 颁发学分失败，已重试 {c} 次，异常: {exc}")
                    student.status = f"颁发失败（{exc}）"
                    return student
                else:
                    self._logger.info(f"为 {student.student_id} 颁发学分时发生异常: {exc}，自动重试")
                c += 1

    def _hide_keyboard(self) -> None:
        # 键盘展开时会盖住底部的「颁发1人」，点下去落到键盘的 Search 键上，弹窗永远不出现
        d = self.device
        d.hide_keyboard()
        for _ in range(10):
            if "mInputShown=true" not in d.shell("dumpsys input_method").output:
                return
            sleep(0.1)

    def _search_student(self, student: Student):
        d = self.device
        row = d(**SELECTORS["人员信息"], text=student.name)
        # 按学号搜索后列表只剩目标一人，第二行消失才说明结果是本次搜索的
        rest = d(**{**SELECTORS["人员信息"], "index": "1"})

        for attempt in range(2):
            self._logger.debug(f"搜索学生: {student.student_id}，第 {attempt + 1} 次")
            d(**SELECTORS["人员搜索框"]).set_text(student.student_id)
            d.press("enter")
            self._hide_keyboard()

            if not rest.wait(exists=False):
                continue
            # 搜不到时界面会直接显示“这里暂无数据”，不必再空等整行的 15 秒超时
            if d(**SELECTORS["无结果"]).wait(exists=True, timeout=2):
                continue
            if row.wait():
                d(**SELECTORS["加载"]).wait_gone()
                return row

        if row.exists:
            self._logger.warning(f"两次搜索后列表未过滤到单人: {student.name} ({student.student_id})")
            student.status = "待核对（搜索结果未确认）"
        elif d(**SELECTORS["无结果"]).exists:
            self._logger.warning(f"两次搜索仍未找到学生: {student.name} ({student.student_id})")
            student.status = "待核对（两次搜索无结果）"
        elif d(**SELECTORS["人员信息"]).exists:
            name = d(**SELECTORS["人员信息"]).get_text()
            self._logger.warning(
                f"两次搜索姓名不符: {student.student_id}，应为 {student.name}，实际为 {name}"
            )
            student.status = f"待核对（姓名不符，应为{student.name}，实际为{name}）"
        else:
            self._logger.warning(f"两次搜索后结果未确认: {student.name} ({student.student_id})")
            student.status = "待核对（搜索结果未确认）"

        return None
            
    def cleanup(self) -> None:
        if not self.device:
            self._logger.warning("设备未连接，跳过清理步骤")
            return
        self.device.app_stop(DMKJ_PACKAGE_NAME)
        self.device.press("home")
        self.device.screen_off()
        self._logger.info("已关闭应用并锁屏，清理完成")
