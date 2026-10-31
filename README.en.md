# Daomeng credit-awarding automation

[简体中文](README.md) · [Linux notes in Chinese](README-Linux.md)

This source-based tool runs on Windows, macOS, or Linux and uses ADB to operate the Daomeng Space Android app. It awards activity credits **one student at a time** from Excel lists; it does not use a bulk-award API. Use it only with permission to manage the activity, after all intended students have checked in or been checked in retroactively.

> Awarding changes real records in the app. Verify the workflow with a test activity and a small test list, not a production list. Automated tests and an end-to-end real award have been run on Linux against an Android phone. Windows and macOS remain untested on real hardware.

## 1. Computer and phone setup

- Install Python 3.11 or newer and `adb` from the official [Android SDK Platform-Tools](https://developer.android.com/tools/releases/platform-tools). Check `python --version` on Windows or `python3 --version` on macOS/Linux, then `adb devices`. If `adb` is not on `PATH`, set `ADBUTILS_ADB_PATH` as shown below.
- Install and sign in to the Daomeng Space app on an Android phone with an account authorized to manage and award credits for the activity. Enable USB debugging, connect the phone, and approve the debugging prompt. Its state in `adb devices` must be `device`. The host computer cannot replace the Android phone with an iPhone.
- Complete all check-ins or make-up check-ins before awarding. The tool does not import a check-in list or use app-side bulk awarding.

### Windows (PowerShell)

Make sure `python` is available in the terminal. Download Platform-Tools for Windows from Google and add the directory containing `adb.exe` to `PATH`, or set its absolute path in the current PowerShell session:

```powershell
$env:ADBUTILS_ADB_PATH = 'C:\Android\platform-tools\adb.exe'
& $env:ADBUTILS_ADB_PATH devices
cd C:\path\to\daomeng
.\install-windows.cmd
.\run-windows.cmd -h
```

Replace the example paths. Installing dependencies requires internet access. They go into the project's `.venv`; no activation is necessary.

### macOS (Terminal)

Install Python 3 and Google's macOS Platform-Tools. macOS and Linux share the Bash launchers:

```bash
export ADBUTILS_ADB_PATH="/absolute/path/platform-tools/adb"
"$ADBUTILS_ADB_PATH" devices
cd "/absolute/path/daomeng"
bash install-linux.sh
bash run-linux.sh -h
```

Skip the environment variable if `adb` is already on `PATH`. Calling the scripts with `bash` does not require changing file permissions.

### Linux (Ubuntu example)

```bash
sudo apt update
sudo apt install python3 python3-venv adb
adb devices
cd "/absolute/path/daomeng"
bash install-linux.sh
bash run-linux.sh -h
```

On another distribution, use its package manager or Google's Platform-Tools. If `adb` is not on `PATH`, set `ADBUTILS_ADB_PATH` as in the macOS example.

## 2. Excel input

You need an enrollment workbook and at least one award workbook, all in `.xlsx` format:

| File | Required columns | Purpose |
| --- | --- | --- |
| Enrollment list | `活动名称`, `学号`, `姓名` | Validation reference; use score `0` in the command, which does **not** award zero credits |
| Each award list | `学号`, `姓名` | One student per row; supply that list's actual score in the command |

The enrollment workbook needs at least two data rows. The program takes the activity name from the **second data row** of `活动名称`; it uses that value to find the activity in the app and name the output directory. Other rows need not repeat the activity name. Keep student IDs as 11-digit text where possible. A stray leading backtick is removed when reading the ID. Review names, IDs, scores, and the activity name before running.

## 3. Award credits

The following examples use two award lists, worth 1 and 2 credits. Use `-i` for the first connection to a phone or when the phone-side automation service needs reinitialization. **`-i` is not an initialization-only command:** it continues with real awarding. Omit it on later normal runs.

Windows PowerShell:

```powershell
cd C:\path\to\daomeng
.\run-windows.cmd -f "C:\Lists\录取名单.xlsx" 0 -f "C:\Lists\1分.xlsx" 1 -f "C:\Lists\2分.xlsx" 2 -i
```

macOS:

```bash
cd "/absolute/path/daomeng"
bash run-linux.sh -f "/absolute/path/录取名单.xlsx" 0 -f "/absolute/path/1分.xlsx" 1 -f "/absolute/path/2分.xlsx" 2 -i
```

Linux:

```bash
cd "/absolute/path/daomeng"
bash run-linux.sh -f "/absolute/path/录取名单.xlsx" 0 -f "/absolute/path/1分.xlsx" 1 -f "/absolute/path/2分.xlsx" 2 -i
```

Scores are not limited to whole numbers: `-f "/absolute/path/list.xlsx" 2.5` awards 2.5 credits. Pass one `-f` pair per list; omit a pair to skip that score. Run the platform-specific `-h` command for wireless debugging, device selection, and other options. Follow any login or confirmation prompt on the phone or in the terminal.

### Optional graphical interface

If you would rather not type the command line, the GUI runs exactly the same awarding flow:

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

It can start a new task (pick the roster, add as many award lists as you need and type each list's score, tick initialization on first connect) and add it to a queue; an unfinished run directory can be queued with "Resume previous task...", which continues from the saved progress without awarding anything twice; press "Start queue" and it works through the activities one after another without supervision. A failed task pauses the queue: after sorting out the phone, use "Retry this" to continue that task from its own run directory (nothing is awarded twice) or "Skip this" to move on. "Stop" halts the whole queue once the current student is done, keeping all progress. When the phone needs you (signed out, reconnect required), it shows a dialog and waits. On Linux, `./install-desktop.sh` adds a desktop and application-menu icon that opens the GUI in one click.

On Windows, `build-windows.cmd` packages a portable folder in `dist\daomeng-gui` (build on Windows; PyInstaller cannot cross-compile). Put `adb.exe` in `vendor\platform-tools\` to bundle it, otherwise the target computer needs its own `platform-tools`.

## 4. Results, resuming, and verification

The program prints an output directory under the program folder, named after the activity and time. It contains `automation.log`, a progress database, and `config.json`. **After normal completion**, it exports one full Excel workbook named after the activity, with every student's status. An interrupted run may not have exported the workbook yet, but its saved progress can be resumed.

Resume using **the same output directory**, without `-f`, and keep the original input workbooks at their original paths:

```powershell
# Windows
.\run-windows.cmd -r "C:\path\to\daomeng\activity-time"
```

```bash
# macOS / Linux
bash run-linux.sh -r "/absolute/path/daomeng/activity-time"
```

In the GUI, queue the directory with "Resume previous task...", or press "Retry this" after a failed task; both continue from that task's own run directory.

Only records marked `未处理` (unprocessed) resume automatically. If two searches cannot confirm a student, the tool marks `待核对` (needs review) and does not click Award. Do not blindly re-award `待核对` or `状态未知` (unknown status); check the app first. **The existing retry-on-exception behavior after clicking Confirm has not been changed and can still risk a duplicate award.** Check the app immediately if that happens. The app's actual credit record is authoritative.

If you use an account workbook with `-u`, `config.json` in the task directory may contain credentials in plain text. Output directories, Excel lists, logs, and account files contain sensitive information; do not share them publicly.
