# Daomeng credit-awarding automation

[简体中文](README.md) · [Linux notes in Chinese](README-Linux.md)

This source-based tool runs on Windows, macOS, or Linux and uses ADB to operate the Daomeng Space Android app. It awards activity credits **one student at a time** from Excel lists; it does not use a bulk-award API. Use it only with permission to manage the activity, after all intended students have checked in or been checked in retroactively.

> Awarding changes real records in the app. Verify the workflow with a test activity and a small test list, not a production list. Automated tests and search-screen observation have been performed on Linux only. Windows, macOS, and an end-to-end real award have not yet been tested on their respective systems.

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

For a single score, remove the other `-f "file path" score` pair. Run the platform-specific `-h` command for wireless debugging, device selection, and other options. Follow any login or confirmation prompt on the phone or in the terminal.

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

Only records marked `未处理` (unprocessed) resume automatically. If two searches cannot confirm a student, the tool marks `待核对` (needs review) and does not click Award. Do not blindly re-award `待核对` or `状态未知` (unknown status); check the app first. **The existing retry-on-exception behavior after clicking Confirm has not been changed and can still risk a duplicate award.** Check the app immediately if that happens. The app's actual credit record is authoritative.

If you use an account workbook with `-u`, `config.json` in the task directory may contain credentials in plain text. Never upload output directories, Excel lists, logs, account files, or `.venv` to GitHub.

## 5. Publish on GitHub

This directory is already a Git repository. Its current `origin` points to `https://github.com/tangent2pi/daomeng`. **Do not push before confirming the repository owner and your permissions.** First inspect:

```bash
git status --short --branch
git remote -v
git ls-files
```

Check that no student lists, results, passwords, or other personal data are tracked. Decide whether you have the right to publish the source and which license, if any, to use. There is currently no `LICENSE` file; do not assume that a license has been granted. If this is someone else's project, prefer a GitHub Fork and keep attribution.

- If you can write to `tangent2pi/daomeng`, push your local commits with `git push origin main`.
- Otherwise, Fork the original repository on GitHub, add your Fork as a separate remote, for example `git remote add myfork https://github.com/YOUR-USERNAME/daomeng.git`, then run `git push -u myfork main`. Replace the placeholder username.
- Open the repository page after pushing. Confirm that the Chinese and English guides, launchers, and code appear, and that no private files appear. To publish a version, open **Releases → Draft a new release**, create a tag, and publish it. GitHub provides a source archive for that version. This project currently offers **source-based installation, not** Windows `.exe` or macOS `.app` binaries.

See GitHub's official documentation for [creating repositories](https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-new-repository), [pushing local code](https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github), and [creating releases](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository).
