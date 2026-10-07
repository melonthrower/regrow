# 单文件离线交付

`build_offline.py` 复用现有讲稿、动画、进度网页。把 CSS、JS 和原 PNG 字节内嵌；静态与动态图片引用都改为内嵌资源。进度依据与素材清单也内嵌。保留内容及证据边界，没有新增实验或修改框架。

执行：`python3 build_offline.py FULL_SITE_DIST NEW_OUTPUT_DIRECTORY`。完整站点含14张PNG；本源码导出不含研究截图，应从已授权完整Site或归档交付中取输入。构建拒绝缺图与覆盖旧成品；输出 manifest 记录原图SHA256、文件大小，单文件不超过12 MB。

输出：`regrow-slides-offline.html`（15页讲稿）、`regrow-film-offline.html`（15幕动画）、`regrow-progress-offline.html`（进度与对比）。每份内容可独立打开；跨版本导航需要三文件放同目录。原论文/官方素材外链离线不可访问，但不参与画面加载。

飞书：将需要的HTML直接拖入云文档，选择预览视图；无需上传assets目录。官方说明支持HTML预览且上限12 MB，部分风险功能可能受限。如交互受限，下载后浏览器打开。未实际登录飞书验证。
https://www.feishu.cn/hc/zh-CN/articles/052565607602-在飞书中查看-html-文件

本批验证：Chromium断网file://打开；15页、全部图片、4步动态切换、放大图、15幕动画及播放暂停、进度详情及内嵌来源；零HTTP(S)请求与JS错误。与原图SHA256一致，未修改截图内容。历史首次构建漏了collection模板与intro/compare图片路径，经独立审阅与运行失败定位后补齐；今后必须遍历所有动态画面验证，不仅检查图片表。
