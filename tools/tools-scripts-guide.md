# `tools` 脚本使用指南

本文说明仓库 `tools/` 目录中的六个脚本：

| 脚本 | 用途 | 默认是否修改数据 |
| --- | --- | --- |
| `setup_environment.py` | 创建/检查本地运行环境 | 会创建 `data/` 和缺失的 `.env`；加 `--check` 后只读 |
| `sync_telegram_game_bots.py` | 扫描目标 Telegram 群并检查/同步游戏 Bot ID | 默认只检查；只有 `--apply` 会同步业务数据 |
| `reconcile_overdue_schedules.py` | 检查全部 profile 的过期未执行调度，并调用原队列型 scheduler 补偿 | 默认只检查；只有 `--apply` 会重新入队 |
| `run_telegram_game_bot_sync_scheduled.py` | 供计划任务依次执行 Bot 同步和调度补偿，并记录日志 | 会执行两个脚本的 `--apply` |
| `install_telegram_game_bot_schedule.ps1` | 安装、更新周期、启用、停用或删除 Windows 计划任务 | 会修改当前用户的 Windows 计划任务 |
| `install_telegram_game_bot_schedule_macos.sh` | 安装、更新或管理 macOS LaunchAgent | 会修改当前用户的 `~/Library/LaunchAgents` |

所有命令都应在仓库根目录执行：

```powershell
cd <你的仓库目录>
```

## 一、公共前置条件

- Python `3.10+`。
- 仓库根目录存在 `.env.example`、`requirements.txt`、`run_services.py`。
- 能正常访问 Telegram；需要扫描群 Bot 时，Telegram 账号必须已经加入目标群。
- Windows 使用 PowerShell；macOS/Linux 将 `python` 换成 `python3`，虚拟环境解释器路径换成 `.venv/bin/python`。

建议先查看当前 Python：

```powershell
python --version
```

## 二、`setup_environment.py`

### 作用

该脚本负责：

1. 检查 Python 版本是否为 `3.10+`。
2. 创建 `data/` 目录。
3. `.env` 不存在时，从 `.env.example` 复制生成；已有 `.env` 不会被覆盖。
4. 使用 `--install` 时创建虚拟环境并安装 `requirements.txt`。
5. 检查 `.env` 必填项，并打印后续启动命令。

### 首次初始化

在仓库内创建 `.venv`、安装依赖并生成 `.env`：

```powershell
python tools/setup_environment.py --install
```

使用仓库外的虚拟环境：

```powershell
python tools/setup_environment.py --install --venv <虚拟环境目录>
```

`--venv` 使用相对路径时，相对于仓库根目录解析；也可以直接填写绝对路径。

### 配置 `.env`

打开配置文件：

```powershell
notepad .env
```

必填项：

```dotenv
TELEGRAM_API_ID=
TELEGRAM_API_HASH=
TG_GAME_BOUND_CHAT_ID=
TG_GAME_BOUND_BOT_ID=
```

按需填写：

```dotenv
# topic 群填写；普通群留空
TG_GAME_BOUND_THREAD_ID=

# 额外可信游戏 Bot ID，多个 ID 使用英文逗号分隔
TG_GAME_ALLOWED_BOT_IDS=

# 管理员 Telegram 用户 ID
AUTHORIZED_USER_ID=

# Web 监听地址和端口
TG_GAME_HOST=127.0.0.1
TG_GAME_PORT=8787
```

### 只读检查

```powershell
python tools/setup_environment.py --check
```

`--check` 不创建目录、不复制 `.env`、不创建虚拟环境，也不安装依赖。

用于部署检查或 CI；必填配置缺失时返回非零退出码：

```powershell
python tools/setup_environment.py --check --strict
```

### 参数说明

| 参数 | 说明 |
| --- | --- |
| `--install` | 创建虚拟环境，并安装 `requirements.txt` |
| `--venv <目录>` | 指定虚拟环境目录，默认 `.venv` |
| `--check` | 只检查，不创建或安装任何内容 |
| `--strict` | `.env` 必填项缺失时返回退出码 `1` |

### 初始化后启动

Windows：

```powershell
.venv\Scripts\python.exe run_services.py all
```

macOS/Linux：

```bash
.venv/bin/python run_services.py all
```

首次登录 Telegram 时，按终端提示输入手机号、验证码和二步验证密码。

