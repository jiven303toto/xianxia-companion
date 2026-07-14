MINIAPP_SAFETY_BOUNDARY = (
    "只读同步会临时请求 Telegram WebView 和 xianxia-dwelling/start；"
    "未执行升级/寻宝/布置/宝阁等消耗动作；不保存 initData/tgWebAppData/hash/user/raw URL。"
)
MINIAPP_HUNT_SAFETY_BOUNDARY = (
    "自动寻宝会临时请求一次 Telegram WebView，并在同一洞府 MiniApp 会话内连续寻宝；"
    "默认每轮耗尽神识后结算，达到今日次数上限后停止；"
    "不保存 initData/tgWebAppData/hash/user/raw URL/sessionId。"
)
ESTATE_MINIAPP_DEFAULT_BOT_USERNAME = "fanrenxiuxian_bot"
ESTATE_MINIAPP_PUBLIC_ENTRY_CHANNEL = -1002083016447
ESTATE_MINIAPP_PUBLIC_ENTRY_STATE_KEY = "estate_public_entry_discovery"
ESTATE_MINIAPP_DEFAULT_API_BASE_URL = "https://asc.aiopenai.app"
ESTATE_MINIAPP_WEB_PATH = "/miniapp/xianxia-dwelling"
ESTATE_MINIAPP_API_PATH_PREFIX = "/api/miniapp/xianxia-dwelling/"
ESTATE_MINIAPP_ENDPOINTS = {
    "start": f"{ESTATE_MINIAPP_API_PATH_PREFIX}start",
    "hunt": f"{ESTATE_MINIAPP_API_PATH_PREFIX}hunt",
    "hunt_reveal": f"{ESTATE_MINIAPP_API_PATH_PREFIX}hunt/reveal",
    "hunt_settle": f"{ESTATE_MINIAPP_API_PATH_PREFIX}hunt/settle",
}
ESTATE_MINIAPP_ALLOWED_WEB_HOSTS = {"t.me", "telegram.me", "asc.aiopenai.app"}
ESTATE_MINIAPP_ALLOWED_API_HOSTS = {"asc.aiopenai.app"}
