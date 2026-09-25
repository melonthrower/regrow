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

import pandas as pd
import numpy as np
from PIL import Image
from io import BytesIO
import matplotlib.pyplot as plt
import math

# 读取 parquet
df = pd.read_parquet("")
image_column = 'images_after'
num_images = len(df)

# 正方形布局
cols = math.ceil(math.sqrt(num_images))
rows = math.ceil(num_images / cols)

fig, axs = plt.subplots(rows, cols, figsize=(cols * 3, rows * 3))
axs = np.array(axs).reshape(rows, cols)

for i in range(rows * cols):
    row, col = divmod(i, cols)
    ax = axs[row, col]
    if i < num_images:
        try:
            image_bytes = df[image_column].iloc[i]
            if isinstance(image_bytes, (list, np.ndarray)):
                img_data = image_bytes[0]
            else:
                img_data = image_bytes
            image = Image.open(BytesIO(img_data))
            ax.imshow(image)
            ax.axis('off')
        except Exception as e:
            print(f"无法显示第{i}张图片: {e}")
            ax.set_title("Error")
            ax.axis('off')
    else:
        ax.axis('off')

plt.tight_layout()
plt.savefig("")
plt.show()

