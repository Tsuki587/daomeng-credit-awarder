# 到梦空间逐人发分工具

[English](README.en.md) · [Linux 补充说明](README-Linux.md)

本工具在 Windows、macOS 或 Linux 电脑上运行，通过 ADB 操作安卓手机上的“到梦空间”App，按 Excel 名单**逐人**颁发活动学分；它不是到梦空间的批量发分接口，也不是免安装的桌面程序。请仅在你有活动管理权限并完成学生签到或补签后使用。

> 发分会真实修改 App 中的记录。先用测试活动和少量测试名单核对操作；不要用正式名单试运行。真实颁发流程已在 Linux + 安卓手机上实机跑通；Windows、macOS 只做过自动测试，尚未实机跑过。

## 1. 准备电脑和手机

- 电脑安装 Python 3.11 或更新版本，以及 [Android SDK Platform-Tools](https://developer.android.com/tools/releases/platform-tools) 中的 `adb`。安装后在终端运行 `python --version`（Windows）或 `python3 --version`（macOS/Linux），并运行 `adb devices`。如果 `adb` 不在 `PATH` 中，可按下文设置 `ADBUTILS_ADB_PATH`。
- 安卓手机安装并登录“到梦空间”；账号需有目标活动的管理和发分权限。开启 USB 调试，连接电脑，在手机上允许调试授权。`adb devices` 中的设备状态应为 `device`。电脑只负责自动操作安卓手机，不能用 iPhone 替代。
- 先为要发分的学生全部签到或补签。本程序不导入签到名单，也不支持 App 的批量颁发。

### Windows（PowerShell）

安装 Python 时确保终端能找到 `python`。从 Google 官方页面下载 Windows 版 Platform-Tools，并将 `adb.exe` 所在目录加入 `PATH`；也可以在当前 PowerShell 窗口指定绝对路径：

```powershell
$env:ADBUTILS_ADB_PATH = 'C:\Android\platform-tools\adb.exe'
& $env:ADBUTILS_ADB_PATH devices
cd C:\path\to\daomeng
.\install-windows.cmd
.\run-windows.cmd -h
```

把示例路径换成你电脑上的真实路径。首次安装依赖需要网络；依赖装进项目的 `.venv`，不必激活虚拟环境。

### macOS（Terminal）

安装 Python 3 和 Google 官方 macOS 版 Platform-Tools。macOS 与 Linux 共用 Bash 启动脚本：

```bash
export ADBUTILS_ADB_PATH="/absolute/path/platform-tools/adb"
"$ADBUTILS_ADB_PATH" devices
cd "/absolute/path/daomeng"
bash install-linux.sh
bash run-linux.sh -h
```

若 `adb` 已在 `PATH` 中，无需设置环境变量。这里用 `bash` 调用脚本，不要求修改文件权限。

### Linux（以 Ubuntu 为例）

```bash
sudo apt update
sudo apt install python3 python3-venv adb
adb devices
cd "/absolute/path/daomeng"
bash install-linux.sh
bash run-linux.sh -h
```

其他发行版可使用其包管理器或 Google 官方 Platform-Tools；`adb` 不在 `PATH` 时，按 macOS 示例设置 `ADBUTILS_ADB_PATH`。

## 2. 准备 Excel

发分名单是必需的，录取名单可选，格式均为 `.xlsx`：

| 文件 | 必需列 | 用途 |
| --- | --- | --- |
| 每份发分名单 | `学号`、`姓名` | 每人一行；命令中写该表的实际分值 |
| 录取名单（可选） | `活动名称`、`学号`、`姓名` | 作为人员校验基准，命令中分值写 `0`，不发 0 分。给了它，名单里的人必须也在录取名单里，否则记为“未报名”不发 |

活动名称在图形界面里直接填、命令行用 `--activity` 给，不必再为它准备录取名单。活动名要和 App 里看到的完整名称一致，程序用它在 App 里搜索活动并命名结果目录。

录取名单至少有两条数据；给了录取名单又没写 `--activity` 时，程序读取“活动名称”列的**第二条数据**作为活动名（合并单元格常见这样写）。学号尽量按 11 位文本保存；单元格开头多余的反引号会被去掉。检查名单、分值和活动名后再发分。

## 3. 开始发分

下面是 1 分、2 分两份发分名单的示例。`-i` 在首次连接该手机或需要重新初始化手机端自动化服务时使用；它**不是单独的初始化命令**，仍会继续实际发分。以后正常运行可去掉 `-i`。

Windows PowerShell：

```powershell
cd C:\path\to\daomeng
.\run-windows.cmd --activity "活动全名" -f "C:\Lists\1分.xlsx" 1 -f "C:\Lists\2分.xlsx" 2 -i
```

macOS：

```bash
cd "/absolute/path/daomeng"
bash run-linux.sh --activity "活动全名" -f "/absolute/path/1分.xlsx" 1 -f "/absolute/path/2分.xlsx" 2 -i
```

Linux：

```bash
cd "/absolute/path/daomeng"
bash run-linux.sh --activity "活动全名" -f "/absolute/path/1分.xlsx" 1 -f "/absolute/path/2分.xlsx" 2 -i
```

分值不限于整数，`-f "/absolute/path/名单.xlsx" 2.5` 就按 2.5 分发；有几份名单就写几组 `-f`，少写一组就是不发那一种。要按录取名单校验人员，再加 `-f "录取名单.xlsx" 0`；不加就是名单里的人按学号直接发。无线调试、指定设备及其他选项见对应系统的 `-h` 输出。手机或终端要求登录、确认时，按提示处理。

### 图形界面（可选）

不想记命令行参数时，可以用图形界面；它和命令行走同一套发分流程：

```powershell
# Windows
.\venv\Scripts\python.exe -m pip install -r requirements-gui.txt
.\venv\Scripts\python.exe DM-gui.py
```

```bash
# macOS / Linux
./.venv/bin/python -m pip install -r requirements-gui.txt
./.venv/bin/python DM-gui.py
```

窗口左边填活动名称（App 里那个完整名称）、按需加任意份发分名单并各自填分值（首次连接勾“初始化设备”），录取名单是选填的；点“加入队列”排进等候区；之前没跑完的运行目录用“继续上次任务...”挑进去，会接着原来的进度跑、不会重发；排好几条后点“开始队列”，程序会按从上到下的顺序一个活动接一个活动地跑，中间不用守着；顺序不对就选中一条用“上移”“下移”调整。某条失败会停下来等你看：处理好手机上的情况后点“重试这条”接着跑（从它的运行目录续上，不会重发），或者“跳过这条”先跑下一个。“停止”会停掉整条队列，当前这个学生处理完就停，进度照常保存。手机上需要人工处理（掉登录、需要重连）时会弹窗提示。Linux 下再执行 `./install-desktop.sh` 可在桌面和应用列表放一个图标，点一下直接打开。

Windows 上可用 `build-windows.cmd` 打包成免安装目录 `dist\daomeng-gui`（须在 Windows 上打包，PyInstaller 不能跨平台）。把 `adb.exe` 放到 `vendor\platform-tools\` 会一并打进包里，否则目标电脑仍需自备 `platform-tools`。

## 4. 结果、中断与核对

程序会打印输出目录，位于程序文件夹下，名称为“活动名-时间”。其中有 `automation.log`、进度数据库和 `config.json`；**正常完成后**导出一份以活动名命名、包含所有学生及其状态的 Excel。异常中断时可能尚未导出 Excel，但进度仍可用于恢复。

恢复时使用**同一个输出目录**，不要再传 `-f`；保留原 Excel 文件在原路径：

```powershell
# Windows
.\run-windows.cmd -r "C:\path\to\daomeng\活动名-时间"
```

```bash
# macOS / Linux
bash run-linux.sh -r "/absolute/path/daomeng/活动名-时间"
```

命令行用上面的 `-r`；图形界面里用“继续上次任务...”选那个目录加进队列，或者某条任务失败后点“重试这条”，都会从它自己的运行目录接着跑。续跑前会拿名单和进度库对一遍；“继续上次任务...”发现名单改过（加了人、删了人、换了活动）会列出来让你确认。确认后按现在的名单来：新加的人补进去一起发，录取名单里后来补上的人也会恢复为待发，已经发过的不会重发。

仅状态为“未处理”的学生会自动继续。搜索两次仍无法确认的学生标记“待核对”，不会点颁发；“待核对”和“状态未知”不要直接重发，先在 App 核对。**点击“确定”后发生异常的自动重试逻辑目前未修改，仍有重复颁发风险**；遇到此情形应立即人工核对。App 的实际发分记录是最终依据。

使用 `-u` 账号表时，任务目录的 `config.json` 可能保存明文账号密码。结果目录、Excel、日志和账号表含有敏感信息，不要公开分享。
