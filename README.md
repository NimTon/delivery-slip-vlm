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
| `false` | 用 `load_bgr` 仅做读图（含 `preprocess.auto_exif`）；后续 **直接发送原文件字节**（MIME 按后缀推断），**不缩放、不做色调/透视**。 |

当 `use_preprocess: true` 时，单图预处理顺序为：

1. **读图**：`load_bgr`；若 `auto_exif: true`，优先按 EXIF 摆正像素。
2. **几何**（`apply_rotate_and_deskew`）：文字方向检测转正（可选）→ 透视（可选）。
   - 若 **`preprocess.auto_rotate_ocr.enabled: true`**：用 **PaddleClas(PULC)** 的 **`text_image_orientation`** 做整页文字方向检测（0/90/180/270），并自动转正（需 `pip install paddleclas paddlepaddle`）。不可用或未识别到时保持原朝向。
3. **缩放**：长边限制为 `max_long_edge`（优先 `vlm.max_long_edge`，否则 `preprocess.max_long_edge`）。
4. **色调**：`tone_mode`（如 `shaded` / `raw`）。
5. 写入临时目录下的 PNG。

说明：整页 90° 的转正由本地「文字方向检测转正（PULC）」完成。

## 单张图片：VLM 与解析

调用 **一次** VLM：`vlm_delivery_system` + `vlm_delivery_user`（`configs/prompts/` 下外置文件优先）。
提示词要求模型**只输出业务表格 JSON**；`parse_delivery_response(..., drop_vlm_orientation_keys=True)` 会在解析前移除顶层朝向键（若模型误输出），避免误入业务字段。

## 输出布局

- 输出根目录（默认 `data/out/delivery_vlm` 或由调用方指定）。
- `page_text.subdir`（默认 `pages`）下：每页 `{page_id}.json`、`page_text.manifest`（默认 `pages.jsonl`）。
- 根目录：`delivery_merged.xlsx`（或 `--out-xlsx`）。

## 配置要点（参见 `configs/default.yaml`）

- **`preprocess`**：`auto_exif`、`auto_rotate_ocr`（可选）、`perspective`、`tone_mode`、`max_long_edge`。
- **`vlm`**：`model`、`use_preprocess`、`max_long_edge`、`max_workers` 等。
- **`delivery`**：`merge_key`、`line_keys` / `header_keys`。

## 图形界面（`delivery-vlm-gui`）

主窗口「运行选项」勾选框与 yaml 对应关系概览：

| 界面文案 | 覆盖的配置路径 |
|----------|----------------|
| EXIF 读图转正 | `preprocess.auto_exif` |
| 文字方向检测转正 | `preprocess.auto_rotate_ocr.enabled` |
| 整单透视拉直 | `preprocess.perspective.enabled` |
| 预处理再送模型 | `vlm.use_preprocess` |
（xlsx 固定输出两个 sheet：`detail` 与 `merged`）

启动时勾选状态从项目 **`configs/default.yaml`** 同步；**每次勾选/取消运行选项**都会立刻合并写回该文件（日志里会打印绝对路径）。点击「开始识别」时也会先尝试保存再校验是否已选图。任务结束（完成/取消）后 GUI 会复位并再次从 yaml 同步。

若你在编辑器里打开的是仓库里的 `configs/default.yaml`，但运行的是打包后的 exe，实际写入的可能是 exe 旁的 `configs/default.yaml`，两处不是同一份文件。

## 命令行示例

```bash
delivery-vlm --in path/to/images --config configs/default.yaml
delivery-vlm --in path/to/images --config configs/default.yaml
```

安装项目后入口为 `delivery-vlm` / `delivery-vlm-gui`（见 `pyproject.toml` 的 scripts）。未安装时可在项目根执行：`python -m delivery_vlm.cli -h`。