## 三、`sync_telegram_game_bots.py`

### 作用和安全边界

该脚本会读取目标群的 Bot 成员和近期消息，只识别：

- `fanrenxiuxian_bot`
- `hantianzun数字_bot`

脚本不会向 Telegram 发送消息，不会停止或重启服务，也不会删除暂时未出现在本次扫描中的旧轮换 Bot ID。

### 使用前置条件

运行前必须满足：

1. 已通过 `setup_environment.py --install` 安装依赖。
2. `.env` 已配置 `TELEGRAM_API_ID`、`TELEGRAM_API_HASH` 和 `TG_GAME_BOUND_CHAT_ID`。
3. topic 群已正确配置 `TG_GAME_BOUND_THREAD_ID`；普通群保持为空。
4. `data/tg_game.db` 已存在，并包含 profile 和当前目标群绑定。
5. 至少一个 profile 配有可用且已授权的 Telegram session；session 对应账号能访问目标群。
6. 执行 `--apply` 前，每个 profile 必须恰好有一条当前群的活动绑定；缺失、停用或重复绑定都会阻止写入。
7. `.env` 中保留 `TG_GAME_ALLOWED_BOT_IDS=` 配置行；可以为空，但 `--apply` 写入时需要该字段存在。

建议使用已安装依赖的虚拟环境解释器运行：

```powershell
.venv\Scripts\python.exe tools\sync_telegram_game_bots.py --check
```

### 先执行只读检查

```powershell
python tools/sync_telegram_game_bots.py --check
```

不写 `--check` 或 `--apply` 时，同样默认为只读检查：

```powershell
python tools/sync_telegram_game_bots.py
```

检查结果会显示：

- 扫描使用的 profile/session。
- 实际检查的近期消息数量。
- 群上识别到的游戏 Bot。
- `.env` 和每个 profile 当前保存的 Bot 数量。
- 同步后的目标数量、保留的旧轮换 ID 和绑定阻塞项。

`--check` 不修改 `.env`、数据库、扫描快照或 `progress.md`。脚本仍会创建/使用 `data/telegram_game_bot_sync.lock`，用于阻止多个同步进程并发运行。

### 调整消息扫描数量

默认扫描最近 `2000` 条消息，同时读取群 Bot 成员列表：

```powershell
python tools/sync_telegram_game_bots.py --check --message-limit 5000
```

`--message-limit` 必须大于 `0`。数值越大，扫描时间和 Telegram API 请求量越高。

### 正式同步

确认只读结果无阻塞项后执行：

```powershell
python tools/sync_telegram_game_bots.py --apply --message-limit 5000
```

当本地配置确实需要更新时，脚本会：

1. 创建数据库备份：`data/tg_game-before-bot-sync-YYYYMMDD-HHMMSS.db`。
2. 将 `.env` 的 `TG_GAME_ALLOWED_BOT_IDS` 更新为合并后的可信 ID。
3. 同步当前群全部 profile 的 `bot_ids` 和已识别 username。
4. 执行 SQLite 完整性和外键检查。
5. 更新 `data/telegram_game_bot_scan.json`。
6. 在 `progress.md` 追加同步结果和精确回滚点。

目标列表会合并 `.env`、数据库已有绑定和本次群扫描结果，因此旧轮换 ID 会被保留；脚本不会修改主 Bot 配置 `TG_GAME_BOUND_BOT_ID`。

如果本地已经同步，`--apply` 只刷新最近扫描快照，不创建数据库备份，也不追加同步日志。

同步完成后无需重启服务，后续消息会读取数据库中的新绑定。

命令运行期间会持有 `data/telegram_game_bot_sync.lock`。计划任务、命令行和网页同步按钮不能同时执行；后启动的任务会提示“已有 Bot 同步任务正在运行”。

### 参数说明

| 参数 | 说明 |
| --- | --- |
| `--check` | 只扫描和比较，不修改任何数据 |
| `--apply` | 备份后同步 `.env` 和数据库 |
| `--message-limit <数量>` | 近期消息扫描数量，默认 `2000` |

`--check` 和 `--apply` 不能同时使用。

### 常见失败

