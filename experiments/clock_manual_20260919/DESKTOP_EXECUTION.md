# 临时逐步遍历器：OSWorld桌面接入

2026-09-22：复用OSWorld /execute与/screenshot接口，在同一run_progress_session→run_task_step→发现/动作/更新流程内切换平台适配器。原Android路径保留；未改原gui_rewalk遍历内核。

manifest.platform=desktop时加载desktop_transport.DesktopRun。desktop提供controller、launch_command、window_class；root/run账本同Android格式，桌面run放desktop_runs，避免Android应用选择器把桌面端当ADB设备。当前启动证据和现有网页入口见records/217_osworld_settings_20260922。网页沿用progress_window及图视图。

支持原八种动作的桌面映射：点击、双击、长按、替换ASCII文本、滚轮、Esc、等待、不投递。坐标为整屏。back仅Esc，不表示任意页面返回；滚动端点表达方向幅度，不拖控件。不扩展hover/任意热键/Unicode输入。输入沿用先聚焦、视觉核对、Ctrl+A、替换及原回执；每个底层命令扣GUI预算，OSWorld非零退出不算成功，投递不自动重试。

截图和X11活动窗口归属用于结果核对；窗口记录不是像素/业务效果证明。异常重启只针对manifest声明的目标应用，不重启VM。平台prompt由transport附加并保存，恢复动态平台由Android改为桌面；公共Android说明改为条件说明。系统设置目标内部设置不因设备级语义自动排除，但关闭远程会话、网络、系统或账号凭据更改仅记录，保护实验现场。

离线30项聚焦测试通过，覆盖桌面命令/非零退出/平台prompt/执行记账与原Android输入恢复，日志artifacts/tmp_tests/desktop_stepwise_20260922/green2.log。初版测试导入路径问题在测试夹具中修正，失败日志保留。四模块语法检查通过。实跑使用217冻结源，现有OSWorld5007，未清理旧窗口、未重置系统设置；是否完成模型动作闭环见运行结果，不能仅凭本页宣称已全应用通过。

实机首段：217的a0001点击搜索图标后搜索框出现，0005更新成功；随后a0002/a0003也已结算，自动继续。首次窗口归属读取因VM无xdotool返回未知（未伪称归属）；当前源码改为xprop读取，独立只读实机探针已得到Settings WM_CLASS并确认匹配。运行中冻结源未热替换，当前段仍保留未知窗口证据，下一段使用修正。修改后仍30项聚焦测试通过，final.log。

2026-09-22 续跑与任务展示：progress把任务reason原文作为purpose展示“探索目的与完成条件”，与受阻原因分开；不生成或补写结束条件。run_manifest.session_limits可为当前run指定每段max_http/max_gui_commands/max_rounds，缺省仍30/30/20；每轮预留6的预算保护不变，预算不进Luna prompt。Settings续段218设120/120/80，保留原图与217冻结证据，新冻结源含xprop修正。14项progress及details测试通过（artifacts/tmp_tests/settings_continue_20260922/green.log）；网页API已读取真实reason。首次续跑截图接口返回非PNG，在GUI投递前停止（1 HTTP、0 GUI）；随后独立读取PNG正常，保留失败并重新开始，最终结果以session账本为准。

2026-09-22 总探索进度：网页复用graph.json中各区块progress.complete，显示已完成/已发现区块；新增区块会增加分母，当前区块任务进度保留。没有改完成判定或遍历流程。修正网页仍写死30次预算的旧文案。14项progress/details检查与浏览器脚本语法通过，实机HTTP读取并验证计数见records/219_region_progress_20260922。仅替换218服务读取的HTML，修改前后副本存219；未热改执行源码或重启运行。

2026-09-22 更新步来源绑定：动作后更新schema删除exploration_update.entry_name，登记与诊断不再用模型重复声明的名称反查来源。来源仍由实际edge/binding/dispatch确定，保留绑定一致性和来源观察校验。task_result.name仍为探索任务名，prompt明确任务名与控件名不同。仅改临时框架维护源，未热改218冻结执行源，未恢复遍历。按用户明确要求未运行测试，仅审阅diff；不宣称运行验证。

2026-09-22 控件候选对齐：target_observation与纠错统一调用visual_choices.prepare，模型位置清单和绑定器visual_choices来自同一次准备；绑定时重查当前帧。控件图片相邻region.png能唯一定位所属区块时，候选必须完全落在该区块内；所属区块不能确认时保留原候选消歧，不宣称归属已验证。旧0022真实截图离线复现后，正确弹窗关闭坐标通过、主窗口关闭坐标拒绝；实际attach输出清单与后台一致。14项visual_choices/progress测试通过，证据artifacts/tmp_tests/close_owner_fix_20260922；没有GUI投递、没有热改冻结源或恢复运行。

2026-09-22 关系调查任务：plan_request接入独立任务/参数关系调查.prompt并复用target_observation.describe披露控件状态、外观与疑问；其他区块明确为历史。以具体互斥/联动线索提出最小parameter任务，单选值合为一个参数，区分观察与已验证效果。陌生读者+2次Luna保存帧验证见records/221_parameter_relations_20260922/REPORT.md；第二次关系任务符合目标，数字输入原值的辨别力仍待改进。16项测试通过；未执行GUI、未发布试验任务到真实图、未热改冻结源。

2026-09-22 任务价值筛选：探索目标以指令设计所需功能、参数或约束增量为依据，替代动作方式本身不自动派任务；同步清理输入任务必选和新方式必查要求。数字显示与减号可record保留未验证边界，业务数量调查由代表任务承担。陌生读者审查后1次Luna保存帧测试得到4 explore/2 record，无纯数字输入任务；16项测试及schema/内存登记通过。证据records/222_task_value_20260922。0GUI，真实图不变，冻结运行源未更新。本轮涉及预存未跟踪prompt，未创建混入用户内容或缺失修改的提交。

## 2026-09-22 截图短暂损坏续跑
OSWorld截图接口收到非PNG或截断PNG时，仅重试读取最多3次，间隔0.3秒；每次失败保存原响应和capture.json，Pillow完整校验后才保存正式帧。GUI动作不重试。服务使用共享截图文件，存在并发读写风险；本次原失败未保存响应体，不能认定已证实根因。
验证：tests/test_stepwise_desktop.py 6项离线通过，含空响应、截断PNG恢复及耗尽三次拒绝；日志artifacts/tmp_tests/screenshot_retry_20260922/green.log。实际续跑首次3HTTP/0GUI在取图中断，修复后自动回溯已执行1GUI并继续模型动作步，详见records/229_settings_continue_20260922；不宣称完整遍历通过。

2026-09-23：共享动作增加 `key_press`，沿用 `text` 字段填写 ENTER/TAB/ESC/BACKSPACE；桌面使用按键投递，Android使用相应keyevent。必须先确认当前焦点；输入可见文字不表示命令已提交。此次只验证保存帧任务生成与适配器命令，没有在真实终端执行命令。

## 2026-09-23：普通动作与导航、恢复共用桌面动作
新增 hover、right_click、drag、hotkey；key_press 支持桌面常见单键（含功能键）。hotkey 的 text 用加号连接按键，drag 使用起终点；输入仍为替换，提交另发 ENTER。Android请求只披露其支持的动作。普通执行与恢复投递前都检查画面/前景，未投递不得登记为已执行。没有应用专属快捷键规则。
