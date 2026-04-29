# 边缘检测方案（透视四边形检测）

本文档描述本项目在 **透视校正** 中用于“找纸张/单据四边形”的边缘检测与轮廓近似算法实现（当前实现位于 `src/delivery_vlm/preprocess/perspective_rectify.py` 的 `rectify_largest_quad_to_rectangle()`）。

## 目标

给定一张包含单据/纸张的图片，检测其外轮廓对应的 **凸四边形**（4 个角点），并将该四边形透视拉正到固定画布（默认 `800x1100`）。

## 总流程（步骤）

### 1) 灰度化

- 输入：BGR 彩色图 `img_bgr`
- 输出：灰度图 `gray`

### 2) 高斯模糊（降噪）

目的：降低噪声对边缘的干扰，让 Canny 的边缘更连续、稳定。

- `blurred = GaussianBlur(gray, ksize=(5,5), sigma=0)`

### 3) Canny 边缘检测（低阈值，高灵敏度）

目的：得到“边缘二值图” `edges`，让纸张/单据边界尽量显著。

当前项目的阈值（已多次降低以提高召回）：

- `edges = Canny(blurred, threshold1=20, threshold2=60)`

说明：

- `threshold1`：低阈值（更低 → 更灵敏，噪声也会变多）
- `threshold2`：高阈值（更低 → 更容易形成强边缘）

### 4) 膨胀（连接断裂边缘）

目的：把边缘中的断点连接起来，提高“闭合轮廓”形成概率。

- 结构元：`3x3` 矩形核
- 迭代次数：`2`

即：

- `edges = dilate(edges, kernel=rect(3,3), iterations=2)`

### 5) 轮廓提取（仅外轮廓）

目的：获取图中候选四边形轮廓。

- `findContours(edges, RETR_EXTERNAL, CHAIN_APPROX_SIMPLE)`

说明：

- `RETR_EXTERNAL`：只取最外层轮廓（更符合“纸张外框”的期望；也降低误检内部表格线的概率）
- `CHAIN_APPROX_SIMPLE`：压缩轮廓点

### 6) 轮廓筛选（面积优先）

将轮廓按面积从大到小排序，仅遍历前若干个（默认最多 80 个）：

- `cnts = sorted(cnts, key=contourArea, reverse=True)[:80]`

并施加最小面积占比约束（来自配置 `min_area_ratio`）：

- `contourArea(cnt) >= min_area_ratio * image_area`

### 7) 多 epsilon 近似多边形（approxPolyDP）

对每个候选轮廓，计算其周长 `peri = arcLength(cnt, closed=True)`，然后按一组 epsilon 比例尝试近似：

- `approx = approxPolyDP(cnt, epsilon_ratio * peri, closed=True)`

若满足：

- `len(approx) == 4`
- `isContourConvex(approx) == True`

则认为找到候选四边形，停止搜索。

> 备注：多 epsilon 比“只试一个 epsilon”更容易把轮廓近似到 4 个角点，从而提升召回率。

### 8) 四点排序（TL/TR/BR/BL）

目的：确保透视变换点对应关系正确，避免“点顺序错导致拉正翻转/扭曲”。

使用 `order_quad_points()` 将四点排序为：

- 左上 (TL)、右上 (TR)、右下 (BR)、左下 (BL)

### 9) 计算单应性并透视拉正（warpPerspective）

将排序后的四边形 `src_pts` 映射到固定画布 `dst_pts`：

- 目标画布：`dst_w=800, dst_h=1100`
- `dst_pts = [[0,0],[dst_w-1,0],[dst_w-1,dst_h-1],[0,dst_h-1]]`

计算透视矩阵并变换：

- `M = getPerspectiveTransform(src_pts, dst_pts)`
- `corrected = warpPerspective(img_bgr, M, (dst_w, dst_h))`

输出：

- `corrected`：透视拉正后的固定尺寸图
- `meta`：包含 `quad_xy`（四边形点）、`quad_area_ratio`、`dst_doc_wh` 等

## 关键参数（当前默认）

- **Blur**：`GaussianBlur(5x5)`
- **Canny**：`(20, 60)`（已偏“高灵敏度”）
- **Dilate**：kernel `3x3`，iterations `2`
- **Contours**：`RETR_EXTERNAL`
- **approxPolyDP**：逐个尝试 `epsilon_ratios`（来自配置，默认 `(0.02, 0.03, 0.045, 0.06)`）
- **最小面积占比**：`min_area_ratio`（来自配置，示例中常用 `0.06`）
- **输出画布**：`800x1100`（固定）

## 调参建议（常见现象 → 调法）

### A. 召回不足：经常“找不到四边形”

- **降低 Canny 阈值**：例如从 `(20,60)` 继续降到 `(15,45)` 或 `(10,30)`
- **增加膨胀迭代**：`2 → 3`（注意会增加误检）
- **降低 `min_area_ratio`**：例如 `0.06 → 0.03`（小纸张/远拍更容易命中）
- **增大轮廓遍历上限**：例如 `[:80] → [:150]`（更多候选，但更慢）

### B. 误检增加：框到背景/桌面/阴影边

- **提高 `min_area_ratio`**（更偏向大纸张）
- **提高 Canny 阈值**（减少噪声边缘）
- **减少膨胀迭代**（防止边缘“长”到一起）

### C. 透视变换后图像翻转/扭曲

- 检查 **四点排序** 是否正确（必须 TL/TR/BR/BL）
- 若纸张不是凸四边形（被遮挡/折叠），可能会出现近似点错误

## 与“仅 OCR”方案的关系

该边缘检测与透视校正是纯几何处理，用于让单据更接近“扫描件”效果；方向纠正（PULC）在几何之前完成（当前项目顺序为：方向转正 → 透视 → deskew）。