| 提示 | 处理方式 |
| --- | --- |
| `.env 缺少 TELEGRAM_API_ID 或 TELEGRAM_API_HASH` | 补全 Telegram API 配置 |
| `.env 缺少 TG_GAME_BOUND_CHAT_ID` | 填写目标群/会话 ID |
| `data/tg_game.db` 不存在或缺表 | 先正常初始化并运行项目，创建数据库和 profile |
| `session 文件不存在` | 检查 profile 的 session 名称及 `data/*.session` 文件 |
| `session 未授权` | 先完成该 Telegram 账号登录 |
| `当前 Telegram 账号无法访问群` | 确认账号已加入目标群，且群 ID 正确 |
| `存在绑定阻塞项，拒绝执行 --apply` | 修复缺失、非活动或重复的当前群绑定后，重新执行 `--check` |
| `扫描期间目标群配置发生变化` | 不要在扫描期间修改群/topic 配置，重新执行命令 |
| `已有 Bot 同步任务正在运行` | 等待当前命令、网页同步或计划任务结束后重试 |

### 回滚 `--apply`

每次发生实际同步时，终端和 `progress.md` 都会给出本次备份路径及同步前 ID。需要人工回滚时：

1. 先停止 Web/Telegram 服务，避免 SQLite 正在写入。
2. 恢复本次生成的数据库备份。
3. 将 `.env` 的 `TG_GAME_ALLOWED_BOT_IDS` 恢复为 `progress.md` 记录的同步前值。
4. 再启动服务并执行一次 `--check`。

PowerShell 示例：

```powershell
Remove-Item data\tg_game.db-wal,data\tg_game.db-shm -Force -ErrorAction SilentlyContinue
Copy-Item data\tg_game-before-bot-sync-YYYYMMDD-HHMMSS.db data\tg_game.db -Force
python tools/sync_telegram_game_bots.py --check --message-limit 5000
```

## 四、`reconcile_overdue_schedules.py`

### 作用和安全边界

只读检查：

```powershell
.venv\Scripts\python.exe tools\reconcile_overdue_schedules.py --check
```

受控补偿：

```powershell
.venv\Scripts\python.exe tools\reconcile_overdue_schedules.py --apply
```

不写参数时等同于 `--check`。`--check` 是只读审计；`--apply` 会生成新的 `outgoing_commands`。如果 Telegram runtime 正在运行，新入队命令可能随即发往目标群，因此需要严格 no-send 时只能使用 `--check`。

脚本检查全部 profile 的当前活动群调度，只有至少过期 `60` 秒且没有活动 outgoing 阻塞的任务才进入候选。`--apply` 不直接发送 Telegram 指令，而是调用原有通用自动任务、钓鱼、批量代卜或天星 scheduler 的单轮入口，由其重新检查冷却、当天执行记录、资源和业务状态后写入 `outgoing_commands`。

以下情况只记录、不补偿：

- `pending / sending / awaiting_confirm / needs_manual_confirm`。
- 等待 Bot 回包或人工确认的状态机。
- 非当前活动群、已停用、熔断或演练模式。
- 同一 profile 同一种任务本轮已经处理过。
- 仍由旧 runner 直接发送的凡人、元婴和宗门调度。

错过多个周期只补当前一次。重复执行时，已入队或已经由 executor 重新排期的任务不会再次生成队列。并发命令会被 `data/overdue_schedule_reconcile.lock` 拒绝。

输出包含检查 profile 数、任务数、过期数、可补偿数、重新入队数、队列命令数、跳过原因和逐任务明细。任一 executor 执行失败时，脚本返回退出码 `1`。

参数说明：

| 参数 | 说明 |
| --- | --- |
| `--check` | 只审计过期调度，不加锁、不入队 |
| `--apply` | 持有补偿锁，调用原 scheduler 复核并按需入队 |

## 五、Windows 定时自动同步

### 三个脚本的分工

- `install_telegram_game_bot_schedule.ps1`：注册、更新周期、启用、停用或删除 Windows 计划任务。
- `run_telegram_game_bot_sync_scheduled.py`：由计划任务调用，先固定执行 `sync_telegram_game_bots.py --apply --message-limit 5000`；只有同步成功才继续执行 `reconcile_overdue_schedules.py --apply`。
- `reconcile_overdue_schedules.py`：只负责调度审计和补偿入队，不扫描 Telegram 群。

