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

import matplotlib.pyplot as plt
import numpy as np
# 数据
labels = [
    "Browser/Search",
    "Communication/Information",
    "Developer Tools",
    "Office/Productivity",
    "Shopping/Life",
    "Multimedia",
    "System/Basic Functions"
]
sizes = [
    13.04347826,
    8.695652174,
    4.347826087,
    26.08695652,
    13.04347826,
    8.695652174,
    26.08695652
]

# 使用科研常见配色
# colors = plt.cm.tab20c.colors[:len(labels)]
# colors = [
#     "#DBE8C5",
#     "#DFEBCB",
#     "#D1EFEB",
#     "#E1D7F1",
#     "#F4DEE0",
#     "#F7E4E6",
#     "#F9EBED"
# ]
def rgb(r, g, b):
    return (r/255, g/255, b/255)
colors = [
    rgb(38, 70, 83),    
    rgb(40, 114, 113),  
    rgb(41, 157, 144), 
    rgb(138, 176, 125),  
    rgb(232, 197, 107),  
    rgb(243, 162, 97), 
    rgb(230, 111, 81)   
]

# 设置全局字体为 Comic Sans MS
plt.rcParams['font.family'] = 'Comic Sans MS'

fig, ax = plt.subplots(figsize=(7, 3))
wedges, texts = ax.pie(
    sizes,
    # autopct='%1.1f%%',
    startangle=90,
    # textprops={'fontsize': 12},
    wedgeprops={'edgecolor': 'white', 'linewidth': 1},
    colors=colors,
    # pctdistance=1.1
)

# 添加折线和标签
for i, wedge in enumerate(wedges):
    # 计算角度
    angle = (wedge.theta2 + wedge.theta1) / 2
    x = np.cos(np.deg2rad(angle))
    y = np.sin(np.deg2rad(angle))

    # 起点（饼图外缘）
    line_x = 1.05 * x
    line_y = 1.05 * y

    # 折点（往外伸长）
    mid_x = 1.2 * x
    mid_y = 1.2 * y

    # 水平终点
    if x >= 0:  # 右侧
        end_x = mid_x + 0.4
        ha = "left"
        text_x = mid_x + 0.2   # 文本往右挪
    else:       # 左侧
        end_x = mid_x - 0.4
        ha = "right"
        text_x = mid_x - 0.2   # 文本往左挪
    end_y = mid_y

    # 画折线
    ax.plot([line_x, mid_x, end_x], [line_y, mid_y, end_y], color="black", lw=1)

    # 数字始终在折线上方
    ax.text(text_x, mid_y + 0.01, f"{sizes[i]:.1f}%", 
            ha="center", va="bottom", fontsize=11)
# 图例替代标签
ax.legend(
    wedges,
    labels,
    title="Categories",
    loc="center left",
    bbox_to_anchor=(1, 0, 0.5, 1),
    fontsize=11
)

# 标题
# ax.set_title("App Categories Distribution", fontsize=14, pad=20)
ax.axis('equal')  # 保证饼图是圆的

plt.tight_layout()

plt.savefig('application_usage_pie_chart.png', bbox_inches='tight', dpi=600)
plt.savefig('application_usage_pie_chart.pdf', bbox_inches='tight')  # PDF是矢量图，不需要设置DPI
plt.show()
