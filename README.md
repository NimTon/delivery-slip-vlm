# delivery-slip-vlm

送货单图像 → VLM 结构化 JSON → 合并导出 Excel。核心入口：`delivery_vlm.pipeline.delivery_run.run_delivery_vlm_to_xlsx`；命令行见 `delivery-vlm`，图形界面见 `delivery_vlm.gui_app`。

## 端到端总流程

1. **加载配置**：`configs/default.yaml`（可用 `--config` 覆盖），并读取环境变量中的 VLM 地址与密钥（见 `delivery_vlm.config.vlm_settings`）。
2. **枚举输入图**：对输入目录递归扫描图片，按相对路径生成 `page_id`。
3. **并发处理每一张图**（`vlm.max_workers`）：每张图独立完成「预处理 → VLM → 解析 → 写页 JSON → 写入 manifest 一行」。多线程时 manifest 仍按页序号顺序流式写入。
4. **汇总**：读取各页 `excel_rows`，按 `delivery` 段配置做合并与列裁剪，写出 `delivery_merged.xlsx`（及可选 jsonl）。

## 单张图片：预处理（`vlm.use_preprocess`）

| `use_preprocess` | 行为 |
|------------------|------|
| `true`（默认） | 读原图 → `preprocess_image` 写出临时 PNG → 后续 VLM 使用该 PNG（或由其解码得到的矩阵）。 |
| `false` | 用 `load_bgr` 仅做读图（含 `preprocess.auto_exif`）；门控开启时直接用该 BGR 编码 PNG 调 VLM；门控关闭时**直接发送原文件字节**（ MIME 按后缀推断），**不缩放、不做色调/透视/deskew**。 |

当 `use_preprocess: true` 时，单图预处理顺序为：

1. **读图**：`load_bgr`；若 `auto_exif: true`，优先按 EXIF 摆正像素。
2. **几何**（`apply_rotate_and_deskew`）：
   - 若启用 **透视**（`preprocess.perspective`）且成功，先得到矫正图；再视配置决定是否做后续步骤。
   - 若 **`preprocess.auto_rotate_ocr.enabled: true`**：用 **PaddleOCR** 对当前图做 0°/90°/180°/270° 四种朝向各跑一次 OCR，取**去空白后字符数最多**的朝向作为正向（需 `pip install paddleocr`）。不可用或未识别到文字时保持原朝向。
   - 若透视已成功应用，则**跳过 deskew** 并结束几何阶段；否则可选 **deskew**（小角度纠偏）。
3. **缩放**：长边限制为 `max_long_edge`（优先 `vlm.max_long_edge`，否则 `preprocess.max_long_edge`）。
4. **色调**：`tone_mode`（如 `shaded` / `raw`）。
5. 写入临时目录下的 PNG。

说明：整页 90° 还可由 **VLM 门控**在开启时按模型建议继续微调；OCR 四向与门控可同时开（先本地 OCR 选向，再送 VLM）。

## 单张图片：VLM 与解析

是否启用门控由 **`vlm.use_vlm_rotation_gate`** 决定（兼容旧键 `orientation_gate`）。**图形界面**在「运行选项」中提供与 yaml 对应的布尔开关，任务运行时会通过 `config_overrides` 覆盖配置文件；命令行可用 `--vlm-rotation` / `--no-vlm-rotation` 覆盖该项。

### A. 门控关闭（`use_vlm_rotation_gate: false`）

1. 调用 **一次** VLM：`vlm_delivery_system` + `vlm_delivery_user`（`configs/prompts/` 下外置文件优先）。
2. 提示词要求模型**只输出业务表格 JSON**，**禁止**输出 `needs_rotation`、`rotate_clockwise_90_steps`、`rotate_degrees`。
3. `parse_delivery_response(..., drop_vlm_orientation_keys=True)`：解析前会去掉上述顶层键，避免误入业务字段。
4. 页级元数据：`vlm_orientation_gate: false`，`orientation_rotate_attempts: 0` 等。

### B. 门控开启（`use_vlm_rotation_gate: true`）

