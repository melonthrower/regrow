# 根目录开发迁移（2026-10-25）

活动源码从 `artifacts/tmp_tests/function_state_20261025_01/implementation/` 迁入 GUI-ReWalk 根目录：`src/regrow/`、必需 `tools/`、`tests/`、当前设计与开发记录。源码内容未改。在本机先激活 `guiwalk-android` 环境（验证解释器为 `/data/shenghonghui/miniconda3/envs/guiwalk-android/bin/python`）。正常入口为 `python src step ...`、`python tools/run_stepwise.py ...`，Prompt 工作台仍使用原数据目录及端口。

迁移前根目录与活动树属于不同 Git 仓库，分别为 GUI-ReWalk-mobile 的2359a2f与regrow的4400deb。两侧已有大量未提交修改；未移动.git、未混合Git历史、未推送。迁入的未验收候选保留原状态，不能用迁移验证替代行为验收。

同名不同内容的工具/测试/当前文档先逐文件备份，再以活动版本作为当前。根目录原有采集代码、独立管线合同及旧experiments保留；历史运行、截图、冻结源码、工作台草稿与历史不改写。旧checkout保留并标记非维护入口，不能按临时缓存删除。依赖链接未递归复制。

证据：`artifacts/runs/root_migration_20261025_01/`，含两侧Git状态、文件迁移清单、root-before冲突备份、操作脚本和验证日志。根入口help、根导入与真实0154完整上下文的原生无模型预览通过（0HTTP/0GUI）；不声称全框架或新的模型行为验收。

本批不提交迁入的已有未提交候选，也不将其作为批准源同步远端。需要后续按已有候选各自验证状态整合，当前目录已经唯一，不再在旧树交替编辑。

## 2026-10-29 Git收尾
用户授权把当前根目录框架建立为Git基线。本次纳入src及其必要运行资源、启动/Prompt调试/看板入口，补充旧全局忽略规则漏掉的__main__.py、JSON和HTML。测试与可选工具保留本地，不新增到本批；既有跟踪文件、旧Git历史和真实运行证据均保留。
验证只检查待提交文件在独立检出中的入口、导入、资源与模型请求构造，不启动GUI、不调用模型、不等同全框架功能验收。已知登记质量问题见CURRENT_FRAMEWORK及对应实验报告。根仓库保留自身历史；经既有授权另同步必要源码到私有regrow仓库，不force-push、不推送到原GUI-ReWalk-mobile的origin。具体提交与导出锚点见本批交付。
