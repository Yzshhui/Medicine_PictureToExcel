"""
药品包装识别工具 - 主程序
图片 → 提取药品信息 → 导出 Excel
"""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import os
import json
import threading
from pathlib import Path

from medicine_ocr import (
    analyze_image,
    export_to_excel,
    MEDICINE_FIELDS,
    extract_text_easyocr,
    parse_medicine_info,
    is_easyocr_model_ready,
)

# ===== 配置管理 =====
CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")

def load_config():
    default = {
        "base_url": "https://api.openai.com/v1",
        "api_key": "",
        "model": "gpt-4o",
        "work_dir": os.path.dirname(os.path.abspath(__file__)),
        "model_dir": os.path.join(os.path.expanduser("~"), ".EasyOCR", "model"),
        "output_dir": "",
        "model_history": [],
        "model_removed": [],
        "showapi_accounts": [],
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return {**default, **json.load(f)}
        except:
            pass
    return default

def save_config(config):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


# ===== 主界面 =====
class MedicineOCRApp:
    def __init__(self, root):
        self.root = root
        self.root.title("药品包装识别工具")
        self.root.geometry("1100x750")
        self.root.minsize(800, 600)

        self.config = load_config()
        self.images = []  # list of {"path": ..., "results": [dict]}
        self.results = []  # flat list of all results
        self.current_page = 0
        self.page_size = 20

        self._setup_ui()
        self._bind_events()

    def _setup_ui(self):
        # ===== 顶部工具栏 =====
        toolbar = ttk.Frame(self.root, padding=5)
        toolbar.pack(side=tk.TOP, fill=tk.X)

        ttk.Button(toolbar, text="📁 添加图片", command=self.add_images).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="🗑 清空列表", command=self.clear_images).pack(side=tk.LEFT, padx=2)
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=8, fill=tk.Y)

        ttk.Button(toolbar, text="🔍 本地OCR识别", command=self.run_ocr).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="🤖 AI视觉识别", command=self.run_ai_vision).pack(side=tk.LEFT, padx=2)
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=8, fill=tk.Y)

        ttk.Button(toolbar, text="📊 导出Excel", command=self.export_excel).pack(side=tk.LEFT, padx=2)
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=8, fill=tk.Y)

        ttk.Button(toolbar, text="⚙ 设置", command=self.open_settings).pack(side=tk.LEFT, padx=2)

        # 状态信息
        self.status_label = ttk.Label(toolbar, text="就绪")
        self.status_label.pack(side=tk.RIGHT, padx=8)

        # ===== 主区域 =====
        main_paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_paned.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 左侧：图片列表
        left_frame = ttk.LabelFrame(main_paned, text="图片列表", padding=3)
        self.img_listbox = tk.Listbox(left_frame, width=30, font=("Microsoft YaHei", 9))
        self.img_listbox.pack(fill=tk.BOTH, expand=True)
        self.img_listbox.bind("<<ListboxSelect>>", self.on_select_image)
        main_paned.add(left_frame, weight=0)

        # 右侧：预览 + 结果
        right_frame = ttk.Frame(main_paned)
        main_paned.add(right_frame, weight=1)

        # - 预览区域
        preview_frame = ttk.LabelFrame(right_frame, text="图片预览", padding=3)
        preview_frame.pack(fill=tk.BOTH, expand=False, pady=(0, 5))

        self.preview_label = ttk.Label(preview_frame, text="← 左侧选择图片", anchor=tk.CENTER)
        self.preview_label.pack(fill=tk.X, expand=False, pady=10)

        # - 结果表格
        result_frame = ttk.LabelFrame(right_frame, text="识别结果（双击单元格可编辑）", padding=3)
        result_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("药名", "厂家", "国药准字", "规格")
        self.tree = ttk.Treeview(result_frame, columns=columns, show="headings", height=12)
        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=150, minwidth=80)
        self.tree.tag_configure("warn", foreground="red")
        self.tree.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)

        # 滚动条
        scrollbar = ttk.Scrollbar(result_frame, orient=tk.VERTICAL, command=self.tree.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.configure(yscrollcommand=scrollbar.set)

        # ===== 底部状态栏 =====
        bottom_frame = ttk.Frame(self.root, padding=3)
        bottom_frame.pack(side=tk.BOTTOM, fill=tk.X)
        self.mode_label = ttk.Label(bottom_frame, text="模式: 本地OCR (无API)")
        self.mode_label.pack(side=tk.LEFT)
        self.count_label = ttk.Label(bottom_frame, text="图片: 0 | 结果: 0")
        self.count_label.pack(side=tk.RIGHT)

        # 更新模式显示
        self._update_mode_display()
        self._update_count_display()

    def _bind_events(self):
        # 双击编辑
        self.tree.bind("<Double-1>", self.on_cell_edit)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ----- 图片管理 -----
    def add_images(self):
        files = filedialog.askopenfilenames(
            title="选择药品包装图片",
            initialdir=self.config.get("work_dir") or os.path.expanduser("~"),
            filetypes=[
                ("图片文件", "*.jpg *.jpeg *.png *.webp *.bmp"),
                ("所有文件", "*.*"),
            ],
        )
        if not files:
            return

        added = 0
        for f in files:
            if not any(img["path"] == f for img in self.images):
                self.images.append({"path": f, "results": []})
                self.img_listbox.insert(tk.END, os.path.basename(f))
                added += 1

        if added > 0:
            self.status_label.config(text=f"已添加 {added} 张图片")
            self._update_count_display()

    def clear_images(self):
        if not self.images:
            return
        if messagebox.askyesno("确认", f"清空所有 {len(self.images)} 张图片？"):
            self.images.clear()
            self.img_listbox.delete(0, tk.END)
            self._clear_tree()
            self.results.clear()
            self.status_label.config(text="已清空")
            self._update_count_display()

    def on_select_image(self, event):
        sel = self.img_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx >= len(self.images):
            return

        img_data = self.images[idx]
        self._show_preview(img_data["path"])
        self._show_results_for_image(idx)

    def _show_preview(self, path):
        try:
            from PIL import Image, ImageTk
            img = Image.open(path)
            img.thumbnail((500, 300), Image.LANCZOS)
            tk_img = ImageTk.PhotoImage(img)
            self.preview_label.config(image=tk_img, text="")
            self.preview_label.image = tk_img  # keep reference
        except Exception as e:
            self.preview_label.config(text=f"无法预览: {e}", image="")

    def _show_results_for_image(self, img_idx):
        self._clear_tree()
        if img_idx >= len(self.images):
            return
        results = self.images[img_idx].get("results", [])
        for item in results:
            warns = item.get("_warn", [])
            tags = ("warn",) if warns else ()
            self.tree.insert("", tk.END, values=(
                item.get("药名", ""),
                item.get("厂家", ""),
                item.get("国药准字", ""),
                item.get("规格", ""),
            ), tags=tags)

    def _clear_tree(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

    # ----- OCR / AI 识别 -----
    def run_ocr(self):
        # 先检查本地模型是否已下载，避免默认自动下载（优先于图片检查）
        if not is_easyocr_model_ready(self.config.get("model_dir")):
            ans = messagebox.askyesno(
                "下载本地模型",
                "本地 OCR 模型尚未下载（约 50MB，首次使用需联网）。\n\n模型目录：\n" + (self.config.get("model_dir") or "默认 ~/.EasyOCR/model") + "\n\n是否现在下载？\n\n选择「是」开始下载；选择「否」可改用「AI 视觉识别」。",
            )
            if not ans:
                return
        if not self.images:
            messagebox.showinfo("提示", "请先添加图片")
            return
        self._run_extraction(mode="ocr")

    def run_ai_vision(self):
        if not self.images:
            messagebox.showinfo("提示", "请先添加图片")
            return
        if not self.config.get("api_key"):
            if messagebox.askyesno("API未配置", "尚未配置API密钥，是否现在配置？"):
                self.open_settings()
            if not self.config.get("api_key"):
                return
        self._run_extraction(mode="ai")

    def _run_extraction(self, mode="ocr"):
        # 禁用按钮
        self._set_buttons_state(tk.DISABLED)
        self.status_label.config(text="正在识别...")
        self.root.update()

        def worker():
            total = len(self.images)
            for idx, img_data in enumerate(self.images):
                try:
                    if mode == "ocr":
                        # 用本地 EasyOCR
                        text = extract_text_easyocr(img_data["path"], self.config.get("model_dir"))
                        results = [parse_medicine_info(text)]
                        for r in results:
                            r["_file"] = img_data["path"]
                    else:
                        # 用 AI Vision
                        results = analyze_image(img_data["path"], self.config, self.config.get("model_dir"))
                        for r in results:
                            r["_file"] = img_data["path"]

                    self.images[idx]["results"] = results

                    # ShowAPI 验证（在工作线程中，避免阻塞UI）
                    if self.config.get("showapi_enabled") and self.config.get("showapi_appkey") and self.config.get("showapi_secret"):
                        try:
                            from showapi_client import ShowApiClient
                            client = ShowApiClient(
                                self.config["showapi_appkey"],
                                self.config["showapi_secret"],
                                self.config.get("showapi_base", "https://route.showapi.com"),
                                cache_file=os.path.join(
                                    self.config.get("work_dir") or os.path.dirname(os.path.abspath(__file__)),
                                    "showapi_cache.json"
                                ),
                            )
                            for r in results:
                                    # 优先用国药准字查
                                    search_key = r.get("国药准字", "").replace("国药准字", "").strip()
                                    if not search_key:
                                        search_key = r.get("药名", "")
                                    if search_key:
                                        resp = client.search_drug(search_key, max_result=5)
                                        candidates = ShowApiClient.parse_response(resp)
                                        if candidates:
                                            # 简单匹配：药名+准字号都对
                                            best = None
                                            for c in candidates:
                                                if (c.get("批准文号") == r.get("国药准字") or
                                                    c.get("药品名称") == r.get("药名")):
                                                    best = c
                                                    break
                                            if best:
                                                # 比对四字段
                                                warns = []
                                                for local_f, api_f in [("药名", "药品名称"), ("厂家", "生产企业"),
                                                                       ("国药准字", "批准文号"), ("规格", "规格")]:
                                                    lv = (r.get(local_f) or "").strip()
                                                    av = (best.get(api_f) or "").strip()
                                                    if lv and av and lv != av:
                                                        warns.append(f"{local_f}不一致: 识别'{lv}' vs 官方'{av}'")
                                                r["_warn"] = (r.get("_warn", []) + warns)
                        except Exception as e:
                            print(f"[ShowAPI验证] 第{idx+1}张出错: {e}", flush=True)

                    print(f"[主程序] 已识别第 {idx+1}/{total} 张: {img_data['path']} -> {len(results)} 条", flush=True)

                    # 更新UI（在主线程）
                    self.root.after(0, lambda idx=idx: self._update_result_display(idx))

                except Exception as e:
                    print(f"[主程序] 第 {idx+1} 张识别出错: {e}", flush=True)
                    self.images[idx]["results"] = [{"药名": f"错误: {e}", "厂家": "", "国药准字": "", "规格": "", "_file": img_data["path"]}]
                    self.root.after(0, lambda idx=idx: self._update_result_display(idx))

                self.root.after(0, lambda i=idx+1: self.status_label.config(text=f"识别进度: {i}/{total}"))

            # 重新构建 flat results
            self._rebuild_flat_results()
            print(f"[主程序] 识别完成，共 {len(self.results)} 条结果", flush=True)
            self.root.after(0, self._on_extraction_done)

        threading.Thread(target=worker, daemon=True).start()

    def _update_result_display(self, img_idx):
        # 如果当前选中的是这个图片，刷新显示
        sel = self.img_listbox.curselection()
        if sel and sel[0] == img_idx:
            self._show_results_for_image(img_idx)

    def _rebuild_flat_results(self):
        self.results = []
        for img_data in self.images:
            self.results.extend(img_data.get("results", []))

    def _on_extraction_done(self):
        self._set_buttons_state(tk.NORMAL)
        self.status_label.config(text="识别完成 ✓")
        self._update_count_display()
        # 主动刷新结果表格：优先显示当前选中图片，否则显示第一张
        sel = self.img_listbox.curselection()
        if sel:
            self._show_results_for_image(sel[0])
        elif self.images:
            self.img_listbox.selection_set(0)
            self._show_results_for_image(0)
        else:
            self._clear_tree()
        if not self.results:
            messagebox.showwarning("完成", "识别完成，但没有任何结果。\n\n请检查：\n1. 终端日志中 API 返回内容\n2. API Key 与 base_url 是否正确\n3. 图片是否清晰可见药品信息")
        else:
            messagebox.showinfo("完成", f"识别完成！共 {len(self.results)} 条结果")

    def _set_buttons_state(self, state):
        for child in self.root.winfo_children():
            if isinstance(child, ttk.Frame):
                for btn in child.winfo_children():
                    if isinstance(btn, ttk.Button):
                        try:
                            btn.config(state=state)
                        except:
                            pass

    # ----- 编辑结果 -----
    def on_cell_edit(self, event):
        item = self.tree.selection()
        if not item:
            return
        # 获取点击位置
        col_id = self.tree.identify_column(event.x)
        col_idx = int(col_id.replace("#", "")) - 1
        if col_idx < 0:
            return

        col_name = MEDICINE_FIELDS[col_idx]
        values = self.tree.item(item[0], "values")
        old_val = values[col_idx] if col_idx < len(values) else ""

        # 弹出编辑框
        new_val = simpledialog.askstring(
            f"编辑 {col_name}", f"修改 {col_name}:", initialvalue=old_val,
            parent=self.root
        )
        if new_val is not None:
            new_values = list(values)
            new_values[col_idx] = new_val
            self.tree.item(item[0], values=tuple(new_values))

            # 同步更新 images 中的数据
            sel = self.img_listbox.curselection()
            if sel:
                img_idx = sel[0]
                tree_items = self.tree.get_children()
                for iid in tree_items:
                    if iid == item[0]:
                        row_idx = list(tree_items).index(iid)
                        results = self.images[img_idx].get("results", [])
                        if row_idx < len(results):
                            results[row_idx][col_name] = new_val
                        break

            self._rebuild_flat_results()

    # ----- 导出 Excel -----
    def export_excel(self):
        if not self.results:
            messagebox.showinfo("提示", "没有可导出的结果，请先识别")
            return

        # 默认输出路径：优先 output_dir，其次 work_dir，最后用户主目录
        default_dir = self.config.get("output_dir") or self.config.get("work_dir") or os.path.expanduser("~")
        default_name = "药品信息导出.xlsx"
        default_path = os.path.join(default_dir, default_name)

        file_path = filedialog.asksaveasfilename(
            title="导出 Excel",
            defaultextension=".xlsx",
            initialdir=default_dir if default_dir else os.path.expanduser("~"),
            initialfile=default_name,
            filetypes=[("Excel 文件", "*.xlsx")],
        )
        if not file_path:
            return

        try:
            export_to_excel(self.results, file_path)
            self.config["output_dir"] = os.path.dirname(file_path)
            save_config(self.config)
            self.status_label.config(text=f"已导出: {os.path.basename(file_path)}")
            messagebox.showinfo("导出成功", f"已保存到:\n{file_path}")
        except Exception as e:
            messagebox.showerror("导出失败", str(e))

    # ----- 设置 -----
    def open_settings(self):
        dialog = SettingsDialog(self.root, self.config)
        if dialog.result:
            self.config = dialog.result
            save_config(self.config)
            self._update_mode_display()

    def _update_mode_display(self):
        if self.config.get("api_key"):
            model = self.config.get("model", "gpt-4o")
            self.mode_label.config(text=f"模式: AI视觉 ({model})")
        else:
            self.mode_label.config(text="模式: 本地OCR (无API)")

    def _update_count_display(self):
        self.count_label.config(text=f"图片: {len(self.images)} | 结果: {len(self.results)}")

    def on_close(self):
        self.root.destroy()


# ===== 设置对话框 =====
class SettingsDialog:
    def __init__(self, parent, current_config):
        self.result = None
        dialog = tk.Toplevel(parent)
        dialog.title("API 设置")
        dialog.geometry("520x470")
        dialog.resizable(False, False)
        dialog.transient(parent)
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding=15)
        frame.pack(fill=tk.BOTH, expand=True)


        ttk.Label(frame, text="API 地址:").grid(row=1, column=0, sticky=tk.W, pady=5)
        base_url_var = tk.StringVar(value=current_config.get("base_url", "https://api.openai.com/v1"))
        ttk.Entry(frame, textvariable=base_url_var, width=50).grid(row=1, column=1, sticky=tk.EW, padx=(5, 0))

        ttk.Label(frame, text="API Key:").grid(row=2, column=0, sticky=tk.W, pady=5)
        api_key_var = tk.StringVar(value=current_config.get("api_key", ""))
        api_key_entry = ttk.Entry(frame, textvariable=api_key_var, width=50, show="*")
        api_key_entry.grid(row=2, column=1, sticky=tk.EW, padx=(5, 0))

        def toggle_key_visibility():
            if api_key_entry.cget("show") == "*":
                api_key_entry.config(show="")
                toggle_btn.config(text="隐藏")
            else:
                api_key_entry.config(show="*")
                toggle_btn.config(text="显示")
        toggle_btn = ttk.Button(frame, text="显示", command=toggle_key_visibility)
        toggle_btn.grid(row=2, column=2, padx=2)

        ttk.Label(frame, text="模型:").grid(row=3, column=0, sticky=tk.W, pady=5)
        model_var = tk.StringVar(value=current_config.get("model", "gpt-4o"))
        model_combo = ttk.Combobox(frame, textvariable=model_var, width=47)

        DEFAULT_MODELS = [
            "Qwen/Qwen2.5-VL-72B-Instruct", "Qwen/Qwen-VL-Plus", "Qwen/Qwen-VL-Max",
            "moonshot-v1-8k-vision-preview",
            "gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini",
            "claude-sonnet-4-20250514", "claude-3-5-sonnet-20241022",
            "gemini-2.5-flash", "gemini-2.5-pro",
            "deepseek-v3", "deepseek-r1",
        ]

        def _refresh_model_values():
            _h = list(current_config.get("model_history", []))
            _cur = current_config.get("model", "")
            _removed = set(current_config.get("model_removed", []))
            _mg, _s = [], set()
            for _x in _h + [_cur] + DEFAULT_MODELS:
                if _x and _x not in _s and _x not in _removed:
                    _s.add(_x)
                    _mg.append(_x)
            model_combo["values"] = _mg

        def _delete_model(_mm):
            _h = list(current_config.get("model_history", []))
            if _mm in _h:
                _h.remove(_mm)
                current_config["model_history"] = _h
            else:
                _removed = list(current_config.get("model_removed", []))
                if _mm not in _removed:
                    _removed.append(_mm)
                    current_config["model_removed"] = _removed
            save_config(current_config)
            _refresh_model_values()
            if model_var.get() == _mm:
                model_var.set("")

        def _reset_models():
            current_config["model_history"] = []
            current_config["model_removed"] = []
            save_config(current_config)
            _refresh_model_values()

        def _on_right_click(event):
            _menu = tk.Menu(model_combo, tearoff=0)
            _vals = list(model_combo["values"])
            if not _vals:
                _menu.add_command(label="（无条目可删）", state="disabled")
            else:
                for _m in _vals:
                    _menu.add_command(label="删除：" + _m, command=lambda mm=_m: _delete_model(mm))
                _menu.add_separator()
                _menu.add_command(label="恢复默认列表", command=_reset_models)
            _menu.tk_popup(event.x_root, event.y_root)

        _refresh_model_values()
        model_combo.grid(row=3, column=1, sticky=tk.EW, padx=(5, 0))
        model_combo.bind("<Button-3>", _on_right_click)


        ttk.Label(frame, text="工作目录:").grid(row=5, column=0, sticky=tk.W, pady=5)
        work_dir_var = tk.StringVar(value=current_config.get("work_dir", ""))
        ttk.Entry(frame, textvariable=work_dir_var, width=42).grid(row=5, column=1, sticky=tk.EW, padx=(5, 0))
        ttk.Button(frame, text="浏览", command=lambda: _browse_dir(work_dir_var)).grid(row=5, column=2, padx=2)

        ttk.Label(frame, text="模型目录:").grid(row=6, column=0, sticky=tk.W, pady=5)
        model_dir_var = tk.StringVar(value=current_config.get("model_dir", ""))
        ttk.Entry(frame, textvariable=model_dir_var, width=42).grid(row=6, column=1, sticky=tk.EW, padx=(5, 0))
        ttk.Button(frame, text="浏览", command=lambda: _browse_dir(model_dir_var)).grid(row=6, column=2, padx=2)

        ttk.Label(frame, text="ShowAPI AppKey:").grid(row=7, column=0, sticky=tk.W, pady=5)
        showapi_appkey_var = tk.StringVar(value=current_config.get("showapi_appkey", ""))
        showapi_secret_var = tk.StringVar(value=current_config.get("showapi_secret", ""))
        ttk.Entry(frame, textvariable=showapi_appkey_var, width=50).grid(row=7, column=1, sticky=tk.EW, padx=(5, 0))

        ttk.Label(frame, text="ShowAPI Secret:").grid(row=8, column=0, sticky=tk.W, pady=5)
        showapi_combo = ttk.Combobox(frame, textvariable=showapi_secret_var, width=47)
        showapi_combo.grid(row=8, column=1, sticky=tk.EW, padx=(5, 0))

        def _refresh_showapi_values():
            _accounts = list(current_config.get("showapi_accounts", []))
            _cur_key = current_config.get("showapi_appkey", "")
            _cur_secret = current_config.get("showapi_secret", "")
            if _cur_key and not any(a.get("appkey") == _cur_key for a in _accounts):
                _accounts.insert(0, {"appkey": _cur_key, "secret": _cur_secret})
            _vals, _seen = [], set()
            for a in _accounts:
                k = a.get("appkey", "")
                if k and k not in _seen:
                    _seen.add(k)
                    _vals.append(k)
            showapi_combo["values"] = _vals

        def _on_showapi_select(event):
            _k = showapi_secret_var.get()
            for a in current_config.get("showapi_accounts", []):
                if a.get("appkey") == _k:
                    showapi_appkey_var.set(a.get("appkey", ""))
                    showapi_secret_var.set(a.get("secret", ""))
                    break

        def _delete_showapi(_k):
            _accounts = [a for a in current_config.get("showapi_accounts", []) if a.get("appkey") != _k]
            current_config["showapi_accounts"] = _accounts
            save_config(current_config)
            _refresh_showapi_values()
            if showapi_appkey_var.get() == _k:
                showapi_appkey_var.set("")
                showapi_secret_var.set("")

        def _reset_showapi():
            current_config["showapi_accounts"] = []
            save_config(current_config)
            _refresh_showapi_values()

        def _on_showapi_right_click(event):
            _menu = tk.Menu(showapi_combo, tearoff=0)
            _vals = list(showapi_combo["values"])
            if not _vals:
                _menu.add_command(label="（无条目可删）", state="disabled")
            else:
                for _k in _vals:
                    _menu.add_command(label="删除：" + _k, command=lambda kk=_k: _delete_showapi(kk))
                _menu.add_separator()
                _menu.add_command(label="清空历史", command=_reset_showapi)
            _menu.tk_popup(event.x_root, event.y_root)

        _refresh_showapi_values()
        showapi_combo.bind("<<ComboboxSelected>>", _on_showapi_select)
        showapi_combo.bind("<Button-3>", _on_showapi_right_click)

        ttk.Label(frame, text="ShowAPI Base URL:").grid(row=9, column=0, sticky=tk.W, pady=5)
        showapi_base_var = tk.StringVar(value=current_config.get("showapi_base", "https://route.showapi.com"))
        ttk.Entry(frame, textvariable=showapi_base_var, width=50).grid(row=9, column=1, sticky=tk.EW, padx=(5, 0))

        ttk.Label(frame, text="启用验证:").grid(row=10, column=0, sticky=tk.W, pady=5)
        showapi_enabled_var = tk.BooleanVar(value=current_config.get("showapi_enabled", True))
        ttk.Checkbutton(frame, variable=showapi_enabled_var).grid(row=10, column=1, sticky=tk.W, padx=(5, 0))

        def show_help():
            help_win = tk.Toplevel(dialog)
            help_win.title("设置说明")
            help_win.geometry("580x540")
            help_win.resizable(True, True)
            help_win.transient(dialog)
            hf = ttk.Frame(help_win, padding=15)
            hf.pack(fill=tk.BOTH, expand=True)
            txt = tk.Text(hf, wrap=tk.WORD, font=("Microsoft YaHei", 10))
            help_text = """【API 设置说明】

1. API 地址
OpenAI 兼容服务的 base_url。SiliconFlow 填 https://api.siliconflow.cn/v1，OpenAI 官方填 https://api.openai.com/v1，也可填任意兼容服务。

2. API Key
留空则使用本地 OCR（EasyOCR，离线）；填写则使用 AI 视觉识别（需联网、更准确）。

3. 显示/隐藏 Key
切换 API Key 明文 / 密文显示。

4. 模型
必须选择支持图像的视觉模型（如 Qwen/Qwen2.5-VL-72B-Instruct）。
纯文本模型（如 Qwen3.5-9B）看不到图片会瞎编。
下拉列表右键可删除某条推荐 / 历史模型，或点「恢复默认列表」。

5. 工作目录
图片选择的默认打开目录。

6. 模型目录
EasyOCR 模型文件存放目录，首次使用需联网下载约 50MB。

7. ShowAPI AppKey
万维易源（showapi.com）应用标识，用于国药准字验证。

8. ShowAPI Secret
签名密钥，可选。留空则只用 AppKey 简单模式调用；填写则启用签名（更规范安全）。

9. ShowAPI 密钥历史
密钥栏下拉记忆已用过的 AppKey + Secret 配对，选择自动回填，右键可删除。

10. 按钮
测试连接：验证 API Key 与模型是否可用。
保存：写入配置并关闭。  取消：放弃修改。
"""
            txt.insert(tk.END, help_text)
            txt.config(state=tk.DISABLED)
            txt.pack(fill=tk.BOTH, expand=True)
            ttk.Button(hf, text="关闭", command=help_win.destroy).pack(pady=10)
        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=11, column=0, columnspan=3, pady=10)

        def _browse_dir(var):
            d = filedialog.askdirectory(title="选择目录", initialdir=var.get() or os.path.expanduser("~"))
            if d:
                var.set(d)

        def on_save():
            _model = model_var.get().strip() or "gpt-4o"
            _hist = list(current_config.get("model_history", []))
            if _model and _model not in _hist:
                _hist.insert(0, _model)
                current_config["model_history"] = _hist[:15]
            _k = showapi_appkey_var.get().strip()
            _s = showapi_secret_var.get().strip()
            _accounts = [a for a in current_config.get("showapi_accounts", []) if a.get("appkey") != _k]
            if _k:
                _accounts.insert(0, {"appkey": _k, "secret": _s})
            current_config["showapi_accounts"] = _accounts[:10]
            self.result = {
                "base_url": base_url_var.get().strip(),
                "api_key": api_key_var.get().strip(),
                "model": _model,
                "work_dir": work_dir_var.get().strip(),
                "model_dir": model_dir_var.get().strip(),
                "output_dir": current_config.get("output_dir", ""),
                "model_history": current_config.get("model_history", []),
                "model_removed": current_config.get("model_removed", []),
                "showapi_appkey": showapi_appkey_var.get().strip(),
                "showapi_secret": showapi_secret_var.get().strip(),
                "showapi_base": showapi_base_var.get().strip(),
                "showapi_enabled": showapi_enabled_var.get(),
            }
            save_config(current_config)
            dialog.destroy()

        def on_test():
            self._test_connection(
                base_url_var.get().strip(),
                api_key_var.get().strip(),
                model_var.get().strip() or "gpt-4o",
            )

        ttk.Button(btn_frame, text="测试连接", command=on_test).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="保存", command=on_save).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="取消", command=dialog.destroy).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="帮助", command=show_help).pack(side=tk.RIGHT, padx=5)

        frame.columnconfigure(1, weight=1)

        dialog.wait_window()

    def _test_connection(self, base_url, api_key, model):
        if not api_key:
            messagebox.showwarning("提示", "请先输入 API Key")
            return
        self.status_label.config(text="正在测试连接…")
        def _run():
            try:
                from openai import OpenAI
                client = OpenAI(base_url=base_url, api_key=api_key, timeout=30)
                response = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": "返回ok"}],
                    max_tokens=5,
                )
                self.root.after(0, lambda: (
                    self.status_label.config(text="连接成功"),
                    messagebox.showinfo("成功", f"连接成功！\n模型: {model}\n返回: {response.choices[0].message.content}")
                ))
            except Exception as e:
                self.root.after(0, lambda: (
                    self.status_label.config(text="连接失败"),
                    messagebox.showerror("连接失败", str(e))
                ))
        threading.Thread(target=_run, daemon=True).start()
def main():
    root = tk.Tk()
    app = MedicineOCRApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
