# 按需 Android Seed

这里是移动端按需 seed 的唯一入口。它不使用历史全量 v2 snapshot：每次运行从显式的 clean base 开始，只写目标应用及其必要 shared 对象。

用途只有三类：遍历前扩展某一应用的可探索状态；中断后由 run-owned checkpoint 恢复同一 SeedPlan 状态；采集时由 capability authority 的 `seed_objects` 和 typed `scenario_delta` 准确准备实机状态。

运行边界：原始指令不能选择 seed 对象；没有 authority 的资源前置条件会失败；SeedPlan 固化对象、时间和 digest；seed/readback 写进 `environment/` provenance，不进入探索动作、能力证据或训练轨迹。

入口：`tools/guitraverse_seed/live_android_probe.py` 只 attach 到已经运行的任务专属 emulator，不启动模型或 emulator。传入 manifest、clean base、ADB/console/gRPC 端口、报告路径，以及可选 `--app`。正式 traversal/collection 由 `gui_rewalk/run_visual_traversal.py` 和 `gui_rewalk/run_visual_collection.py` 在首个应用 launch 前调用同一 `apply_seed_plan`。

媒体和 FTS 依赖：需要预先提供 `GUITRAVERSE_SHARED_MEDIA_ASSET_ROOT`、`GUITRAVERSE_AUDIO_RECORDER_ASSET_ROOT`、`GUITRAVERSE_DB_TEMPLATE_ROOT`，并把 `GUITRAVERSE_FTS_SQLITE_PYTHON` 指向支持 FTS3/4 的 Python。MP3 资产复制后会仅重写 plan 声明的 ID3 标题/艺术家，不修改原资产。