1. 使用 **门控提示词**：`vlm_delivery_gate_system` + `vlm_delivery_gate_user`。
2. 将**当前**图像（BGR）编码为 PNG，调用 VLM；用 `parse_vlm_orientation_gate_response` 判断返回类型：
   - **识别**：JSON 为正常 `lines` / `items`（及可选 `header`）→ 结束循环，以此条 raw 进入解析。
   - **仅旋转**：`needs_rotation` 为真且 `rotate_clockwise_90_steps` 非 0 → 在内存中对当前图做顺时针 90°×`steps` 的旋转，**旋转次数**加一，再次请求；直至识别成功或达到上限。
3. **次数上限**：`vlm.max_orientation_gate_rotations`（默认 3）。若在未识别前又要求旋转且已用尽次数，则置 `orientation_skipped: true`，保留最后一次 raw，`parse_meta` 中附带 `max_orientation_gate_rotations_exceeded` 等信息。
4. 页级 JSON / manifest 中会写入 `vlm_orientation_gate`、`orientation_rotate_attempts`、`rotate_clockwise_90_applied`、`orientation_skipped` 等。

门控开启时，解析阶段 **`drop_vlm_orientation_keys=False`**（保留与门控 JSON 的兼容；最终以「识别」分支的 JSON 为准）。

## 输出布局

- 输出根目录（默认 `data/out/delivery_vlm` 或由调用方指定）。
- `page_text.subdir`（默认 `pages`）下：每页 `{page_id}.json`、`page_text.manifest`（默认 `pages.jsonl`）。
- 根目录：`delivery_merged.xlsx`（或 `--out-xlsx`）。

## 配置要点（参见 `configs/default.yaml`）

- **`preprocess`**：`auto_exif`、`auto_rotate_ocr`（可选）、`deskew`、`perspective`、`tone_mode`、`max_long_edge`。
- **`vlm`**：`model`、`use_preprocess`、`max_long_edge`、`max_workers`、`use_vlm_rotation_gate`、`max_orientation_gate_rotations` 等。
- **`delivery`**：`merge_by_style`（为 **false** 时导出全明细且列中含 `page_id` / `source_image`；为 **true** 时仅业务列并按 `merge_key` 合并）、`merge_key`、`line_keys` / `header_keys`。未写 `merge_by_style` 时，仍可根据已弃用字段 `xlsx_include_trace` / `xlsx_mode` 推断是否合并。

## 图形界面（`delivery-vlm-gui`）

主窗口「运行选项」勾选框与 yaml 对应关系概览：

| 界面文案 | 覆盖的配置路径 |
|----------|----------------|
| EXIF 读图转正 | `preprocess.auto_exif` |
| OCR 四向转正 | `preprocess.auto_rotate_ocr.enabled` |
| 整单透视拉直 | `preprocess.perspective.enabled` |
| 小角倾斜纠偏 | `preprocess.deskew.enabled` |
| 预处理再送模型 | `vlm.use_preprocess` |
| VLM 多轮转向 | `vlm.use_vlm_rotation_gate` |
| 导出合并同款（关则全明细 + 追溯列） | `delivery.merge_by_style` |

启动时勾选状态从项目 **`configs/default.yaml`** 同步；**每次勾选/取消运行选项**都会立刻合并写回该文件（日志里会打印绝对路径）。点击「开始识别」时也会先尝试保存再校验是否已选图。任务结束（完成/取消）后 GUI 会复位并再次从 yaml 同步。

若你在编辑器里打开的是仓库里的 `configs/default.yaml`，但运行的是打包后的 exe，实际写入的可能是 exe 旁的 `configs/default.yaml`，两处不是同一份文件。

## 命令行示例

```bash
delivery-vlm --in path/to/images --config configs/default.yaml
# 显式关闭 VLM 门控（覆盖 yaml）
delivery-vlm --in path/to/images --no-vlm-rotation
# 不合并、导出含 page_id / source_image 的明细表（覆盖 delivery.merge_by_style）
delivery-vlm --in path/to/images --no-merge-by-style
```

安装项目后入口为 `delivery-vlm` / `delivery-vlm-gui`（见 `pyproject.toml` 的 scripts）。未安装时可在项目根执行：`python -m delivery_vlm.cli -h`。