定时 runner 会把两个 Python 脚本的 stdout、stderr、退出码和总耗时追加到日志。Bot 同步返回非零（包括锁冲突）时不会启动调度补偿；补偿脚本返回非零时，整次任务记录为失败。网页“同步群 Bot”按钮只执行 Bot 同步，不触发补偿。

定时任务不是 no-send 流程：补偿阶段可能生成 `outgoing_commands`，在线 Telegram runtime 随后可能发送这些命令。

定时 runner 的扫描数量固定为 `5000`，没有可配置参数。执行周期由安装器或管理员 Profile 卡片设置，只允许 `1 / 2 / 3 / 6 / 12 / 24` 小时；不要给 runner 追加未经脚本支持的参数。

### 额外前置条件

定时任务安装器固定查找同一虚拟环境下的两个解释器：

```text
<仓库父目录>\.venvs\<仓库目录名>\Scripts\python.exe
<仓库父目录>\.venvs\<仓库目录名>\Scripts\pythonw.exe
```

例如仓库为 `E:\zidongxiuxian` 时，它会使用：

```text
E:\.venvs\zidongxiuxian\Scripts\python.exe
E:\.venvs\zidongxiuxian\Scripts\pythonw.exe
```

计划任务外层使用 `pythonw.exe` 静默启动，runner 再用同目录的 `python.exe` 执行同步和调度补偿，以保留 stdout/stderr 日志。仓库内默认的 `.venv\Scripts\python.exe` 不会被该安装器使用。缺少计划任务解释器时，先创建：

```powershell
$projectName = Split-Path -Leaf (Get-Location)
python tools/setup_environment.py --install --venv "..\.venvs\$projectName"
```

如果确定要启用计划任务，可以在首次初始化时直接使用这个虚拟环境目录，避免同时维护仓库内 `.venv` 和仓库外 `.venvs` 两套依赖。

还必须先满足 `sync_telegram_game_bots.py --apply` 的全部前置条件，包括 `.env`、数据库、profile 绑定和已授权 session。

### 安装或更新计划任务

默认安装为每 `1` 小时执行并立即处于启用状态：

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\install_telegram_game_bot_schedule.ps1
```

指定执行周期，只允许 `1 / 2 / 3 / 6 / 12 / 24` 小时：

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\install_telegram_game_bot_schedule.ps1 -IntervalHours 6
```

修改周期但保持任务关闭：

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\install_telegram_game_bot_schedule.ps1 -IntervalHours 6 -KeepDisabled
```

计划任务名称固定为：

```text
ZidongXiuxian Telegram Bot Sync
```

任务行为：

- 安装、保存周期或重新开启时，从服务器当前时间加所选周期开始运行。
- 重复计划有效期为 `3650` 天，期满后需重新运行安装脚本。
- 仅在当前 Windows 用户处于登录状态时运行，使用普通用户权限和 `pythonw.exe` 静默窗口。
- 错过执行时间后，在系统可用时补跑。
- 同一计划任务不会重叠；单次最长运行 `10` 分钟。
- 脚本锁还会阻止计划任务与命令行或网页同步并发写入。
- 手工关闭旧版命令窗口产生的 `0xC000013A` 会记录为“已被用户中断”，不会破坏卡片状态读取；新安装任务不再弹出该窗口。

### 查看状态

```powershell
Get-ScheduledTask -TaskName 'ZidongXiuxian Telegram Bot Sync'
Get-ScheduledTaskInfo -TaskName 'ZidongXiuxian Telegram Bot Sync'
```

### 启用或停用

停用已安装任务：

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\install_telegram_game_bot_schedule.ps1 -Disable
```

重新启用并保留原周期：

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\install_telegram_game_bot_schedule.ps1 -Enable
```

重新启用并改为每 `6` 小时执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\install_telegram_game_bot_schedule.ps1 -Enable -IntervalHours 6
```

`-Remove`、`-Enable`、`-Disable` 不能同时使用。任务不存在时，`-Disable` 会报错；`-Enable` 会按指定周期安装，未指定时默认 `1` 小时。

### 手动立即运行

以下命令会执行一次正式 Bot `--apply` 同步，并在成功后执行调度补偿，不是只读检查：

```powershell
Start-ScheduledTask -TaskName 'ZidongXiuxian Telegram Bot Sync'
```

查看最近日志：

```powershell
Get-Content data\telegram_game_bot_schedule.log -Tail 100
```

