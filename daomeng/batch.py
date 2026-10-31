"""发分主流程：连接设备、逐分逐人发分、导出结果，命令行与图形界面共用。"""
import logging

from .config import AutomationConfig, Student
from .device_controller import DeviceController
from .file_manager import FileManager


class BatchHooks:
    """运行过程中的回调，命令行与图形界面各自实现。

    回调都在主流程线程里同步调用，实现方负责把自己的控件更新排到界面线程。
    """

    def on_loop_start(self, controller: DeviceController) -> None:
        """发分循环开始前调用，此时设备已连上、数据库已就绪。"""

    def on_loop_end(self) -> None:
        """发分循环结束（正常结束或被停止）后调用。"""

    def on_total(self, total: int) -> None:
        """告知待处理总人数。"""

    def on_point(self, point: float, count: int) -> None:
        """开始处理某个分值，count 为该分值待发人数。"""

    def on_student(self, student: Student) -> None:
        """开始处理某个学生。"""

    def on_done(self, student: Student) -> None:
        """某个学生已处理完并写库。"""

    def on_point_end(self, point: float) -> None:
        """某个分值处理完。"""

    def should_stop(self) -> bool:
        return False

    def finished_normally(self) -> bool:
        """任务是否正常跑完；中途停下时保留数据库，下次还能接着跑。"""
        return True


def run_batch(
    controller: DeviceController,
    file_manager: FileManager,
    hooks: BatchHooks,
    logger: logging.Logger,
) -> int:
    """逐分逐人发分，返回本次实际处理的人数。"""
    points = file_manager.get_all_points_list()
    logger.info(f"共读取到 {len(points)} 个不同分值: {points}")

    total = file_manager.get_unprocessed_students_count()
    logger.info(f"待处理学生总数: {total}")
    logger.info("=" * 60)
    hooks.on_total(total)

    done = 0
    for point in points:
        logger.info("=" * 60)
        logger.info(f"开始处理分值: {point:.1f}")
        controller.navigation(point)

        students = file_manager.get_unprocessed_students_by_points(point)
        logger.info(f"该分值待处理学生数: {len(students)}")
        hooks.on_point(point, len(students))

        for student in students:
            if hooks.should_stop():
                logger.warning("收到停止指令，本次运行到此为止")
                return done
            hooks.on_student(student)
            student = controller.award_points(student)
            file_manager.update_students_status([student])
            done += 1
            hooks.on_done(student)

        hooks.on_point_end(point)
        logger.info(f"分值 {point:.1f} 处理完成")

    return done


def run_session(config: AutomationConfig, logger: logging.Logger, hooks: BatchHooks) -> int:
    """完整跑一轮：连接设备 → 建库 → 发分 → 导出 → 清理。"""
    controller = DeviceController(config, logger)
    try:
        logger.info("=" * 60)
        logger.info("开始进行设备连接")
        controller.connect()
        logger.info("设备连接完成，设备已就绪")
        logger.info("=" * 60)

        with FileManager(config, logger) as file_manager:
            if file_manager.check_database_initialized():
                logger.info("检测到已有学生数据库，跳过Excel读取步骤")
            else:
                logger.info("开始读取Excel文件并生成学生数据库")
                file_manager.save_students_to_db()
                logger.info("学生数据库生成完成")

            hooks.on_loop_start(controller)
            try:
                with controller.fast_input():
                    logger.info("开始运行自动化任务")
                    controller.device.unlock()
                    done = run_batch(controller, file_manager, hooks, logger)
            finally:
                hooks.on_loop_end()

            if hooks.finished_normally():
                logger.info("=" * 60)
                logger.info("自动化任务成功完成")
                logger.info("=" * 60)
            file_manager.export_db_to_excel()

        if hooks.finished_normally():
            file_manager.cleanup()
        else:
            logger.warning("任务中途停止，已保留 students.db 和 config.json，下次可继续")
        return done
    finally:
        controller.cleanup()
