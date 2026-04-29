"""
送货单 VLM 图形界面：选图目录（或多选文件）→ 预处理 + 多模态识别 → 合并 xlsx。

布局与交互参考 nursing-mm-qbank（tkinter + 可选 sv-ttk、日志队列、后台线程、取消）。

运行：
  delivery-vlm-gui
或：
  python -m delivery_vlm.gui_app

可选主题依赖：pip install "delivery-slip-vlm[gui]"（安装 sv-ttk）。
"""

from __future__ import annotations

import logging
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

if sys.platform == "win32":
    try:
        import ctypes

        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            try:
                import ctypes

                ctypes.windll.user32.SetProcessDPIAware()  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                pass

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext, ttk
except ImportError as e:  # noqa: F841
    tk = None  # type: ignore[misc, assignment]
    filedialog = messagebox = scrolledtext = ttk = None  # type: ignore[misc, assignment]
    _tk_import_error = e
else:
    _tk_import_error = None

from dotenv import load_dotenv

try:
    import sv_ttk
except Exception:  # noqa: BLE001
    sv_ttk = None  # type: ignore[assignment]

from delivery_vlm import __version__
from delivery_vlm.config import deep_merge_config, load_config, project_root
from delivery_vlm.pipeline.delivery_run import run_delivery_vlm_to_xlsx

_LOG_QUEUE: queue.Queue[str] | None = None

_log = logging.getLogger(__name__)


class _TextQueueHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:  # noqa: N802
        if _LOG_QUEUE is not None:
            _LOG_QUEUE.put(self.format(record) + "\n")


def _reveal_dir(path: Path) -> None:
    p = path.resolve()
    if not p.is_dir():
        p = p.parent
    s = str(p)
    if sys.platform == "win32":
        os.startfile(s)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", s], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.Popen(["xdg-open", s], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _list_images(d: Path) -> list[Path]:
    exts = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
    if not d.is_dir():
        return []
    return sorted(p for p in d.rglob("*") if p.is_file() and p.suffix.lower() in exts)


def _safe_name(name: str) -> str:
    s = (name or "").strip()
    s = re.sub(r'[\\/:*?"<>|]+', "_", s)
    s = re.sub(r"\s+", "_", s)
    return s or "input"


