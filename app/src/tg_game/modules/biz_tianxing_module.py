from tg_game.models import FeatureModule


MODULE = FeatureModule(
    key="tianxing",
    name="天星宗",
    summary="按 profile 隔离记录命星、推命、改命、时间线和下游玩法放行状态。",
    status="active",
    capabilities=[
        "天机盘、观命、定命、推命、改命、消劫回包解析",
        "profile 级回复归属与审计",
        "时间线 dry-run 与 ack 超时校准",
        "探索、炼制、闭关路线 gate",
    ],
    next_steps=[
        "把探索、炼制、闭关实际 scheduler 接到天星宗 gate",
        "在 profile 页面展示天星宗运行快照",
    ],
)
