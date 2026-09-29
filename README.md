# 到梦空间逐人发分工具

[English](README.en.md) · [Linux 补充说明](README-Linux.md)

本工具在 Windows、macOS 或 Linux 电脑上运行，通过 ADB 操作安卓手机上的“到梦空间”App，按 Excel 名单**逐人**颁发活动学分；它不是到梦空间的批量发分接口，也不是免安装的桌面程序。请仅在你有活动管理权限并完成学生签到或补签后使用。

> 发分会真实修改 App 中的记录。先用测试活动和少量测试名单核对操作；不要用正式名单试运行。当前只有 Linux 环境的自动测试和搜索页观察，Windows、macOS 以及真实颁发流程尚未实机验证。

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

至少需要一份录取名单和一份发分名单，格式均为 `.xlsx`：

| 文件 | 必需列 | 用途 |
| --- | --- | --- |
| 录取名单 | `活动名称`、`学号`、`姓名` | 作为人员校验基准，命令中分值写 `0`，不发 0 分 |
| 每份发分名单 | `学号`、`姓名` | 每人一行；命令中写该表的实际分值 |

录取名单至少有两条数据；程序读取“活动名称”列的**第二条数据**作为活动名，用它在 App 搜索活动并命名结果目录。其余行不必重复填写活动名。学号尽量按 11 位文本保存；单元格开头多余的反引号会被去掉。检查名单、分值和活动名后再发分。

## 3. 开始发分

下面是 1 分、2 分两份发分名单的示例。`-i` 在首次连接该手机或需要重新初始化手机端自动化服务时使用；它**不是单独的初始化命令**，仍会继续实际发分。以后正常运行可去掉 `-i`。

Windows PowerShell：

```powershell
cd C:\path\to\daomeng
.\run-windows.cmd -f "C:\Lists\录取名单.xlsx" 0 -f "C:\Lists\1分.xlsx" 1 -f "C:\Lists\2分.xlsx" 2 -i
```

macOS：

```bash
cd "/absolute/path/daomeng"
bash run-linux.sh -f "/absolute/path/录取名单.xlsx" 0 -f "/absolute/path/1分.xlsx" 1 -f "/absolute/path/2分.xlsx" 2 -i
```

Linux：

```bash
cd "/absolute/path/daomeng"
bash run-linux.sh -f "/absolute/path/录取名单.xlsx" 0 -f "/absolute/path/1分.xlsx" 1 -f "/absolute/path/2分.xlsx" 2 -i
```

只发一种分值时，删去另一组 `-f "文件路径" 分值`。无线调试、指定设备及其他选项见对应系统的 `-h` 输出。手机或终端要求登录、确认时，按提示处理。

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

仅状态为“未处理”的学生会自动继续。搜索两次仍无法确认的学生标记“待核对”，不会点颁发；“待核对”和“状态未知”不要直接重发，先在 App 核对。**点击“确定”后发生异常的自动重试逻辑目前未修改，仍有重复颁发风险**；遇到此情形应立即人工核对。App 的实际发分记录是最终依据。

使用 `-u` 账号表时，任务目录的 `config.json` 可能保存明文账号密码。结果目录、Excel、日志、账号表及虚拟环境均不要上传到 GitHub。

## 5. 发布到 GitHub

本目录已经是 Git 仓库，目前 `origin` 指向 `https://github.com/tangent2pi/daomeng`。**不要在不确认仓库归属和权限时直接推送。**先运行：

```bash
git status --short --branch
git remote -v
git ls-files
```

确认跟踪列表中没有学号名单、结果目录、密码或其他个人资料，并决定是否有权公开这些源码、采用什么许可证。当前仓库没有 `LICENSE`，不要自行假定别人可如何使用；若是别人的项目，优先在 GitHub 上 Fork 并保留来源。

- 如果你有 `tangent2pi/daomeng` 的写入权限，确认本地提交后执行 `git push origin main`。
- 如果没有，先在 GitHub Fork 原仓库，再把自己的 Fork 地址加为新远端，例如 `git remote add myfork https://github.com/你的用户名/daomeng.git`，执行 `git push -u myfork main`。不要把示例用户名原样复制。
- 推送后打开仓库页面，确认中英文说明、脚本和源码可见，且没有名单或账号文件。若要标版本，在仓库的 **Releases → Draft a new release** 创建 tag 并发布；GitHub 会提供该版本源码压缩包。这里提供的是源码安装方式，**不是** Windows `.exe` 或 macOS `.app`。

操作界面以 [GitHub 创建仓库文档](https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-new-repository)、[推送本地代码文档](https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github) 和 [发布 Release 文档](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository) 为准。
