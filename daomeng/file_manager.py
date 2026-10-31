import warnings
import logging
import re
import sqlite3
from typing import Optional, List, Dict, Any
from pathlib import Path

import pandas as pd
from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt

from .config import AutomationConfig, Student, progress_
from .excel_io import clean_columns, read_excel

warnings.filterwarnings("ignore", message="Workbook contains no default style")


class FileManager:
    """文件管理与数据加载相关操作。"""

    def __init__(self, config: AutomationConfig, logger: logging.Logger) -> None:
        self._config = config
        self._logger = logger
        self._db_path = self._config.output_dir / "students.db"
        self._yiban_mapping_dict: Optional[dict[str, str]] = None  # {易班ID: 学号}
        self._yiban_name_dict: Optional[dict[str, str]] = None  # {易班ID: 姓名}
        self._conn: Optional[sqlite3.Connection] = None  # 共享的数据库连接
        self._ask_hook = None  # 图形界面接管输入
        self._choose_hook = None
        
        # 加载易班映射文件
        if self._config.yiban_mapping:
            self._load_yiban_mapping()

    def set_user_hooks(self, ask=None, choose=None) -> None:
        """把需要人工输入的环节交给图形界面，命令行下留空走 Prompt.ask。"""
        self._ask_hook = ask
        self._choose_hook = choose

    def _ask_user(self, message: str, default: str = "") -> str:
        """问一行文字：索引、学号等。"""
        if self._ask_hook:
            return self._ask_hook(message, default)
        return Prompt.ask(message, default=default)

    def _choose_user(self, message: str, options: List[tuple[str, str]], default: str) -> str:
        """让用户在几个固定选项里挑一个，返回选项编号。"""
        if self._choose_hook:
            return self._choose_hook(message, options, default)
        console = Console()
        console.print(f"\n[bold cyan]{message}[/bold cyan]")
        for key, text in options:
            console.print(f"{key}. {text}")
        return Prompt.ask("请输入选项", choices=[key for key, _ in options], default=default)

    def _records_text(self, records: List[Dict], columns: tuple[str, ...], limit: int = 30) -> str:
        """把记录拼成带序号的几行文字，供对话框展示，同时写进日志。"""
        lines = []
        for index, record in enumerate(records, 1):
            values = [self._format_display_value(record.get(column)) for column in columns]
            lines.append(f"{index}. " + "  ".join(values))

        for line in lines[:200]:
            self._logger.info(line)
        if len(lines) > limit:
            return "\n".join(lines[:limit] + [f"……共 {len(lines)} 条，其余见 automation.log"])
        return "\n".join(lines)

    def __enter__(self):
        """进入上下文管理器，建立数据库连接。"""
        # 确保输出目录存在
        self._config.output_dir.mkdir(parents=True, exist_ok=True)
        
        # 连接数据库
        self._conn = sqlite3.connect(self._db_path)
        
        # 启用 WAL 模式
        self._conn.execute("PRAGMA journal_mode=WAL;")
        
        # 启用外键约束
        self._conn.execute("PRAGMA foreign_keys=ON;")
        
        self._logger.debug(f"已建立数据库连接: {self._db_path}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """退出上下文管理器，关闭数据库连接。"""
        if self._conn:
            try:
                if exc_type is None:
                    # 没有异常，提交所有未提交的更改
                    self._conn.commit()
                    self._logger.debug("最终提交所有数据库更改")
                else:
                    # 有异常，回滚未提交的更改
                    self._conn.rollback()
                    self._logger.debug("由于异常，回滚未提交的数据库更改")
            except Exception as e:
                self._logger.error(f"提交/回滚数据库事务时出错: {e}")
            finally:
                try:
                    self._conn.close()
                    self._logger.debug("数据库连接已关闭")
                except Exception as e:
                    self._logger.error(f"关闭数据库连接时出错: {e}")
                finally:
                    self._conn = None
        return False  # 不抑制异常

    def check_database_initialized(self) -> bool:
        """检查数据库是否已初始化（表是否存在）。
        
        Returns:
            bool: 如果 students 表存在且有数据则返回 True，否则返回 False
        """
        if not self._conn:
            self._logger.warning("数据库连接未建立，无法检查初始化状态")
            return False
        
        try:
            cursor = self._conn.cursor()
            # 检查 students 表是否存在
            cursor.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='students'
            """)
            table_exists = cursor.fetchone() is not None
            
            if not table_exists:
                self._logger.debug("students 表不存在，需要初始化")
                return False
            
            # 检查表中是否有数据
            cursor.execute("SELECT COUNT(*) FROM students")
            count = cursor.fetchone()[0]
            
            if count > 0:
                self._logger.debug(f"数据库已初始化，包含 {count} 条学生记录")
                return True
            else:
                self._logger.debug("students 表存在但为空，需要初始化")
                return False
                
        except Exception as e:
            self._logger.error(f"检查数据库初始化状态时出错: {e}")
            return False

    def _format_display_value(self, value: Any, default: str = "N/A") -> str:
        """格式化表格展示值，确保 Rich 能正确渲染。"""
        if value is None:
            return default

        # 处理 pandas 的缺失值
        if pd.isna(value):
            return default

        if isinstance(value, str):
            stripped = value.strip()
            if stripped == "" or stripped.lower() == "nan":
                return default
            return stripped

        if isinstance(value, float):
            # 避免显示诸如 1.0 的浮点字符串
            if value.is_integer():
                return str(int(value))
            return str(value)

        return str(value)

    def _load_yiban_mapping(self) -> None:
        """加载易班ID映射文件。"""
        if not self._config.yiban_mapping or not self._config.yiban_mapping.exists():
            self._logger.warning("易班映射文件不存在或未指定")
            return
        
        self._logger.info(f"开始加载易班ID映射文件: {self._config.yiban_mapping}")
        try:
            import pandas as pd
            
            # 尝试多种编码读取CSV文件
            df = None
            encodings = ['utf-8', 'gbk', 'gb2312', 'gb18030', 'utf-8-sig']
            last_error = None
            
            for encoding in encodings:
                try:
                    self._logger.debug(f"尝试使用编码 {encoding} 读取易班映射文件")
                    df = pd.read_csv(self._config.yiban_mapping, dtype=str, encoding=encoding)
                    self._logger.debug(f"成功使用编码 {encoding} 读取文件")
                    break
                except (UnicodeDecodeError, UnicodeError) as e:
                    last_error = e
                    self._logger.debug(f"编码 {encoding} 读取失败: {e}")
                    continue
            
            if df is None:
                self._logger.error(f"无法解码易班映射文件，尝试了以下编码: {encodings}")
                raise ValueError(f"无法解码易班映射文件，最后错误: {last_error}")
            
            # 验证必要列
            required_cols = {'姓名', '学号', '易班ID'}
            if not required_cols.issubset(df.columns):
                missing = required_cols - set(df.columns)
                self._logger.error(f"易班映射文件缺少必要列: {missing}，当前列: {df.columns.tolist()}")
                raise ValueError(f"易班映射文件缺少必要列: {missing}")
            
            # 构建映射字典
            self._yiban_mapping_dict = {}
            self._yiban_name_dict = {}
            
            for _, row in df.iterrows():
                yiban_id = str(row['易班ID']).strip() if pd.notna(row['易班ID']) else None
                student_id = str(row['学号']).strip() if pd.notna(row['学号']) else None
                name = str(row['姓名']).strip() if pd.notna(row['姓名']) else None
                
                if yiban_id and student_id and name:
                    self._yiban_mapping_dict[yiban_id] = student_id
                    self._yiban_name_dict[yiban_id] = name
            
            self._logger.info(f"成功加载易班ID映射，共 {len(self._yiban_mapping_dict)} 条记录")
        except Exception as e:
            self._logger.error(f"加载易班映射文件失败: {e}")
            raise

    def _read_student_list_single(self, file_dir: Path) -> pd.DataFrame:
        """读取单个学生名单文件，返回 DataFrame。
        
        如果启用了易班ID映射且文件中没有学号列，则尝试通过易班ID和姓名映射学号。
        """
        self._logger.debug(f"开始读取学生名单文件: {file_dir}")
        try:
            # 表头可能带序号（「1、姓名」），统一清洗后再按列名取
            df = read_excel(file_dir, dtype=str)
            clean_columns(df)
            
            # 检查姓名列是否存在（必需）
            if "姓名" not in df.columns:
                self._logger.error(f"文件 {file_dir} 缺少必要列: 姓名")
                raise ValueError(f"文件 {file_dir} 缺少必要列: 姓名")
            
            # 如果没有学号列且启用了易班映射
            if "学号" not in df.columns and self._yiban_mapping_dict:
                if "易班ID" not in df.columns:
                    self._logger.error(f"文件 {file_dir} 既没有学号列也没有易班ID列")
                    raise ValueError(f"文件 {file_dir} 既没有学号列也没有易班ID列")
                
                self._logger.info(f"文件 {file_dir} 缺少学号列，尝试通过易班ID映射")
                
                # 通过易班ID和姓名映射学号
                student_ids = []
                for _, row in df.iterrows():
                    yiban_id = str(row.get('易班ID', '')).strip() if pd.notna(row.get('易班ID')) else None
                    name = str(row.get('姓名', '')).strip() if pd.notna(row.get('姓名')) else None
                    
                    student_id = "1000000000"  # 默认值
                    
                    if yiban_id and self._yiban_mapping_dict and yiban_id in self._yiban_mapping_dict:
                        mapped_name = self._yiban_name_dict.get(yiban_id) if self._yiban_name_dict else None
                        mapped_id = self._yiban_mapping_dict.get(yiban_id)
                        
                        # 验证姓名是否匹配
                        if name == mapped_name:
                            student_id = mapped_id
                            self._logger.debug(f"通过易班ID {yiban_id} 映射到学号 {student_id} (姓名: {name})")
                        else:
                            self._logger.warning(f"易班ID {yiban_id} 对应姓名不匹配 (文件: {name}, 映射: {mapped_name})，使用默认学号")
                    else:
                        self._logger.warning(f"易班ID {yiban_id} 未找到映射 (姓名: {name})，使用默认学号")
                    
                    student_ids.append(student_id)
                
                # 添加学号列
                df['学号'] = student_ids
                self._logger.info(f"通过易班ID映射完成，成功映射 {sum(1 for sid in student_ids if sid != '1000000000')} 条记录")
            
            # 如果既没有学号列也没有启用易班映射，则报错
            elif "学号" not in df.columns:
                self._logger.error(f"文件 {file_dir} 缺少学号列且未启用易班映射")
                raise ValueError(f"文件 {file_dir} 缺少学号列且未启用易班映射")

            df["学号"] = df["学号"].str.removeprefix("`")
            
            # 确保返回的DataFrame包含所需列
            required = ["学号", "姓名", "院系", "专业", "班级"]
            for col in required:
                if col not in df.columns:
                    df[col] = None  # 添加缺失列，填充为None
            
            # 只保留所需列
            df = df[required]
            
            self._logger.info(f"成功加载学生名单文件: {file_dir.name}，读取人数: {len(df)}")
            return df
        except Exception as e:
            self._logger.error(f"加载学生名单文件失败: {file_dir}，错误: {e}")
            raise

    def _read_student_list(self) -> dict[float, pd.DataFrame]:
        """读取所有学生名单文件，返回 DataFrame 字典。"""
        self._logger.info(f"开始加载所有学生名单文件，共 {len(self._config.file_dir)} 个文件")
        dataframes = {}
        with progress_() as progress:
            task = progress.add_task("加载学生名单...", total=len(self._config.file_dir))
            for pts, path in self._config.file_dir.items():
                self._logger.debug(f"加载分值 {pts} 的名单文件: {path}")
                df = self._read_student_list_single(path)
                dataframes[pts] = df
                progress.update(task, advance=1)
        self._logger.info(f"所有学生名单文件加载完成，共 {len(dataframes)} 个分值")
        return dataframes

    def _read_additional_list(self) -> Optional[pd.DataFrame]:
        """读取附加名单文件，返回 DataFrame 或 None。"""
        if not self._config.additional_list or not self._config.additional_list.exists():
            self._logger.info("未提供附加名单文件，跳过加载")
            return None
        self._logger.debug(f"开始读取附加名单文件: {self._config.additional_list}")
        try:
            df = read_excel(self._config.additional_list, dtype=str, usecols=lambda col: col in {"学号", "姓名", "分值"})
            if not {"学号", "姓名", "分值"}.issubset(df.columns):
                self._logger.error(f"附加名单文件 {self._config.additional_list} 缺少必要列")
                raise ValueError(f"附加名单文件 {self._config.additional_list} 缺少必要列，必须包含: 学号, 姓名, 分值")
            self._logger.info(f"成功加载附加名单文件: {self._config.additional_list.name}，读取人数: {len(df)}，读取列: {df.columns.tolist()}")
            return df
        except Exception as e:
            self._logger.error(f"加载附加名单文件失败: {self._config.additional_list}，错误: {e}")
            raise

    def _extract_student_id(self, student_id_str: str) -> Optional[str]:
        """从字符串中提取11位学号。
        
        Args:
            student_id_str: 包含学号的字符串
            
        Returns:
            提取的11位学号，如果未找到或输入超过11位数字则返回None
        """
        if pd.isna(student_id_str):
            self._logger.debug("学号字符串为空或 NaN")
            return None
        
        student_id_str = str(student_id_str).strip()
        
        # 如果整个字符串就是纯数字
        if student_id_str.isdigit():
            # 只接受恰好11位的学号
            if len(student_id_str) == 11:
                self._logger.debug(f"提取到有效学号: {student_id_str}")
                return student_id_str
            else:
                # 超过或少于11位都视为无效
                self._logger.debug(f"学号位数不正确: {student_id_str} (长度: {len(student_id_str)})")
                return None
        
        # 如果包含其他字符，尝试提取11位数字
        # 但要确保提取的数字段不是更长数字串的一部分
        match = re.search(r'(?<!\d)\d{11}(?!\d)', student_id_str)
        if match:
            extracted_id = match.group(0)
            self._logger.debug(f"从字符串 '{student_id_str}' 中提取到学号: {extracted_id}")
            return extracted_id
        else:
            self._logger.debug(f"无法从字符串中提取11位学号: {student_id_str}")
            return None

    def _find_students_by_name(self, name: str, enrollment_df: pd.DataFrame) -> pd.DataFrame:
        """在录取名单中根据姓名查找学生。
        
        Args:
            name: 要查找的学生姓名
            enrollment_df: 录取名单DataFrame
            
        Returns:
            匹配的学生记录DataFrame
        """
        if pd.isna(name) or not isinstance(name, str):
            return pd.DataFrame()
        return enrollment_df[enrollment_df['姓名'] == name.strip()]

    def _display_invalid_id_table(self, invalid_records: List[Dict]) -> None:
        """展示无效学号及匹配信息表格。
        
        Args:
            invalid_records: 包含错误学号、姓名、匹配学号数的记录列表
        """
        console = Console()
        table = Table(title="[bold red]无效学号列表[/bold red]", show_header=True, header_style="bold magenta")
        table.add_column("索引", justify="right", style="cyan", width=6)
        table.add_column("错误学号", style="yellow")
        table.add_column("姓名", style="green")
        table.add_column("匹配学号数", justify="right", style="blue")
        
        for idx, record in enumerate(invalid_records, 1):
            table.add_row(
                str(idx),
                str(record.get('invalid_id', 'N/A')),
                str(record.get('name', 'N/A')),
                str(record.get('match_count', 0))
            )
        
        console.print(table)

    def _display_student_comparison_table(self, enrollment_records: List[Dict], score_record: Dict) -> None:
        """展示录取名单与发分名单的对比表格。
        
        Args:
            enrollment_records: 录取名单中的匹配记录列表
            score_record: 发分名单中的学生记录
        """
        console = Console()
        
        # 发分名单信息
        console.print("\n[bold cyan]发分名单信息:[/bold cyan]")
        score_table = Table(show_header=True, header_style="bold yellow")
        score_table.add_column("学号", style="cyan")
        score_table.add_column("姓名", style="green")
        score_table.add_column("院系", style="magenta")
        score_table.add_column("专业", style="blue")
        score_table.add_column("班级", style="yellow")
        
        score_table.add_row(
            self._format_display_value(score_record.get('学号')),
            self._format_display_value(score_record.get('姓名')),
            self._format_display_value(score_record.get('院系')),
            self._format_display_value(score_record.get('专业')),
            self._format_display_value(score_record.get('班级'))
        )
        console.print(score_table)
        
        # 录取名单信息
        console.print("\n[bold cyan]录取名单匹配记录:[/bold cyan]")
        enrollment_table = Table(show_header=True, header_style="bold green")
        enrollment_table.add_column("索引", justify="right", style="cyan", width=6)
        enrollment_table.add_column("学号", style="cyan")
        enrollment_table.add_column("姓名", style="green")
        enrollment_table.add_column("院系", style="magenta")
        enrollment_table.add_column("专业", style="blue")
        enrollment_table.add_column("班级", style="yellow")
        
        for idx, record in enumerate(enrollment_records, 1):
            enrollment_table.add_row(
                str(idx),
                str(record.get('学号', 'N/A')),
                str(record.get('姓名', 'N/A')),
                str(record.get('院系', 'N/A')),
                str(record.get('专业', 'N/A')),
                str(record.get('班级', 'N/A'))
            )
        console.print(enrollment_table)

    def _display_name_mismatch_table(self, mismatch_records: List[Dict]) -> None:
        """展示姓名不匹配的记录表格。
        
        Args:
            mismatch_records: 姓名不匹配的记录列表，包含学号、发分表姓名、录取表姓名
        """
        console = Console()
        table = Table(title="[bold yellow]姓名不匹配列表[/bold yellow]", show_header=True, header_style="bold magenta")
        table.add_column("索引", justify="right", style="cyan", width=6)
        table.add_column("学号", style="cyan")
        table.add_column("发分表姓名", style="yellow")
        table.add_column("录取表姓名", style="green")
        
        for idx, record in enumerate(mismatch_records, 1):
            table.add_row(
                str(idx),
                str(record.get('学号', 'N/A')),
                str(record.get('发分表姓名', 'N/A')),
                str(record.get('录取表姓名', 'N/A'))
            )
        
        console.print(table)

    def _handle_invalid_ids(self, invalid_records: List[Dict], enrollment_df: pd.DataFrame) -> Dict[Any, str]:
        """处理无效学号，返回确认后的学号映射。
        
        Args:
            invalid_records: 无效学号记录列表
            enrollment_df: 录取名单DataFrame
            
        Returns:
            记录唯一键到正确学号的映射字典
        """
        if not invalid_records:
            self._logger.debug("无无效学号需要处理")
            return {}
        
        self._logger.info(f"发现 {len(invalid_records)} 条无效学号记录，等待用户确认")
        console = Console()
        self._display_invalid_id_table(invalid_records)
        
        message = f"发现 {len(invalid_records)} 条无效学号记录，怎么处理？\n\n" \
                  + self._records_text(invalid_records, ("invalid_id", "name", "match_count"))
        choice = self._choose_user(
            message,
            [("1", "全部拒绝"),
             ("2", "仅智能选择"),
             ("3", "智能选择，并手动输入无法确认的学号")],
            "3")
        self._logger.info(f"用户选择了处理方式: {choice}")
        
        id_mapping: Dict[Any, str] = {}

        def _get_record_key(record: Dict[str, Any]) -> Any:
            """生成用于无效学号映射的唯一键。"""
            if 'record_key' in record and record['record_key'] is not None:
                return record['record_key']
            # 兼容旧数据结构，使用(错误学号, 姓名)作为回退键
            return (record.get('invalid_id'), record.get('name'))
        
        if choice == "1":
            self._logger.info("用户选择拒绝所有无效学号记录")
            return id_mapping
        
        def _normalize_field(value: Any) -> str:
            if value is None:
                return ""
            if isinstance(value, str):
                return value.strip()
            if isinstance(value, float):
                if pd.isna(value):
                    return ""
                if value.is_integer():
                    return str(int(value))
                return str(value).strip()
            if pd.isna(value):
                return ""
            return str(value).strip()

        for record in invalid_records:
            name = record.get('name')
            match_count = record.get('match_count', 0)
            invalid_id = record.get('invalid_id')
            score_info = record.get('score_info', {})

            matched_students = None
            if name:
                matched_students = self._find_students_by_name(name, enrollment_df)
                if matched_students is not None:
                    match_count = len(matched_students)

            # 只有在选择2或3时才进行自动映射，选择1（全部拒绝）时跳过所有自动映射
            if choice in {"2", "3"} and match_count == 1 and matched_students is not None and not matched_students.empty:
                # 只匹配到一个学号，自动使用
                correct_id = matched_students['学号'].iloc[0]
                id_mapping[_get_record_key(record)] = correct_id
                self._logger.info(f"自动映射: {invalid_id} -> {correct_id} (姓名: {name})")
                continue

            auto_mapped = False
            if (
                (match_count > 1 or match_count == 0)
                and choice in {"2", "3"}
                and matched_students is not None
                and not matched_students.empty
                and '班级' in matched_students.columns
            ):
                score_class = _normalize_field(score_info.get('班级'))
                if score_class:
                    class_matches = matched_students[
                        matched_students['班级'].apply(_normalize_field) == score_class
                    ]
                    if len(class_matches) == 1:
                        correct_id = class_matches['学号'].iloc[0]
                        id_mapping[_get_record_key(record)] = correct_id
                        self._logger.info(
                            f"通过班级匹配自动映射: {invalid_id} -> {correct_id} (姓名: {name}, 班级: {score_class})"
                        )
                        auto_mapped = True
                    else:
                        self._logger.debug(
                            f"班级匹配未找到唯一结果: {invalid_id} (姓名: {name}, 班级: {score_class}, 匹配数: {len(class_matches)})"
                        )
                else:
                    self._logger.debug(
                        f"班级信息缺失，无法进行班级自动映射: {invalid_id} (姓名: {name})"
                    )

            if auto_mapped:
                continue

            if match_count > 1 and choice == "3":
                # 匹配到多个学号，需要手动选择
                if matched_students is None or matched_students.empty:
                    continue

                console.print(f"\n[bold yellow]处理学生: {name} (错误学号: {invalid_id})[/bold yellow]")
                self._display_student_comparison_table(
                    matched_students.to_dict('records'),
                    score_info
                )

                
                while True:
                    index_choice = self._ask_user(
                        f"请选择正确的学号（输入序号）或直接输入 11 位学号，0 跳过\n\n"
                        f"学生: {name}  错误学号: {invalid_id}\n"
                        + self._records_text(matched_students.to_dict("records"), ("学号", "姓名", "班级")),
                        "0")
                    try:
                        idx = int(index_choice)
                        if 1 <= idx <= len(matched_students):
                            correct_id = matched_students.iloc[idx - 1]['学号']
                            id_mapping[_get_record_key(record)] = correct_id
                            self._logger.info(f"手动映射: {invalid_id} -> {correct_id} (姓名: {name})")
                            break
                        elif idx == 0:
                            self._logger.info(f"跳过无效学号: {invalid_id} (姓名: {name})")
                            break
                        else:
                            correct_id = index_choice.strip()
                            if re.fullmatch(r'\d{11}', correct_id):
                                id_mapping[invalid_id] = correct_id
                                self._logger.info(f"手动映射: {invalid_id} -> {correct_id} (姓名: {name})")
                                break
                            else:
                                self._logger.warning("输入的学号无效，请输入11位数字")
                                continue
                    except ValueError:
                        self._logger.warning("无效输入，请重试")
        
        return id_mapping

    def _handle_name_mismatches(self, mismatch_records: List[Dict]) -> List[str]:
        """处理姓名不匹配的记录，返回用户确认保留的学号列表。
        
        Args:
            mismatch_records: 姓名不匹配的记录列表
            
        Returns:
            用户确认保留的学号列表
        """
        if not mismatch_records:
            self._logger.debug("无姓名不匹配记录需要处理")
            return []
        
        self._logger.info(f"发现 {len(mismatch_records)} 条姓名不匹配记录，等待用户确认")
        console = Console()
        self._display_name_mismatch_table(mismatch_records)
        
        message = f"发现 {len(mismatch_records)} 条姓名不匹配记录，怎么处理？\n\n" \
                  + self._records_text(mismatch_records, ("学号", "发分表姓名", "录取表姓名"))
        choice = self._choose_user(
            message,
            [("1", "全部拒绝"),
             ("2", "全部同意"),
             ("3", "仅同意特定学生"),
             ("4", "仅拒绝特定学生")],
            "2")
        
        all_ids = [record['学号'] for record in mismatch_records]
        
        if choice == "1":
            self._logger.info("用户选择拒绝所有姓名不匹配记录")
            return []
        elif choice == "2":
            self._logger.info("用户选择同意所有姓名不匹配记录")
            return all_ids
        elif choice == "3":
            while True:
                indices_str = self._ask_user("要保留哪几条？输入序号，逗号分隔（如 1,3）", "")
                try:
                    indices = [int(idx.strip()) for idx in indices_str.split(",") if idx.strip()]
                    approved_ids = [all_ids[idx - 1] for idx in indices if 1 <= idx <= len(all_ids)]
                    self._logger.info(f"用户选择保留 {len(approved_ids)} 条姓名不匹配记录")
                    return approved_ids
                except (ValueError, IndexError) as e:
                    self._logger.warning(f"无效输入: {e}，请重试")
        elif choice == "4":
            while True:
                indices_str = self._ask_user("要拒绝哪几条？输入序号，逗号分隔（如 2,4）", "")
                try:
                    indices = [int(idx.strip()) for idx in indices_str.split(",") if idx.strip()]
                    rejected_indices = set(indices)
                    approved_ids = [all_ids[i] for i in range(len(all_ids)) if (i + 1) not in rejected_indices]
                    self._logger.info(f"用户选择拒绝 {len(rejected_indices)} 条记录，保留 {len(approved_ids)} 条")
                    return approved_ids
                except (ValueError, IndexError) as e:
                    self._logger.warning(f"无效输入: {e}，请重试")
        
        return []

    def _process_student_list(
        self,
        dataframes: Optional[Dict[float, pd.DataFrame]] = None,
        additional_df: Optional[pd.DataFrame] = None
    ) -> pd.DataFrame:
        """处理学生名单，提取学号、验证姓名、合并数据。
        
        Args:
            dataframes: 分值到DataFrame的映射（分值非0的发分名单）
            additional_df: 额外发放名单DataFrame
            
        Returns:
            处理后的合并DataFrame，包含学号、姓名、分值、状态列
        """
        console = Console()
        console.print("[bold green]开始处理学生名单...[/bold green]")
        self._logger.info("开始处理学生名单，进行学号提取和姓名验证")
        
        dataframes = dataframes or self._read_student_list()
        additional_df = additional_df or self._read_additional_list()
        
        # 获取录取名单（分值为0）
        enrollment_df = dataframes.get(0.0)
        if enrollment_df is None or enrollment_df.empty:
            self._logger.error("未找到录取名单（分值为0），无法进行验证")
            raise ValueError("缺少录取名单")
        self._logger.info(f"录取名单共有 {len(enrollment_df)} 条记录")
        
        # 准备收集所有处理后的记录
        all_processed_records = []
        
        # 第一步：处理所有分值非0的名单
        score_dataframes = {k: v for k, v in dataframes.items() if k > 0}
        
        for points, df in score_dataframes.items():
            console.print(f"\n[bold cyan]处理 {points} 分名单...[/bold cyan]")
            self._logger.info(f"开始处理 {points} 分名单，共 {len(df)} 条记录")
            
            # 提取学号
            invalid_records = []
            valid_records = []
            rejected_invalid_records = []  # 保存被拒绝的无效学号记录
            
            with progress_() as progress:
                task = progress.add_task("提取学号...", total=len(df))
                for idx, row in df.iterrows():
                    raw_id = row.get('学号', '')
                    extracted_id = self._extract_student_id(str(raw_id))
                    name = row.get('姓名', '')
                    
                    if extracted_id and len(extracted_id) == 11:
                        # 学号有效
                        valid_records.append({
                            'original_id': raw_id,
                            'student_id': extracted_id,
                            'name': name,
                            'points': points,
                            'row_data': row.to_dict()
                        })
                    else:
                        # 学号无效，尝试通过姓名匹配
                        matched = self._find_students_by_name(name, enrollment_df)
                        invalid_records.append({
                            'invalid_id': raw_id,
                            'name': name,
                            'match_count': len(matched),
                            'points': points,
                            'score_info': row.to_dict(),
                            'record_key': idx
                        })
                    progress.update(task, advance=1)
            
            self._logger.info(f"{points} 分名单学号提取完成: 有效 {len(valid_records)} 条，无效 {len(invalid_records)} 条")
            
            # 处理无效学号
            id_mapping = self._handle_invalid_ids(invalid_records, enrollment_df)
            self._logger.info(f"无效学号处理完成: 共映射 {len(id_mapping)} 条记录")
            
            # 应用学号映射
            for record in invalid_records:
                invalid_id = record['invalid_id']
                record_key = record.get('record_key')
                if record_key is None:
                    record_key = (record.get('invalid_id'), record.get('name'))

                if record_key in id_mapping:
                    valid_records.append({
                        'original_id': invalid_id,
                        'student_id': id_mapping[record_key],
                        'name': record['name'],
                        'points': record['points'],
                        'row_data': record['score_info']
                    })
                else:
                    # 被拒绝的无效学号记录，保留数据
                    rejected_invalid_records.append({
                        'student_id': str(invalid_id),
                        'name': record['name'],
                        'points': record['points'],
                        'status': '学号错误（非11位有效学号）'
                    })
            
            # 第二步：验证姓名匹配
            mismatch_records = []
            confirmed_records = []
            rejected_mismatch_records = []  # 保存被拒绝的姓名不匹配记录
            
            with progress_() as progress:
                task = progress.add_task("验证姓名匹配...", total=len(valid_records))
                for record in valid_records:
                    student_id = record['student_id']
                    score_name = record['name']
                    
                    # 在录取名单中查找该学号
                    enrollment_match = enrollment_df[enrollment_df['学号'] == student_id]
                    
                    if not enrollment_match.empty:
                        enrollment_name = enrollment_match['姓名'].iloc[0]
                        
                        if str(score_name).strip() != str(enrollment_name).strip():
                            # 姓名不匹配
                            mismatch_records.append({
                                '学号': student_id,
                                '发分表姓名': score_name,
                                '录取表姓名': enrollment_name,
                                'points': record['points'],
                                'record': record
                            })
                        else:
                            # 姓名匹配
                            confirmed_records.append(record)
                    else:
                        # 录取名单中找不到该学号，直接标记为"未报名"，不进入姓名匹配流程
                        rejected_mismatch_records.append({
                            'student_id': student_id,
                            'name': score_name,
                            'points': record['points'],
                            'status': '未报名（或学号错误）'
                        })
                    progress.update(task, advance=1)
            
            self._logger.info(f"{points} 分名单姓名验证完成: 匹配 {len(confirmed_records)} 条，不匹配 {len(mismatch_records)} 条，未报名 {len(rejected_mismatch_records)} 条")
            
            # 处理姓名不匹配
            if mismatch_records:
                approved_ids = self._handle_name_mismatches(mismatch_records)
                self._logger.info(f"姓名不匹配处理完成: 用户同意 {len(approved_ids)} 条，拒绝 {len(mismatch_records) - len(approved_ids)} 条")
                
                for mismatch in mismatch_records:
                    if mismatch['学号'] in approved_ids:
                        # 用户同意该记录，使用录取表的正确姓名
                        corrected_record = mismatch['record'].copy()
                        corrected_record['name'] = mismatch['录取表姓名']
                        confirmed_records.append(corrected_record)
                    else:
                        # 被拒绝的姓名不匹配记录，保留数据
                        rejected_mismatch_records.append({
                            'student_id': mismatch['学号'],
                            'name': mismatch['发分表姓名'],
                            'points': mismatch['points'],
                            'status': f'姓名错误（或学号填写错误），录取表姓名{mismatch["录取表姓名"]}'
                        })
            
            # 添加到总记录
            for record in confirmed_records:
                all_processed_records.append({
                    '学号': record['student_id'],
                    '姓名': record['name'],
                    '分值': record['points'],
                    '状态': '未处理'
                })
            
            # 添加被拒绝的无效学号记录
            for record in rejected_invalid_records:
                all_processed_records.append({
                    '学号': record['student_id'],
                    '姓名': record['name'],
                    '分值': record['points'],
                    '状态': record['status']
                })
            
            # 添加被拒绝的姓名不匹配记录
            for record in rejected_mismatch_records:
                all_processed_records.append({
                    '学号': record['student_id'],
                    '姓名': record['name'],
                    '分值': record['points'],
                    '状态': record['status']
                })
        
            self._logger.info(f"{points} 分名单处理完成: 确认 {len(confirmed_records)} 条，学号错误 {len(rejected_invalid_records)} 条，姓名错误/未报名 {len(rejected_mismatch_records)} 条")
        
        # 第三步：添加额外发放名单
        if additional_df is not None and not additional_df.empty:
            console.print("\n[bold cyan]添加额外发放名单...[/bold cyan]")
            self._logger.info(f"开始处理额外发放名单，共 {len(additional_df)} 条记录")
            
            # 计算所有分值的最大值（用于处理 "m" 标记）
            max_points = max(score_dataframes.keys()) if score_dataframes else 0.0
            
            # 构建学号到记录索引的映射，用于覆盖重复学号
            student_id_to_index = {record['学号']: idx for idx, record in enumerate(all_processed_records)}
            
            additional_added = 0
            additional_updated = 0
            additional_not_enrolled = 0
            additional_invalid = 0
            
            for _, row in additional_df.iterrows():
                student_id = self._extract_student_id(str(row.get('学号', '')))
                name = row.get('姓名', '')
                points_str = str(row.get('分值', '')).strip().lower()
                if points_str == '' or points_str == 'nan':
                    points = max_points
                
                # 处理分值：如果是 "m" 或 "max"，则使用最大分值
                if points_str in ['m', 'max', 'M', 'MAX']:
                    points = max_points
                    self._logger.info(f"额外名单中学号 {student_id} 分值标记为 '{points_str}'，使用最大分值: {max_points}")
                else:
                    try:
                        points = float(points_str)
                    except (ValueError, TypeError):
                        points = max_points
                        self._logger.warning(f"额外名单中分值无法解析: {points_str}，默认为 {max_points}")

                if not student_id or len(student_id) != 11:
                    # 学号无效
                    self._logger.warning(f"额外名单中学号无效: {row.get('学号', '')} (姓名: {name})")
                    additional_invalid += 1
                    all_processed_records.append({
                        '学号': str(row.get('学号', '')),
                        '姓名': name,
                        '分值': points,
                        '状态': '学号错误'
                    })
                else:
                    # 检查学号是否在录取名单中
                    enrollment_match = enrollment_df[enrollment_df['学号'] == student_id]
                    
                    if enrollment_match.empty:
                        # 不在录取名单中，标记为"未报名"
                        self._logger.warning(f"额外名单中学号未报名: {student_id} (姓名: {name})")
                        additional_not_enrolled += 1
                        
                        # 如果学号已存在，覆盖；否则添加新记录
                        if student_id in student_id_to_index:
                            idx = student_id_to_index[student_id]
                            old_points = all_processed_records[idx]['分值']
                            all_processed_records[idx] = {
                                '学号': student_id,
                                '姓名': name,
                                '分值': max(points, old_points),  # 使用最大分值
                                '状态': '未报名'
                            }
                            self._logger.info(f"覆盖学号 {student_id}，分值从 {old_points} 更新为 {max(points, old_points)}")
                            additional_updated += 1
                        else:
                            all_processed_records.append({
                                '学号': student_id,
                                '姓名': name,
                                '分值': points,
                                '状态': '未报名'
                            })
                            student_id_to_index[student_id] = len(all_processed_records) - 1
                            additional_added += 1
                    else:
                        # 在录取名单中，正常处理
                        if student_id in student_id_to_index:
                            # 学号已存在，覆盖并使用最大分值
                            idx = student_id_to_index[student_id]
                            old_points = all_processed_records[idx]['分值']
                            all_processed_records[idx] = {
                                '学号': student_id,
                                '姓名': name,
                                '分值': max(points, old_points),  # 使用最大分值
                                '状态': '未处理'
                            }
                            self._logger.info(f"覆盖学号 {student_id}，分值从 {old_points} 更新为 {max(points, old_points)}")
                            additional_updated += 1
                        else:
                            # 新学号，添加记录
                            all_processed_records.append({
                                '学号': student_id,
                                '姓名': name,
                                '分值': points,
                                '状态': '未处理'
                            })
                            student_id_to_index[student_id] = len(all_processed_records) - 1
                            additional_added += 1
                            self._logger.info(f"添加额外名单学生: {student_id} (姓名: {name}, 分值: {points})")
            
            # 输出统计信息
            console.print("[bold green]额外名单处理完成:[/bold green]")
            console.print(f"  - 新增记录: {additional_added} 人")
            if additional_updated > 0:
                console.print(f"  - 覆盖更新: {additional_updated} 人")
            if additional_not_enrolled > 0:
                console.print(f"  - 未报名: {additional_not_enrolled} 人")
            if additional_invalid > 0:
                console.print(f"  - 学号无效: {additional_invalid} 人")
        
        # 创建最终的DataFrame
        result_df = pd.DataFrame(all_processed_records)
        
        console.print(f"\n[bold green]处理完成！共处理 {len(result_df)} 条记录[/bold green]")
        self._logger.info(f"学生名单处理完成，最终记录数: {len(result_df)}")
        
        return result_df

    # @contextmanager
    # def _get_db_connection(self):
    #     """获取数据库连接的上下文管理器。
        
    #     自动启用 WAL 模式，确保连接正确关闭。
        
    #     Yields:
    #         sqlite3.Connection: 数据库连接对象
    #     """
    #     conn = None
    #     try:
    #         # 确保输出目录存在
    #         self._config.output_dir.mkdir(parents=True, exist_ok=True)
            
    #         # 连接数据库
    #         conn = sqlite3.connect(self._db_path)
            
    #         # 启用 WAL 模式
    #         conn.execute("PRAGMA journal_mode=WAL;")
            
    #         # 启用外键约束
    #         conn.execute("PRAGMA foreign_keys=ON;")
            
    #         self._logger.debug(f"已连接到数据库: {self._db_path}")
    #         yield conn
            
    #     except Exception as e:
    #         self._logger.error(f"数据库连接错误: {e}")
    #         raise
    #     finally:
    #         if conn:
    #             conn.close()
    #             self._logger.debug("数据库连接已关闭")

    def save_students_to_db(self) -> None:
        """将处理后的学生数据存储到数据库。"""
        self._logger.info("开始处理学生名单并保存到数据库")
        df = self._process_student_list()
        # 验证必要列
        required_cols = {'学号', '姓名', '分值', '状态'}
        if not required_cols.issubset(df.columns):
            missing = required_cols - set(df.columns)
            self._logger.error(f"DataFrame 缺少必要列: {missing}")
            raise ValueError(f"DataFrame 缺少必要列: {missing}")

        self._logger.info(f"开始保存 {len(df)} 条学生记录到数据库: {self._db_path}")

        if not self._conn:
            raise RuntimeError("数据库连接未建立，请在 with 语句中使用 FileManager")
        
        cursor = self._conn.cursor()

        # 创建学生表（如果不存在）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS students (
                student_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                points REAL NOT NULL,
                status TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT (datetime('now', 'localtime')),
                updated_at TIMESTAMP DEFAULT (datetime('now', 'localtime'))
            )
        """)

        # 创建索引以优化查询
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_points_status 
            ON students(points, status)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_status 
            ON students(status)
        """)

        # 提交表结构创建
        self._conn.commit()
        self._logger.debug("数据库表结构创建完成")

        # 开始数据插入事务
        cursor.execute("BEGIN TRANSACTION;")

        try:
            # 使用 INSERT OR REPLACE 来处理重复学号
            insert_count = 0
            update_count = 0

            with progress_() as progress:
                task = progress.add_task("保存到数据库...", total=len(df))
                for _, row in df.iterrows():
                    student_id = str(row['学号']).strip()
                    name = str(row['姓名']).strip()
                    points = float(row['分值'])
                    status = str(row['状态']).strip()

                    cursor.execute(
                        """
                        UPDATE students
                        SET name = ?,
                            points = ?,
                            status = ?,
                            updated_at = datetime('now', 'localtime')
                        WHERE student_id = ?
                        """,
                        (name, points, status, student_id),
                    )

                    if cursor.rowcount:
                        update_count += 1
                    else:
                        cursor.execute(
                            """
                            INSERT INTO students (student_id, name, points, status)
                            VALUES (?, ?, ?, ?)
                            """,
                            (student_id, name, points, status),
                        )
                        insert_count += 1

                    progress.update(task, advance=1)

            # 提交事务
            self._conn.commit()
            self._logger.info(
                f"数据库保存完成: 新增 {insert_count} 条，更新 {update_count} 条记录"
            )

        except Exception as e:
            # 回滚事务
            self._conn.rollback()
            self._logger.error(f"保存到数据库失败，已回滚: {e}")
            raise

    def merge_student_lists(self) -> Dict[str, int]:
        """续跑前把名单里新加的人并进数据库；已发过的记录一律不动。

        Returns:
            统计：新增人数、从「未报名/学号错误」恢复成「未处理」的人数
        """
        dataframes = self._read_student_list()
        enrollment = dataframes.get(0.0)
        if enrollment is None or enrollment.empty:
            raise ValueError("缺少录取名单")
        roster = {
            str(student_id).strip(): str(name).strip()
            for student_id, name in zip(enrollment["学号"], enrollment["姓名"])
        }

        cursor = self._conn.cursor()
        rows = cursor.execute("SELECT student_id, points, status, name FROM students")
        stored = {
            str(student_id): (float(points), str(status), str(name))
            for student_id, points, status, name in rows
        }

        added: List[str] = []
        revived: List[str] = []
        skipped: List[str] = []

        def _ensure(student_id: str, name: str, points: float) -> None:
            eligible = student_id in roster
            if student_id in stored:
                saved_points, status, saved_name = stored[student_id]
                if eligible and status.startswith(("未报名", "学号错误", "姓名错误")):
                    cursor.execute(
                        "UPDATE students SET name = ?, status = '未处理', "
                        "updated_at = datetime('now', 'localtime') WHERE student_id = ?",
                        (roster[student_id], student_id),
                    )
                    stored[student_id] = (saved_points, "未处理", roster[student_id])
                    revived.append(f"{student_id} {roster[student_id]}")
                elif status == "未处理":
                    # 名单改过的姓名也要跟上，否则按姓名找不到人
                    if not saved_points == points:
                        cursor.execute(
                            "UPDATE students SET points = ?, updated_at = datetime('now', 'localtime') "
                            "WHERE student_id = ?",
                            (points, student_id),
                        )
                        saved_points = points
                    if eligible and roster[student_id] != saved_name:
                        cursor.execute(
                            "UPDATE students SET name = ?, updated_at = datetime('now', 'localtime') "
                            "WHERE student_id = ?",
                            (roster[student_id], student_id),
                        )
                        saved_name = roster[student_id]
                    stored[student_id] = (saved_points, status, saved_name)
                return

            if not eligible:
                skipped.append(f"{student_id} {name}")
                return
            cursor.execute(
                "INSERT INTO students (student_id, name, points, status) VALUES (?, ?, ?, '未处理')",
                (student_id, roster[student_id], points),
            )
            stored[student_id] = (points, "未处理", roster[student_id])
            added.append(f"{student_id} {roster[student_id]}")

        for points, frame in dataframes.items():
            if points <= 0:
                continue
            for _, row in frame.iterrows():
                student_id = self._extract_student_id(str(row.get("学号", "")))
                if not student_id or len(student_id) != 11:
                    continue
                _ensure(student_id, str(row.get("姓名", "")).strip(), float(points))

        self._conn.commit()
        if added:
            self._logger.info(f"名单里新加的学生已补进数据库 {len(added)} 人：{self._sample_names(added)}")
        if revived:
            self._logger.info(f"录取名单里补上了 {len(revived)} 人，已恢复为未处理：{self._sample_names(revived)}")
        if skipped:
            self._logger.warning(
                f"有 {len(skipped)} 人不在录取名单里，不参与发分：{self._sample_names(skipped)}"
            )
        return {"added": len(added), "revived": len(revived), "skipped": len(skipped)}

    def _sample_names(self, items: List[str], limit: int = 10) -> str:
        """最多列 limit 个，其余折成「等 N 人」。"""
        shown = "、".join(items[:limit])
        return shown if len(items) <= limit else f"{shown} 等 {len(items)} 人"

    def get_all_points_list(self) -> List[float]:
        """获取所有分值列表（去重并排序）。"""
        self._logger.debug("从数据库获取所有分值列表")
        if not self._conn:
            raise RuntimeError("数据库连接未建立，请在 with 语句中使用 FileManager")
        
        cursor = self._conn.cursor()
        cursor.execute("SELECT DISTINCT points FROM students")
        points = [row[0] for row in cursor.fetchall()]
        self._logger.info(f"获取到 {len(points)} 个不同的分值: {sorted(points)}")
        return sorted(points)

    def get_unprocessed_students_by_points(self, points: float) -> List[Student]:
        """提取特定分值且状态为未处理的所有学生。
        
        Args:
            points: 要查询的分值
            
        Returns:
            符合条件的学生列表
            
        Raises:
            sqlite3.Error: 数据库查询失败
        """
        self._logger.info(f"查询分值为 {points}，状态为未处理的学生...")
        
        if not self._conn:
            raise RuntimeError("数据库连接未建立，请在 with 语句中使用 FileManager")
        
        cursor = self._conn.cursor()
        
        # 查询符合条件的学生
        cursor.execute("""
            SELECT student_id, name, points, status
            FROM students
            WHERE points = ? AND status = '未处理'
            ORDER BY student_id
        """, (points,))
        
        rows = cursor.fetchall()
        
        # 转换为 Student 对象列表
        students = [
            Student(
                student_id=row[0],
                name=row[1],
                points=row[2],
                status=row[3]
            )
            for row in rows
        ]
        
        self._logger.info(f"查询完成，找到 {len(students)} 名学生")
        return students

    def update_students_status(self, students: List[Student]) -> None:
        """批量更新学生列表的状态信息。
        
        为了提高断电容错性，每个学生更新后立即提交到数据库。
        这样即使突然断电，已更新的学生状态也不会丢失。
        
        Args:
            students: 要更新的学生列表
            
        Raises:
            sqlite3.Error: 数据库更新失败
        """
        if not students:
            self._logger.warning("学生列表为空，无需更新")
            return
        
        self._logger.info(f"开始更新 {len(students)} 名学生的状态...")
        
        if not self._conn:
            raise RuntimeError("数据库连接未建立，请在 with 语句中使用 FileManager")
        
        cursor = self._conn.cursor()
        
        update_count = 0
        not_found_count = 0
        
        # 逐个更新学生并立即提交，提高断电容错性
        for student in students:
            try:
                cursor.execute(
                    """
                    UPDATE students
                    SET name = ?,
                        points = ?,
                        status = ?,
                        updated_at = datetime('now', 'localtime')
                    WHERE student_id = ?
                    """,
                    (student.name, student.points, student.status, student.student_id),
                )

                if cursor.rowcount:
                    update_count += 1
                    # 立即提交该学生的更新，确保断电不丢失
                    self._conn.commit()
                    self._logger.debug(f"学号 {student.student_id} 状态更新已提交")
                else:
                    not_found_count += 1
                    self._logger.warning(f"学号 {student.student_id} 不存在于数据库中")
                    
            except Exception as e:
                # 单个学生更新失败不影响其他学生
                self._logger.error(f"更新学号 {student.student_id} 失败: {e}")
                not_found_count += 1
                # 尝试回滚当前失败的操作
                try:
                    self._conn.rollback()
                except Exception:
                    pass
        
        self._logger.info(
            f"状态更新完成: 成功更新 {update_count} 条，未找到/失败 {not_found_count} 条记录"
        )

    def export_db_to_excel(self, output_path: Optional[Path] = None) -> Path:
        """将数据库完整导出为 Excel 文件。
        
        Args:
            output_path: 输出文件路径，如果为 None 则使用默认路径
            
        Returns:
            导出的 Excel 文件路径
            
        Raises:
            sqlite3.Error: 数据库查询失败
            Exception: Excel 导出失败
        """
        if output_path is None:
            output_path = self._config.output_dir / f"{self._config.activity_name}.xlsx"
        else:
            output_path = Path(output_path)
        
        self._logger.info(f"开始导出数据库到 Excel 文件: {output_path}")
        
        if not self._conn:
            raise RuntimeError("数据库连接未建立，请在 with 语句中使用 FileManager")
        
        # 读取所有学生数据
        query = """
            SELECT 
                student_id AS '学号',
                name AS '姓名',
                points AS '分值',
                status AS '状态',
                created_at AS '创建时间',
                updated_at AS '更新时间'
            FROM students
            ORDER BY points DESC, student_id
        """
        
        self._logger.debug("执行 SQL 查询以获取所有学生数据")
        df = pd.read_sql_query(query, self._conn)
        
        if df.empty:
            self._logger.warning("数据库为空，没有数据可导出")
            # 创建空的 Excel 文件
            df.to_excel(output_path, index=False, engine='openpyxl')
        else:
            # 导出到 Excel
            df.to_excel(output_path, index=False, engine='openpyxl')
            self._logger.info(f"成功导出 {len(df)} 条记录到 Excel 文件: {output_path}")
        
        return output_path
    
    def get_unprocessed_students_count(self) -> int:
        """获取所有未处理学生的总人数。"""
        self._logger.debug("查询数据库中未处理学生总数")
        if not self._conn:
            raise RuntimeError("数据库连接未建立，请在 with 语句中使用 FileManager")
        
        cursor = self._conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) FROM students WHERE status = '未处理'
        """)
        count = cursor.fetchone()[0]
        self._logger.info(f"数据库中未处理学生总数: {count}")
        return count

    def cleanup(self) -> None:
        """清理临时文件和数据库连接。
        
        删除输出目录中的数据库文件和 JSON 配置文件。
        """
        self._logger.info("开始清理临时文件...")
        
        # 清理数据库文件
        db_path = self._config.output_dir / "students.db"
        if db_path.exists():
            try:
                db_path.unlink()
                self._logger.info(f"已删除数据库文件: {db_path}")
            except Exception as e:
                self._logger.error(f"删除数据库文件失败: {db_path}，错误: {e}")
        
        # 清理数据库 WAL 和 SHM 文件（SQLite WAL 模式产生的文件）
        wal_path = self._config.output_dir / "students.db-wal"
        if wal_path.exists():
            try:
                wal_path.unlink()
                self._logger.info(f"已删除 WAL 文件: {wal_path}")
            except Exception as e:
                self._logger.error(f"删除 WAL 文件失败: {wal_path}，错误: {e}")
        
        shm_path = self._config.output_dir / "students.db-shm"
        if shm_path.exists():
            try:
                shm_path.unlink()
                self._logger.info(f"已删除 SHM 文件: {shm_path}")
            except Exception as e:
                self._logger.error(f"删除 SHM 文件失败: {shm_path}，错误: {e}")
        
        # 清理 JSON 配置文件
        config_path = self._config.output_dir / "config.json"
        if config_path.exists():
            try:
                config_path.unlink()
                self._logger.info(f"已删除配置文件: {config_path}")
            except Exception as e:
                self._logger.error(f"删除配置文件失败: {config_path}，错误: {e}")
        
        self._logger.info("临时文件清理完成")
