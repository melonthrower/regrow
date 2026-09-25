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

import cv2
import numpy as np
from typing import Tuple


def preprocess_image(image_path: str, target_size: Tuple[int, int] = (256, 256)) -> np.ndarray:
    """
    图像预处理：读取图像、统一尺寸、转换为灰度图并归一化
    :param image_path: 图像文件路径（支持jpg、png等常见格式）
    :param target_size: 统一后的图像尺寸 (宽度, 高度)
    :return: 预处理后的灰度图（ndarray， dtype=float32，值范围[0,1]）
    """
    # 读取图像（cv2.IMREAD_COLOR 读取为BGR格式）
    img = cv2.imread(image_path)
    if img is None:
        raise FileNotFoundError(f"无法读取图像文件：{image_path}，请检查路径是否正确")
    
    # 统一图像尺寸（使用双线性插值，兼顾速度和质量）
    img_resized = cv2.resize(img, target_size, interpolation=cv2.INTER_LINEAR)
    
    # 转换为灰度图（BGR转灰度）
    img_gray = cv2.cvtColor(img_resized, cv2.COLOR_BGR2GRAY)
    
    # 归一化到[0,1]范围（避免像素值过大导致计算误差）
    img_normalized = img_gray.astype(np.float32) / 255.0
    
    return img_normalized


def calculate_ssim(img1: np.ndarray, img2: np.ndarray, window_size: int = 11, sigma: float = 1.5) -> float:
    """
    计算两张灰度图的结构相似性指数（SSIM）
    参考公式：SSIM = (2μ₁μ₂ + C₁) * (2σ₁₂ + C₂) / [(μ₁² + μ₂² + C₁) * (σ₁² + σ₂² + C₂)]
    其中：μ为均值，σ为标准差，σ₁₂为协方差，C₁/C₂为稳定常数（避免分母为0）
    
    :param img1: 第一张预处理后的灰度图（ndarray， dtype=float32，值范围[0,1]）
    :param img2: 第二张预处理后的灰度图（与img1尺寸完全一致）
    :param window_size: 局部窗口大小（需为奇数，推荐11）
    :param sigma: 高斯滤波标准差（控制窗口权重分布，推荐1.5）
    :return: SSIM分数（范围[-1,1]，1表示完全相同，<0表示差异极大）
    """
    # 检查输入图像尺寸一致性
    if img1.shape != img2.shape:
        raise ValueError(f"两张图像尺寸不一致：img1={img1.shape}，img2={img2.shape}，请确保预处理后尺寸相同")
    
    # 检查窗口大小合法性
    if window_size % 2 == 0:
        raise ValueError(f"窗口大小必须为奇数，当前输入：{window_size}")
    
    # 1. 计算高斯窗口权重（模拟人类视觉的局部感知特性）
    # 生成1D高斯核
    gauss_1d = cv2.getGaussianKernel(window_size, sigma)
    # 转换为2D高斯窗口（外积操作）
    gauss_window = np.outer(gauss_1d, gauss_1d)
    
    # 2. 定义稳定常数（避免分母为0，根据图像归一化范围[0,1]设置）
    C1 = (0.01) ** 2  # 对应像素值范围[0,1]的小常数
    C2 = (0.03) ** 2  # 对应像素值范围[0,1]的小常数
    
    # 3. 计算局部均值（μ₁、μ₂）：高斯卷积实现
    mu1 = cv2.filter2D(img1, -1, gauss_window, borderType=cv2.BORDER_REFLECT)  # 边界反射填充，避免边缘误差
    mu2 = cv2.filter2D(img2, -1, gauss_window, borderType=cv2.BORDER_REFLECT)
    
    # 4. 计算局部均值的平方（μ₁²、μ₂²、μ₁μ₂）
    mu1_sq = mu1 ** 2
    mu2_sq = mu2 ** 2
    mu1_mu2 = mu1 * mu2
    
    # 5. 计算局部方差和协方差（σ₁²、σ₂²、σ₁₂）
    sigma1_sq = cv2.filter2D(img1 ** 2, -1, gauss_window, borderType=cv2.BORDER_REFLECT) - mu1_sq
    sigma2_sq = cv2.filter2D(img2 ** 2, -1, gauss_window, borderType=cv2.BORDER_REFLECT) - mu2_sq
    sigma12 = cv2.filter2D(img1 * img2, -1, gauss_window, borderType=cv2.BORDER_REFLECT) - mu1_mu2
    
    # 6. 计算SSIM局部值（每个窗口的SSIM）
    ssim_map = ((2 * mu1_mu2 + C1) * (2 * sigma12 + C2)) / ((mu1_sq + mu2_sq + C1) * (sigma1_sq + sigma2_sq + C2))
    
    # 7. 计算全局SSIM分数（所有局部窗口的均值）
    global_ssim = np.mean(ssim_map)
    
    # 确保输出在[-1,1]范围内（数值计算误差修正）
    global_ssim = max(min(global_ssim, 1.0), -1.0)
    
    return global_ssim

def get_image_ssim(image_path1, image_path2, target_size=(1920, 1080), window_size=11, sigma=1.5):
    img1 = preprocess_image(image_path1, target_size)
    img2 = preprocess_image(image_path2, target_size)
    ssim_score = calculate_ssim(img1, img2, window_size, sigma)
    return ssim_score