日志文件会持续追加，不会自动清空。无 Bot 变化时不会创建 Bot 数据库备份或追加 Bot 同步 `progress.md`，但后续调度补偿仍可能产生新的 outgoing 队列命令。

### 删除计划任务

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\install_telegram_game_bot_schedule.ps1 -Remove
```

删除计划任务不会删除 `.env`、数据库、扫描快照或历史日志。

## 六、macOS 定时自动同步

macOS 不使用 Windows Task Scheduler，安装器会创建当前用户的 LaunchAgent：

```text
~/Library/LaunchAgents/com.zidongxiuxian.telegram-bot-sync.plist
```

管理员 Profile 卡片当前仍只管理 Windows 计划任务；macOS 请使用下面的终端命令管理 LaunchAgent。

### 额外前置条件

macOS 安装器固定使用：

```text
<仓库父目录>/.venvs/<仓库目录名>/bin/python
```

首次准备：

```bash
project_name="$(basename "$PWD")"
python3 tools/setup_environment.py --install --venv "../.venvs/$project_name"
python3 tools/setup_environment.py --check --strict
```

### 安装或更新

默认每 `1` 小时执行：

```bash
bash tools/install_telegram_game_bot_schedule_macos.sh
```

指定周期：

```bash
bash tools/install_telegram_game_bot_schedule_macos.sh --interval-hours 6
```

更新 plist 但保持关闭：

```bash
bash tools/install_telegram_game_bot_schedule_macos.sh --interval-hours 6 --keep-disabled
```

允许周期同样为 `1 / 2 / 3 / 6 / 12 / 24` 小时。

### 状态、启用和停用

```bash
# 查看状态
bash tools/install_telegram_game_bot_schedule_macos.sh --status

# 停用
bash tools/install_telegram_game_bot_schedule_macos.sh --disable

# 按原周期重新启用
bash tools/install_telegram_game_bot_schedule_macos.sh --enable

# 重新启用并改为每 6 小时执行
bash tools/install_telegram_game_bot_schedule_macos.sh --enable --interval-hours 6
```

### 手动立即运行

```bash
bash tools/install_telegram_game_bot_schedule_macos.sh --run-now
```

`--run-now` 会执行真实 Bot 同步，并在成功后执行调度补偿；它不是只读/no-send 操作。

### 删除

```bash
bash tools/install_telegram_game_bot_schedule_macos.sh --remove
```

删除 LaunchAgent 不会删除 `.env`、数据库、扫描快照或历史日志。

### 文件和日志

- LaunchAgent label：`com.zidongxiuxian.telegram-bot-sync`
- 主执行日志：`data/telegram_game_bot_schedule.log`
- launchd stdout：`data/telegram_game_bot_launchd.stdout.log`
- launchd stderr：`data/telegram_game_bot_launchd.stderr.log`

共享 runner 在 Windows 下会从 `pythonw.exe` 切换到同目录的 `python.exe`；在 macOS/Linux 下直接复用当前 `sys.executable`。

## 七、推荐执行顺序

首次部署：

```powershell
python tools/setup_environment.py --install
notepad .env
python tools/setup_environment.py --check --strict
.venv\Scripts\python.exe run_services.py all
```

已有运行环境，只检查群 Bot：

```powershell
.venv\Scripts\python.exe tools\sync_telegram_game_bots.py --check --message-limit 5000
```

确认结果后正式同步：

```powershell
.venv\Scripts\python.exe tools\sync_telegram_game_bots.py --apply --message-limit 5000
```

需要定时同步和调度补偿时，先确认 Bot 同步 `--check`、Bot 同步 `--apply` 和调度补偿 `--check` 均正常，再安装计划任务：

```powershell
.venv\Scripts\python.exe tools\reconcile_overdue_schedules.py --check
powershell -ExecutionPolicy Bypass -File .\tools\install_telegram_game_bot_schedule.ps1
Get-ScheduledTaskInfo -TaskName 'ZidongXiuxian Telegram Bot Sync'
```

macOS：

```bash
project_name="$(basename "$PWD")"
"../.venvs/$project_name/bin/python" tools/reconcile_overdue_schedules.py --check
bash tools/install_telegram_game_bot_schedule_macos.sh
bash tools/install_telegram_game_bot_schedule_macos.sh --status
```
