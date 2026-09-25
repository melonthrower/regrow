# import matplotlib.pyplot as plt

# # 数据
# strides = [1, 2, 3, 4]
# tokens = [300_000, 800_000, 1_300_000, 1_900_000]
# costs = [0.042, 0.105, 0.3024, 0.616]

# plt.rcParams['font.family'] = 'Comic Sans MS'

# fig, ax1 = plt.subplots(figsize=(7, 5))

# # 左 y 轴：tokens
# ax1.plot(strides, tokens, marker='o', color='#EE756E', label="Tokens Consumed")
# ax1.set_xlabel("Stride")
# ax1.set_ylabel("Tokens (count)", color='#EE756E')
# ax1.tick_params(axis='y', labelcolor='#EE756E')
# ax1.set_xticks(strides)  # 只显示 1,2,3,4

# # 在每个点上标出 token 数字（折线上方）
# for x, y in zip(strides, tokens):
#     ax1.text(x, y + 50000, f"{y//1000}k", ha="center", va="bottom", color="#EE756E", fontsize=10)

# # 第二个 y 轴：cost
# ax2 = ax1.twinx()
# ax2.plot(strides, costs, marker='s', color='#25B7BE', label="Cost ($)")
# ax2.set_ylabel("Cost ($)", color='#25B7BE')
# ax2.tick_params(axis='y', labelcolor='#EE756E')

# # 在每个点上标出 cost 数字（折线下方）
# for x, y in zip(strides, costs):
#     ax2.text(x, y - 0.01, f"${y:.3f}", ha="center", va="top", color="#25B7BE", fontsize=10)

# # 图例
# lines, labels = ax1.get_legend_handles_labels()
# lines2, labels2 = ax2.get_legend_handles_labels()
# ax1.legend(lines + lines2, labels + labels2, loc="upper left")

# # plt.title("Tokens and Cost vs Stride", fontsize=14, pad=15)
# plt.tight_layout()
# plt.show()
import matplotlib.pyplot as plt

# 数据
strides = [1, 2, 3, 4]
tokens = [300_000, 800_000, 1_300_000, 1_900_000]
costs  = [0.042, 0.105, 0.3024, 0.616]

fig, ax_tokens = plt.subplots(figsize=(7, 5))

# --- 左轴：Tokens ---
token_color = '#EE756E'  # 粉红色
ln1 = ax_tokens.plot(
    strides, tokens,
    marker='o', color=token_color, linestyle='--',
    label="Tokens"
)
ax_tokens.set_xlabel("Stride")
ax_tokens.set_ylabel("Tokens (count)")
# ax_tokens.tick_params(axis='y', colors=token_color)  # 坐标轴刻度颜色
ax_tokens.set_xticks(strides)

# 把 token 轴上界放大，让曲线只占图的下~45%
max_token = max(tokens)
ax_tokens.set_ylim(0, max_token / 0.45)

# token 数字：点上方
for x, y in zip(strides, tokens):
    ax_tokens.annotate(f"{y//1000}k", xy=(x, y), xytext=(0, 8),
                       textcoords="offset points", ha="center", va="bottom",
                       color=token_color)

# --- 右轴：Cost ---
cost_color = '#25B7BE'  # 青色
ax_cost = ax_tokens.twinx()
ln2 = ax_cost.plot(
    strides, costs,
    marker='s', color=cost_color, linestyle='-',
    label="Cost ($)", zorder=3
)
ax_cost.set_ylabel("Cost ($)")
# ax_cost.tick_params(axis='y', colors=cost_color)  # 坐标轴刻度颜色
ax_cost.margins(y=0.1)

# cost 数字：点下方
for x, y in zip(strides, costs):
    ax_cost.annotate(f"${y:.3f}", xy=(x, y), xytext=(0, -8),
                     textcoords="offset points", ha="center", va="top",
                     color=cost_color)

# 合并图例
lines = ln1 + ln2
labels = [l.get_label() for l in lines]
ax_tokens.legend(lines, labels, loc="upper left")

# plt.title("Tokens and Cost vs Stride")
plt.tight_layout()
plt.savefig('strides_analysis.png', dpi=300, bbox_inches='tight')
plt.savefig('strides_analysis.pdf', bbox_inches='tight')
plt.show()
