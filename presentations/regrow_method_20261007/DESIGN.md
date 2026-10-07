# regrow 方法动画设计

用户目标：给老师演示论文方法，包含遍历、任务生成和轨迹采集；从静态PPT式网页改为视频式效果，允许不同网上界面素材说明每个处理环节，不要求实机过程。

已实现：180秒、15幕无声字幕动画；以GNOME官方6张素材覆盖文件、设置、日历；逐步区域标注、光标移动、卡片出现、知识关系线、章节导航、播放暂停、拖动、倍速和全屏。默认首页为动画；原静态讲稿保留在slides.html。

镜头主线：当前前景→Region→控件外观与操作区域→三类信息需求→一次动作→产物登记→经验复用→完整目的归纳→冻结知识→目标驱动生成→条件分支→实时采集→结果核验→研究主线。第一幕为总览，共15幕，每幕12秒、三段字幕。

素材明确标为方法示意，非模型输出/非连续操作证据。设置两图为独立官方素材；日历事件显示不证明保存成功，验收幕使用未勾选清单。源图、图标和业务参数由素材提供，框线和卡片为独立讲解层。没有改动研究框架或其验收结论。

参考限制：OpenAI页面文本可读取，浏览器视频受校验；小红书返回IP安全限制。未观看完整参考片，不宣称复刻转场或节奏。

文件职责：dist/index.html为播放器外壳；film/scenes.js定义唯一时间轴内容与原图坐标；film/player.js负责确定性时间驱动、标注和交互；film/film.css负责舞台与缩放；film/assets/sources.json保留官方来源、许可声明和哈希。行号与导出提交固定在外部CHANGE_MAP.md。

验证边界：浏览器功能和素材语义检查；没有新的Luna调用或真实GUI。手机竖屏只是缩放视频，建议桌面/横屏。配音、独立MP4和参考视频精确复刻不在已实现范围。

## 实验进度页增量

参考用户所给绿色进度表，新增progress.html/progress.css/progress.js，保持顶部目标摘要、工作行、三类阶段状态和可展开依据；下方保留此前讨论的E1–E4及近期里程碑。资料依据来自10月6日周报与历史真实试点；无统一完成数量时不填写半数、50%或加权总进度。progress-sources.html单独说明来源与分母。index.html仅增加导航链接，动画不变。页面呈现改动，不修改研究目标、框架、源图和运行状态。

Dataset comparison: three version-pinned primary papers; linear count axis 0–16,000. Published counts are solid; regrow 3,000 is fully hatched as a target with completion unknown, not zero or half. Average steps use paper-specific definitions. Print separates the status page and scale/plan page.