def main() -> None:
    global _LOG_QUEUE  # noqa: PLW0603

    if tk is None:
        print("当前解释器未带 tkinter，请使用官方 Python（含 Tcl/Tk）。", file=sys.stderr)  # noqa: T201
        raise SystemExit(1) from _tk_import_error

    load_dotenv(project_root() / ".env")

    _LOG_QUEUE = queue.Queue()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )
    th = _TextQueueHandler()
    th.setLevel(logging.INFO)
    th.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S"))
    logging.getLogger().addHandler(th)
    for name in ("httpx", "httpcore", "openai", "urllib3"):
        logging.getLogger(name).setLevel(logging.WARNING)

    root = tk.Tk()
    root.title(f"delivery-slip-vlm v{__version__} · 送货单识别")
    root.geometry("1200x800")
    root.minsize(680, 480)

    if sv_ttk is not None:
        try:
            sv_ttk.set_theme("light")
        except Exception:  # noqa: BLE001
            pass

    try:
        import tkinter.font as tkfont

        base_family = "Segoe UI" if sys.platform == "win32" else "TkDefaultFont"
        main_size = 10
        mono_family = "Consolas" if os.name == "nt" else "monospace"
        tkfont.nametofont("TkDefaultFont").configure(family=base_family, size=main_size)
        tkfont.nametofont("TkTextFont").configure(family=base_family, size=main_size)
        tkfont.nametofont("TkHeadingFont").configure(family=base_family, size=main_size, weight="bold")
        tkfont.nametofont("TkMenuFont").configure(family=base_family, size=main_size)
        tkfont.nametofont("TkFixedFont").configure(family=mono_family, size=main_size)
        _font_main = (base_family, main_size)
        _font_mono = (mono_family, main_size)
        style = ttk.Style()
        style.configure(".", font=_font_main)
        for sty in ("TLabel", "TButton", "TCheckbutton", "TRadiobutton", "TEntry", "TCombobox", "TNotebook.Tab"):
            style.configure(sty, font=_font_main)
        root.option_add("*TCombobox*Listbox.font", _font_main)
        root.option_add("*Listbox.font", _font_main)
    except Exception:  # noqa: BLE001
        _font_main = None
        _font_mono = None

    content = ttk.Frame(root)
    content.pack(fill=tk.BOTH, expand=True)

    work_dir: list[Path | None] = [None]
    is_temp: list[bool] = [False]
    last_out: list[Path | None] = [None]

    run_cancel = threading.Event()
    is_running: list[bool] = [False]

    fr_top = ttk.LabelFrame(content, text="图片输入", padding=8)
    fr_top.pack(fill=tk.X, padx=8, pady=4)
    fr_top_bar = ttk.Frame(fr_top)
    fr_top_bar.pack(fill=tk.X)
    ttk.Label(fr_top_bar, text=f"v{__version__}", foreground="#666").pack(side=tk.RIGHT, padx=(8, 0))
    btn_dir = ttk.Button(fr_top_bar, text="选择图片文件夹…")
    btn_dir.pack(side=tk.LEFT, padx=(0, 8))
    btn_files = ttk.Button(fr_top_bar, text="选择图片（可多选）…")
    btn_files.pack(side=tk.LEFT, padx=(0, 8))
    _hint_idle = (
        "将递归扫描文件夹内 .png / .jpg / .jpeg / .bmp / .webp。"
        "配置固定为项目 configs/default.yaml；.env 中设置 VLM_BASE_URL、VLM_API_KEY（及可选 VLM_MODEL）。"
    )
    lbl_in = ttk.Label(fr_top, text="未选择", foreground="#666")
    lbl_in.pack(anchor=tk.W, pady=(6, 0))
    lbl_hint = ttk.Label(
        fr_top,
        text=_hint_idle,
        foreground="#666",
        wraplength=900,
    )
    lbl_hint.pack(anchor=tk.W, pady=(2, 0))

    auto_exif_var = tk.BooleanVar(value=True)
    ocr_rot_en_var = tk.BooleanVar(value=False)
    perspective_en_var = tk.BooleanVar(value=True)
    use_pre_var = tk.BooleanVar(value=True)
    _gui_loading = False

    def _sync_from_yaml() -> None:
        nonlocal _gui_loading
        try:
            c = load_config(None)
        except Exception:  # noqa: BLE001
            return
        _gui_loading = True
        try:
            pre = dict(c.get("preprocess") or {})
            pe = dict(pre.get("perspective") or {})
            ore = dict(pre.get("auto_rotate_ocr") or {})
            vm = dict(c.get("vlm") or {})
            dl = dict(c.get("delivery") or {})
            auto_exif_var.set(bool(pre.get("auto_exif", True)))
            ocr_rot_en_var.set(bool(ore.get("enabled", False)))
            perspective_en_var.set(bool(pe.get("enabled", True)))
            use_pre_var.set(bool(vm.get("use_preprocess", True)))
        finally:
            _gui_loading = False

    def _config_overrides() -> dict[str, Any]:
        return {
            "preprocess": {
                "auto_exif": auto_exif_var.get(),
                "auto_rotate_ocr": {"enabled": ocr_rot_en_var.get()},
                "perspective": {"enabled": perspective_en_var.get()},
            },
            "vlm": {
                "use_preprocess": use_pre_var.get(),
            },
        }

    def _save_gui_options_to_yaml() -> None:
        cfg_path = (project_root() / "configs" / "default.yaml").resolve()
        current = load_config(None)
        merged = deep_merge_config(current, _config_overrides())
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        # 使用 block style（多行缩进），避免 {a:1,b:2} 这类单行内联格式。
        text = yaml.safe_dump(
            merged,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
            width=120,
        )
        if not text.endswith("\n"):
            text += "\n"
        cfg_path.write_text(text, encoding="utf-8")
        _log.info("GUI 已保存运行选项到 %s", cfg_path)

    def _persist_gui_options_from_toggle(*_: Any) -> None:
        if _gui_loading or is_running[0]:
            return
        try:
            _save_gui_options_to_yaml()
        except Exception as e:  # noqa: BLE001
            _log.warning("GUI 自动保存 default.yaml 失败: %s", e)

    fr_flags = ttk.LabelFrame(content, text="运行选项（勾选即写入 configs/default.yaml）", padding=6)
    fr_flags.pack(fill=tk.X, padx=8, pady=2)
    chk_run_opts: list[ttk.Checkbutton] = []
    _flag_grid: tuple[tuple[str, tk.BooleanVar], ...] = (
        ("EXIF 读图转正", auto_exif_var),
        ("文字方向检测转正", ocr_rot_en_var),
        ("整单透视拉直", perspective_en_var),
        ("预处理再送模型", use_pre_var),
    )
    # 保持所有运行选项在同一行展示
    for _ci in range(len(_flag_grid)):
        fr_flags.columnconfigure(_ci, weight=1)
    for i, (text, var) in enumerate(_flag_grid):
        w = ttk.Checkbutton(fr_flags, text=text, variable=var)
        w.grid(row=0, column=i, sticky=tk.W, padx=(0, 12), pady=3)
        chk_run_opts.append(w)

    _sync_from_yaml()
    for _v in (
        auto_exif_var,
        ocr_rot_en_var,
        perspective_en_var,
        use_pre_var,
    ):
        _v.trace_add("write", _persist_gui_options_from_toggle)

    fr_out = ttk.LabelFrame(content, text="输出", padding=6)
    fr_out.pack(fill=tk.X, padx=8, pady=4)
    ex = (project_root() / "data" / "out" / "delivery_gui_YYYYMMDD_hhmmss_输入名").as_posix()
    lbl_path = ttk.Label(fr_out, text=f"开始识别后生成目录，形如: {ex}", wraplength=960)
    lbl_path.pack(anchor=tk.W)

    fr_pb = ttk.LabelFrame(content, text="进度", padding=6)
    fr_pb.pack(fill=tk.X, padx=8, pady=2)
    pb = ttk.Progressbar(fr_pb, mode="determinate", length=800, maximum=1000, value=0)
    pb.pack(fill=tk.X, pady=(0, 4))
    st_lbl = ttk.Label(fr_pb, text="空闲")
    st_lbl.pack(anchor=tk.W)
    fr_act = ttk.Frame(fr_pb)
    fr_act.pack(fill=tk.X, pady=4)
    btn_start = ttk.Button(fr_act, text="开始识别", width=14)
    btn_start.pack(side=tk.LEFT, padx=(0, 8))
    btn_cancel = ttk.Button(fr_act, text="取消", width=10, state=tk.DISABLED)
    btn_cancel.pack(side=tk.LEFT, padx=(0, 8))
    btn_ref = ttk.Button(fr_act, text="打开输出目录", state=tk.DISABLED, width=18)
    btn_ref.pack(side=tk.LEFT)

    fr_log = ttk.LabelFrame(content, text="日志", padding=4)
    fr_log.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
    fr_log_bar = ttk.Frame(fr_log)
    fr_log_bar.pack(fill=tk.X, pady=(0, 4))
    ttk.Label(fr_log_bar, text="主题：").pack(side=tk.LEFT)
    style = ttk.Style()
    builtin_themes = list(style.theme_names() or [])
    theme_var = tk.StringVar(value="sv-light" if sv_ttk is not None else (builtin_themes[0] if builtin_themes else ""))
    theme_values: list[str] = []
    if sv_ttk is not None:
        theme_values.extend(["sv-light", "sv-dark"])
    theme_values.extend(builtin_themes)
    cb_theme = ttk.Combobox(fr_log_bar, textvariable=theme_var, values=theme_values, width=14, state="readonly")
    cb_theme.pack(side=tk.LEFT, padx=(0, 12))

    def _apply_theme(_: Any | None = None) -> None:
        v = (theme_var.get() or "").strip()
        if not v:
            return
        if v.startswith("sv-"):
            if sv_ttk is None:
                return
            try:
                sv_ttk.set_theme("dark" if v == "sv-dark" else "light")
            except Exception:  # noqa: BLE001
                pass
        else:
            try:
                style.theme_use(v)
            except Exception:  # noqa: BLE001
                pass

    cb_theme.bind("<<ComboboxSelected>>", _apply_theme)
    _apply_theme()

    ttk.Label(fr_log_bar, text="日志级别：").pack(side=tk.LEFT)
    log_level_var = tk.StringVar(value="INFO")
    cb_level = ttk.Combobox(
        fr_log_bar, textvariable=log_level_var, values=["INFO", "DEBUG", "WARNING"], width=10, state="readonly"
    )
    cb_level.pack(side=tk.LEFT)

    def _apply_log_level(_: Any | None = None) -> None:
        v = (log_level_var.get() or "INFO").strip().upper()
        level = logging.DEBUG if v == "DEBUG" else (logging.WARNING if v in ("WARN", "WARNING") else logging.INFO)
        logging.getLogger().setLevel(level)
        th.setLevel(level)
        logging.getLogger("delivery_vlm").setLevel(level)

    cb_level.bind("<<ComboboxSelected>>", _apply_log_level)
    _apply_log_level()

    font_ = _font_mono or (("Consolas", 10) if os.name == "nt" else ("monospace", 10))
    log_t = scrolledtext.ScrolledText(fr_log, height=14, state=tk.DISABLED, font=font_)

    def _append_t(msg: str) -> None:
        log_t.config(state=tk.NORMAL)
        log_t.insert(tk.END, msg)
        if not msg.endswith("\n"):
            log_t.insert(tk.END, "\n")
        log_t.see(tk.END)
        log_t.config(state=tk.DISABLED)

    log_t.pack(fill=tk.BOTH, expand=True)
    _append_t("日志将显示在此处；预处理与 VLM 调用见 configs/default.yaml。\n\n")

    def poll_q() -> None:
        if _LOG_QUEUE is None:
            return
        buf: list[str] = []
        for _ in range(200):
            try:
                buf.append(_LOG_QUEUE.get_nowait())
            except queue.Empty:
                break
        if buf:
            _append_t("".join(buf))
        root.after(120, poll_q)

    root.after(150, poll_q)

    def on_pick_dir() -> None:
        p = filedialog.askdirectory(title="选择含图片的文件夹", mustexist=True)
        if not p:
            return
        d = Path(p)
        imgs = _list_images(d)
        work_dir[0] = d
        is_temp[0] = False
        lbl_in.config(text=f"文件夹: {d}  （共 {len(imgs)} 张图）", foreground="black")
        if not imgs:
            lbl_hint.config(text="该路径下无支持的图片。", foreground="#a60")
            messagebox.showwarning("提示", "该目录下没有支持的图片格式。")
        else:
            lbl_hint.config(text=f"已选 {len(imgs)} 张，点击「开始识别」。", foreground="#444")

    def on_pick_files() -> None:
        files = filedialog.askopenfilenames(
            title="选择一个或多个图片",
            filetypes=[("图片", "*.png;*.jpg;*.jpeg;*.bmp;*.webp"), ("全部", "*.*")],
        )
        if not files:
            return
        paths = [Path(f) for f in files if Path(f).is_file()]
        if not paths:
            return
        tmp = Path(tempfile.mkdtemp(prefix="delivery_vlm_gui_"))
        for src in paths:
            shutil.copy2(src, tmp / src.name)
        work_dir[0] = tmp
        is_temp[0] = True
        imgs = _list_images(tmp)
        lbl_in.config(
            text=f"已选 {len(paths)} 个文件（临时目录 {tmp}，共 {len(imgs)} 张有效图）",
            foreground="black",
        )
        if not imgs:
            lbl_hint.config(text="复制后无有效图片。", foreground="#a60")
            messagebox.showwarning("提示", "未复制到有效图片。")
        else:
            lbl_hint.config(text=f"已选 {len(imgs)} 张，任务结束后将删除临时目录。", foreground="#444")

    btn_dir["command"] = on_pick_dir
    btn_files["command"] = on_pick_files

    def on_open_out() -> None:
        p = last_out[0]
        if p and p.is_dir():
            try:
                _reveal_dir(p)
            except Exception as e:  # noqa: BLE001
                messagebox.showerror("无法打开", str(e))
        else:
            messagebox.showinfo("提示", "尚无输出目录。")

    btn_ref["command"] = on_open_out

    def _set_inputs(state: str) -> None:
        btn_dir["state"] = state
        btn_files["state"] = state
        for w in chk_run_opts:
            w["state"] = state

    def _reset_initial_state() -> None:
        work_dir[0] = None
        is_temp[0] = False
        last_out[0] = None
        _sync_from_yaml()
        lbl_in.config(text="未选择", foreground="#666")
        lbl_hint.config(text=_hint_idle, foreground="#666")
        lbl_path.config(text=f"开始识别后生成目录，形如: {ex}", foreground="black")
        pb["value"] = 0
        st_lbl.config(text="空闲", foreground="black")
        btn_ref["state"] = tk.DISABLED

    def on_cancel() -> None:
        run_cancel.set()
        st_lbl.config(text="正在取消（当前页请求结束后生效）…", foreground="#a60")

    btn_cancel["command"] = on_cancel

    def on_start() -> None:
        if is_running[0]:
            return
        try:
            _save_gui_options_to_yaml()
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("保存配置失败", f"无法写入 configs/default.yaml：\n{e}")
            return
        wd = work_dir[0]
        if not wd or not wd.is_dir():
            messagebox.showwarning("提示", "请先选择图片文件夹或多选图片。")
            return
        n = len(_list_images(wd))
        if n < 1:
            messagebox.showwarning("提示", "当前输入下没有可处理的图片。")
            return

        run_cancel.clear()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        src_name = _safe_name(wd.name) if wd.name else "input"
        out = (project_root() / "data" / "out" / f"delivery_gui_{ts}_{src_name}").resolve()
        out.mkdir(parents=True, exist_ok=True)
        last_out[0] = out
        lbl_path.config(text=f"本次输出: {out}", foreground="black")

        is_running[0] = True
        _set_inputs(tk.DISABLED)
        btn_start["state"] = tk.DISABLED
        btn_cancel["state"] = tk.NORMAL
        btn_ref["state"] = tk.DISABLED
        root.config(cursor="wait")
        pb["value"] = 0
        st_lbl.config(text=f"待处理 {n} 张 · 0%", foreground="black")

        was_temp = is_temp[0]

        def on_page_done(i: int, t: int) -> None:
            if t <= 0:
                return

            def u() -> None:
                pb["value"] = int(1000 * min(i, t) / t)
                st_lbl.config(text=f"VLM {i}/{t} · {100.0 * i / t:.1f}%")

            root.after(0, u)

        def work() -> None:
            err: str | None = None
            summary: dict[str, Any] = {}
            try:
                summary = run_delivery_vlm_to_xlsx(
                    input_dir=wd,
                    out_dir=out,
                    config_path=None,
                    model=None,
                    cancel_event=run_cancel,
                    on_page_done=on_page_done,
                    config_overrides=_config_overrides(),
                )
            except Exception as e:  # noqa: BLE001
                err = str(e)
            try:
                if was_temp and wd and wd.is_dir():
                    shutil.rmtree(wd, ignore_errors=True)
                    is_temp[0] = False
                    work_dir[0] = None

                    def _clear_lbl() -> None:
                        lbl_in.config(text="多选图片的临时目录已删除；请重新选择输入", foreground="#666")

                    root.after(0, _clear_lbl)
            except OSError:
                pass

            root.after(0, lambda e=err, s=summary: on_done(e, s))

        threading.Thread(target=work, daemon=True).start()

    def on_done(err: str | None, summary: dict[str, Any]) -> None:
        is_running[0] = False
        root.config(cursor="")
        run_cancel.clear()
        _set_inputs(tk.NORMAL)
        btn_start["state"] = tk.NORMAL
        btn_cancel["state"] = tk.DISABLED

        if err is not None:
            pb["value"] = 0
            st_lbl.config(text="失败", foreground="red")
            _append_t(f"\n[错误] {err}\n")
            messagebox.showerror("识别失败", err)
            if last_out[0] and last_out[0].is_dir():
                btn_ref["state"] = tk.NORMAL
                try:
                    _reveal_dir(last_out[0])
                except Exception:  # noqa: BLE001
                    pass
            return

        if summary.get("cancelled"):
            pb["value"] = int(1000 * (summary.get("n_pages", 0) or 0) / max(1, summary.get("n_total_images", 1)))
            st_lbl.config(text="已取消", foreground="#a60")
            _append_t(
                f"\n已取消: {summary}\n临时目录: {summary.get('tmp_dir','')}"
                f"\n临时图数量: {summary.get('tmp_png_count','')}\n"
            )
            messagebox.showinfo("已取消", f"已完成部分页。\n输出: {summary.get('out_dir', '')}")
        else:
            pb["value"] = 1000
            st_lbl.config(text="完成", foreground="green")
            ox = summary.get("out_xlsx", "")
            _append_t(
                f"\n完成: xlsx={ox}\nmanifest={summary.get('manifest', '')}"
                f"\n临时目录: {summary.get('tmp_dir','')}"
                f"\n临时图数量: {summary.get('tmp_png_count','')}\n"
            )
            msg = f"合并表:\n{ox}\n\n表内行数: {summary.get('n_rows', '')}"
            nd = summary.get("n_detail_rows")
            nr = summary.get("n_rows")
            if isinstance(nd, int) and isinstance(nr, int) and nd != nr:
                msg += f"\n（由 {nd} 条明细按款号合并）"
            messagebox.showinfo("完成", msg)
        # 任务结束后自动打开输出目录
        if last_out[0] and last_out[0].is_dir():
            btn_ref["state"] = tk.NORMAL
            try:
                _reveal_dir(last_out[0])
            except Exception:  # noqa: BLE001
                pass
        n_failed = int(summary.get("n_failed_images", 0) or 0)
        if n_failed > 0:
            failed = summary.get("failed_pages") or []
            pages = ", ".join(str(x.get("page_id", "")) for x in failed[:12] if isinstance(x, dict))
            extra = f"\n失败页: {pages}" if pages else ""
            if len(failed) > 12:
                extra += " ..."
            messagebox.showwarning(
                "识别有跳过",
                f"有 {n_failed} 张图片连续重试 3 次仍失败，已自动跳过。{extra}",
            )
        _reset_initial_state()

    btn_start["command"] = on_start

    root.mainloop()


if __name__ == "__main__":
    main()
