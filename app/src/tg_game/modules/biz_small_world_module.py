from tg_game.models import FeatureModule


MODULE = FeatureModule(
    key="small_world",
    name="小世界",
    summary="查看化神后的小世界状态，并提供香火、显灵、神庙和灵兽寄养的手动指令入口。",
    status="active",
    capabilities=[
        "小世界面板状态解析",
        "香火、显灵和神庙快捷指令",
        "灵兽寄养与召回手动入口",
    ],
    next_steps=[
        "观察不同祈愿类型的消耗和结果",
        "确认安全阈值后再考虑自动收割香火",
        "确认白名单后再考虑自动显灵",
    ],
)
