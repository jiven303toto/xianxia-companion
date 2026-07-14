from tg_game.models import FeatureModule


MODULE = FeatureModule(
    key="other",
    name="其他玩法",
    summary="集中放琉璃古塔、野外历练与自动任务，低频玩法可按需展开。",
    status="active",
    capabilities=[
        "常用杂项玩法快捷入口",
        "古塔进度展示",
        "赌运与对赌命令面板",
        "历史消息样例参考",
    ],
    next_steps=[
        "补各玩法真实帮助回包",
        "补更多胜负统计",
        "补自动刷新与玩法冷却提示",
    ],
)
