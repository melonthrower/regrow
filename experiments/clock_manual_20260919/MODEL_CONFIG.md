默认模型改为gpt-6-luna。实验调用脚本和新建run清单统一读取本机explore_api.model。reasoning仍为medium。旧请求/回复不改；38个模板/续跑调用脚本原内容已备份，后续调用使用新配置。本次只做保存帧调用，不启动GUI遍历。
验证：独立读者检查38项迁移及异cwd启动配置通过；一次实际保存帧调用HTTP 200，响应model=gpt-6-luna，schema通过，GUI为0。旧模型质量结论不自动适用于新模型。
