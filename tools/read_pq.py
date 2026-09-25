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


# 备份文件（如果需要）

file_path = f""

# 读取parquet文件
df = pd.read_parquet(file_path)
row_index = 7
# 显示修改前的值
print(f"修改前 - 行 {row_index}:")
if row_index < len(df):
    print(f"Summary: '{df.loc[row_index, 'summary']}'")
    print(f"Task: '{df.loc[row_index, 'task']}'")
else:
    print(f"错误: 行索引 {row_index} 超出范围，文件只有 {len(df)} 行")


# 修改指定行的字段
new_summary = ""
new_task = ""
df.loc[row_index, 'summary'] = new_summary
df.loc[row_index, 'task'] = new_task

# 保存修改后的文件
df.to_parquet(file_path)

print(f"\n修改后 - 行 {row_index}:")
print(f"Summary: '{df.loc[row_index, 'summary']}'")
print(f"Task: '{df.loc[row_index, 'task']}'")
print(f"\n文件已成功更新: {file_path}")