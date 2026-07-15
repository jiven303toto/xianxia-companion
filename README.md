# 🚀 Xianxia Companion 部署

## 1. ✅ 准备

- Python 3.10+
- Telegram API ID / API Hash
- 目标会话 ID：`TG_GAME_BOUND_CHAT_ID`
- 目标 bot 数字 ID：`TG_GAME_BOUND_BOT_ID`
- 如果目标群启用 topic，再准备 `TG_GAME_BOUND_THREAD_ID`

进入仓库目录：

```powershell
cd <你的仓库目录>
```

## 2. ⚙️ 初始化

Windows：

```powershell
python tools/setup_environment.py --install
notepad .env
```

macOS / Linux：

```bash
python3 tools/setup_environment.py --install
nano .env
```

## 3. 📝 填写 `.env`

必填：

```dotenv
TELEGRAM_API_ID=
TELEGRAM_API_HASH=
TG_GAME_BOUND_CHAT_ID=
TG_GAME_BOUND_BOT_ID=


```

按需填写：

```dotenv

TG_GAME_HOST= 127.0.0.1
# 示例端口；可改成任意未占用端口
TG_GAME_PORT= 8787

# --- 管理员（建议填上） ---
AUTHORIZED_USER_ID= 

TG_GAME_BOUND_THREAD_ID=
TG_GAME_ALLOWED_BOT_IDS=

TG_GAME_DOMAIN=
TG_GAME_SSL_CERTFILE=
TG_GAME_SSL_KEYFILE=
```


检查配置：

```powershell
python tools/setup_environment.py --check --strict
```

## 4. ▶️ 启动

Windows：

```powershell
.venv\Scripts\python.exe run_services.py all
```

macOS / Linux：

```bash
.venv/bin/python run_services.py all
```

首次启动 Telegram runtime 时，按终端提示输入手机号、验证码和二步验证密码。

打开，端口按 `TG_GAME_PORT` 替换：

```text
http://127.0.0.1:8787
```

## 5. 🔎 验证

访问，端口按 `TG_GAME_PORT` 替换：

```text
http://127.0.0.1:8787/health
```

确认返回 `status=ok`。如果 `telegram_code_current=false`，重启 Telegram runtime。

## 6. 🔄 更新已部署实例

以下命令在已经完成初始化的部署机器上执行：

Windows：

```powershell
git pull
python tools/setup_environment.py --install
python tools/setup_environment.py --check --strict
.venv\Scripts\python.exe run_services.py all
```

macOS / Linux：

```bash
git pull
python3 tools/setup_environment.py --install
python3 tools/setup_environment.py --check --strict
.venv/bin/python run_services.py all
```
