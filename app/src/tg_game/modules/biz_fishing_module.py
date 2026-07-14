from tg_game.models import FeatureModule


MODULE = FeatureModule(
    key="fishing",
    name="灵溪垂钓",
    summary="管理钓鱼状态、鱼饵鱼获和 MiniApp 自动垂钓。",
    status="active",
    capabilities=[
        "鱼篓与今日竿数状态",
        "MiniApp 试钓、钓满今日和每日自动垂钓",
        "所选鱼饵不足时自动补足",
        "钓鱼、试探、提竿、收竿快捷指令",
        "鱼饵、窝料和鱼获概览",
    ],
    next_steps=[
        "补鱼塘和鱼饵收益统计",
    ],
)
