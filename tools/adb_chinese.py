# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import uiautomator2 as u2
import logging

# 1. 配置日志输出，打印 uiautomator2 调用的 ADB 命令
logging.basicConfig(level=logging.DEBUG)  # 打印所有 DEBUG 及以上级别日志
# 如果只想看与 ADB 相关的，可以这样单独设置：
adb_logger = logging.getLogger("uiautomator2.adb")
adb_logger.setLevel(logging.DEBUG)

# 2. 连接设备（替换为你的设备 IP 或 USB 序列号）
d = u2.connect()

# 3. 切换到 fastinput_ime，用来支持 unicode 文本输入
#    第一次使用需要安装服务，会自动在设备上安装 uiautomator2 fastinput apk
# d.set_fastinput_ime(True)

# 4. 输入中文文本
d.send_keys("你好，世界！")

# 5. （可选）恢复原输入法
# d.set_fastinput_ime(False)