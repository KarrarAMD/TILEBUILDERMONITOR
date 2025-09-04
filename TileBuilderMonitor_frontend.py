import json
import re
from pathlib import Path
import os
import signal
import subprocess
import shlex
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk


class TileBuilderMonitorApp:
    def __init__(self, master=None):
        self.root = master or tk.Tk()
        # Window sizing
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        w = int(sw * 1)
        h = int(sh * 1)
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.root.minsize(800, 400)
        self.root.title("TileBuilder Monitor")

        # Close actions
        self.root.protocol("WM_DELETE_WINDOW", self._shutdown)
        self.root.bind_all("<Control-z>", lambda e: self._shutdown())
        self.root.bind_all("<Control-c>", lambda e: self._shutdown())

        # Data containers
        # Default to cutting off (no wrapping) unless user switches menu to Wrap
        self.wrap_enabled = False
        self.records = []
        self.item_to_records = {}
        self.right_item_to_record = {}

        # UI build & signals
        self._setup_signals()
        self._build_ui()

        # Open column interaction state
        self._hover_open_row = None
        self._pressed_rows = set()

        # Load initial data
        self.records = self._load_json_records()
        self._populate_grouped(self.records)

    def _build_ui(self):
        # Menubar with "Display" dropdown
        # Default selection is now "Cut off"
        self.display_var = tk.StringVar(value="Cut off")
        menubar = tk.Menu(self.root)
        display_menu = tk.Menu(menubar, tearoff=0)
        display_menu.add_radiobutton(
            label="Wrap to new line",
            variable=self.display_var,
            value="Wrap to new line",
            command=self._on_display_change,
        )
        display_menu.add_radiobutton(
            label="Cut off",
            variable=self.display_var,
            value="Cut off",
            command=self._on_display_change,
        )
        menubar.add_cascade(label="Display", menu=display_menu)
        self.root.config(menu=menubar)

        # Main paned layout: left = directories, right = runs table
        main = ttk.Panedwindow(self.root, orient=tk.HORIZONTAL)
        main.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=6, pady=6)

        left_frame = ttk.Frame(main)
        right_frame = ttk.Frame(main)
        main.add(left_frame, weight=2)
        main.add(right_frame, weight=3)

        # Styles and fonts
        self.left_style_name = "TB.Left.Treeview"
        self.right_style_name = "TB.Right.Treeview"
        self.style = ttk.Style(self.root)
        # Optional: ensure a theme that honors row background colors
        try:
            self.style.theme_use("clam")
        except tk.TclError:
            pass
        self.row_font = tkfont.nametofont("TkDefaultFont")
        self.style.configure(self.left_style_name, font=self.row_font, rowheight=24)
        self.style.configure(self.right_style_name, font=self.row_font, rowheight=24)

        # LEFT: directories-only tree (no Running/Failed columns here)
        self.tree_left = ttk.Treeview(
            left_frame,
            columns=(),
            show="tree",  # only the tree column
            height=18,
            style=self.left_style_name,
        )
        self.tree_left.heading("#0", text="Directory")
        self.tree_left.column("#0", width=550, anchor=tk.W)

        # Tag used to highlight FLOW DIRECTORY rows
        self.tree_left.tag_configure("flow", background="#a0b5cc")  # light blue

        vsb_l = ttk.Scrollbar(left_frame, orient="vertical", command=self.tree_left.yview)
        hsb_l = ttk.Scrollbar(left_frame, orient="horizontal", command=self.tree_left.xview)
        self.tree_left.configure(yscrollcommand=vsb_l.set, xscrollcommand=hsb_l.set)

        self.tree_left.grid(row=0, column=0, sticky="nsew")
        vsb_l.grid(row=0, column=1, sticky="ns")
        hsb_l.grid(row=1, column=0, sticky="ew")

        left_frame.rowconfigure(0, weight=1)
        left_frame.columnconfigure(0, weight=1)

        # selection updates right table
        self.tree_left.bind("<<TreeviewSelect>>", self._on_left_select)
        # open details on double-click/Enter
        self.tree_left.bind("<Double-1>", self._on_left_activate)
        self.tree_left.bind("<Return>", self._on_left_activate)

        # RIGHT: runs table (shows run directories with Running/Failed + Open Xterm action)
        columns = ("RUN_DIR", "RUNNING_TARGETS", "FAILED_TARGETS", "OPEN_XTERM")
        self.right_columns = list(columns)
        self.tree_right = ttk.Treeview(
            right_frame,
            columns=columns,
            show="headings",
            height=18,
            style=self.right_style_name,
        )
        self.tree_right.heading("RUN_DIR", text="Run Directory")
        self.tree_right.heading("RUNNING_TARGETS", text="Running Targets")
        self.tree_right.heading("FAILED_TARGETS", text="Failed Targets")
        self.tree_right.heading("OPEN_XTERM", text="Open Xterm")
        self.tree_right.column("RUN_DIR", width=500, anchor=tk.W)
        self.tree_right.column("RUNNING_TARGETS", width=180, anchor=tk.W)
        self.tree_right.column("FAILED_TARGETS", width=180, anchor=tk.W)
        self.tree_right.column("OPEN_XTERM", width=120, anchor=tk.CENTER, stretch=False)

        vsb_r = ttk.Scrollbar(right_frame, orient="vertical", command=self.tree_right.yview)
        hsb_r = ttk.Scrollbar(right_frame, orient="horizontal", command=self.tree_right.xview)
        self.tree_right.configure(yscrollcommand=vsb_r.set, xscrollcommand=hsb_r.set)

        self.tree_right.grid(row=0, column=0, sticky="nsew")
        vsb_r.grid(row=0, column=1, sticky="ns")
        hsb_r.grid(row=1, column=0, sticky="ew")

        right_frame.rowconfigure(0, weight=1)
        right_frame.columnconfigure(0, weight=1)

        # open details from right table on double-click/Enter
        self.tree_right.bind("<Double-1>", self._on_right_activate)
        self.tree_right.bind("<Return>", self._on_right_activate)
        # New bindings for launching terminals
        self.tree_right.bind("<Button-1>", self._on_right_click, add=True)
        self.tree_right.bind("<Motion>", self._on_right_motion, add=True)

    def _on_display_change(self, event=None):
        self.wrap_enabled = (self.display_var.get() == "Wrap to new line")
        self._populate_grouped(self.records)

    def _load_json_records(self):
        # Load tmp.json next to this script
        script_dir = Path(__file__).resolve().parent
        path = script_dir / "tmp_TileBuilderMonitor/tmp.json"
        try:
            text = path.read_text()
        except Exception as e:
            print(f"[ERROR] Failed to read {path} (cwd={Path.cwd()}): {e}")
            return []

        # Strip // comments
        lines = [ln for ln in text.splitlines() if not ln.strip().startswith("//")]
        cleaned = "\n".join(lines).strip()
        if not cleaned:
            return []

        # Try standard JSON first
        try:
            loaded = json.loads(cleaned)
            if isinstance(loaded, dict):
                return [loaded]
            if isinstance(loaded, list):
                return loaded
        except json.JSONDecodeError:
            pass

        # Fallback: parse concatenated objects
        records = []
        dec = json.JSONDecoder()
        idx = 0
        n = len(cleaned)
        while idx < n:
            while idx < n and cleaned[idx].isspace():
                idx += 1
            if idx >= n:
                break
            try:
                obj, end = dec.raw_decode(cleaned, idx)
                if isinstance(obj, dict):
                    records.append(obj)
                idx = end
            except json.JSONDecodeError:
                idx += 1
        return records

    def _wrap_text(self, text: str, max_px: int) -> str:
        if not self.wrap_enabled:
            return str(text)
        lines = []
        for para in str(text).splitlines() or [""]:
            tokens = re.split(r"([/\s,_-])", para)
            cur = ""
            for tok in tokens:
                if tok == "":
                    continue
                trial = cur + tok
                # measure with Treeview font
                if self.row_font.measure(trial) <= max_px or cur == "":
                    cur = trial
                else:
                    lines.append(cur)
                    cur = tok.lstrip()
            lines.append(cur)
        return "\n".join(lines)

    def _split_for_left(self, text: str, max_px: int) -> list[str]:
        """
        For the left Treeview (which can't render multi-line cells), return a list of
        visual lines. In wrap mode, split the text to fit max_px; in cut-off mode,
        return a single-element list.
        """
        if not self.wrap_enabled:
            return [str(text)]
        wrapped = self._wrap_text(text, max_px)
        return wrapped.splitlines() if wrapped else [""]

    def _suffix_from_last_common_dir(self, parent_path: str, child_path: str) -> str:
        p_parts = [p for p in parent_path.split('/') if p]
        c_parts = [p for p in child_path.split('/') if p]
        if not p_parts or not c_parts:
            return child_path
        i = 0
        while i < len(p_parts) and i < len(c_parts) and p_parts[i] == c_parts[i]:
            i += 1
        if i == 0:
            return child_path
        suffix_parts = c_parts[i - 1:]
        return "/" + "/".join(suffix_parts)

    def _populate_grouped(self, records):
        # Clear trees and mapping
        for row in self.tree_left.get_children():
            self.tree_left.delete(row)
        for row in self.tree_right.get_children():
            self.tree_right.delete(row)
        self.item_to_records.clear()
        self.right_item_to_record.clear()

        # Column widths (pixels)
        left_w = int(self.tree_left.column("#0", option="width"))
        right_dir_w = int(self.tree_right.column("RUN_DIR", option="width"))
        right_run_w = int(self.tree_right.column("RUNNING_TARGETS", option="width"))
        right_fail_w = int(self.tree_right.column("FAILED_TARGETS", option="width"))
        right_open_w = int(self.tree_right.column("OPEN_XTERM", option="width"))

        # Group by FLOW_DIR (always ensure a parent exists)
        groups: dict[str, list[dict]] = {}
        for rec in records:
            fd = rec.get("FLOW_DIR") or "(no FLOW_DIR)"
            groups.setdefault(fd, []).append(rec)

        # Insert parents and children on left, expand all
        for flow_dir in sorted(groups.keys()):
            recs = groups[flow_dir]

            parent_label = f"FLOW DIRECTORY: {flow_dir}"
            parent_lines = self._split_for_left(parent_label, left_w)
            parent_id = self.tree_left.insert("", "end", text=parent_lines[0], tags=("flow",))
            self.item_to_records[parent_id] = recs
            for cont in parent_lines[1:]:
                cont_id = self.tree_left.insert(parent_id, "end", text=cont, tags=("flow",))
                self.item_to_records[cont_id] = recs

            for idx, r in enumerate(recs, start=1):
                basedir = r.get("basedir", "(no basedir)")
                child_label = self._suffix_from_last_common_dir(flow_dir, basedir) if flow_dir != "(no FLOW_DIR)" else basedir
                child_text = f"RUN DIRECTORY {idx}: {child_label}"
                child_lines = self._split_for_left(child_text, left_w)
                child_id = self.tree_left.insert(parent_id, "end", text=child_lines[0])
                self.item_to_records[child_id] = r
                for cont in child_lines[1:]:
                    sib_id = self.tree_left.insert(parent_id, "end", text=cont)
                    self.item_to_records[sib_id] = r

            self.tree_left.item(parent_id, open=True)

        # Initial right pane: show runs for first parent (if any)
        first = next(iter(self.tree_left.get_children()), None)
        if first:
            self.tree_left.selection_set(first)
            self._refresh_right_for_item(first, right_dir_w, right_run_w, right_fail_w, right_open_w)

        # Row height settings remain
        self.style.configure(self.left_style_name, rowheight=24)
        if not self.wrap_enabled:
            self.style.configure(self.right_style_name, rowheight=24)

    def _on_left_select(self, event=None):
        # Recompute right pane for current selection
        sel = self.tree_left.selection()
        if not sel:
            return
        right_dir_w = int(self.tree_right.column("RUN_DIR", option="width"))
        right_run_w = int(self.tree_right.column("RUNNING_TARGETS", option="width"))
        right_fail_w = int(self.tree_right.column("FAILED_TARGETS", option="width"))
        right_open_w = int(self.tree_right.column("OPEN_XTERM", option="width"))
        self._refresh_right_for_item(sel[0], right_dir_w, right_run_w, right_fail_w, right_open_w)

    def _refresh_right_for_item(self, item_id, dir_w, run_w, fail_w, open_w):  # open_w reserved
        # Clear existing
        for row in self.tree_right.get_children():
            self.tree_right.delete(row)
        self.right_item_to_record.clear()

        payload = self.item_to_records.get(item_id)
        if payload is None:
            return

        runs = payload if isinstance(payload, list) else [payload]

        max_lines_right = 1
        cur = item_id
        while True:
            parent = self.tree_left.parent(cur)
            if not parent:
                parent_flow_text = self.tree_left.item(cur, "text")
                break
            cur = parent
        if parent_flow_text.startswith("FLOW DIRECTORY: "):
            flow_dir = parent_flow_text[len("FLOW DIRECTORY: "):].replace("\n", " ")
        else:
            flow_dir = "(no FLOW_DIR)"

        for r in runs:
            basedir = r.get("basedir", "(no basedir)")
            child_label = self._suffix_from_last_common_dir(flow_dir, basedir) if flow_dir != "(no FLOW_DIR)" else basedir
            run_dir_out = self._wrap_text(child_label, dir_w)

            running = r.get("RUNNING_TARGETS", [])
            failed = r.get("FAILED_TARGETS", [])
            running_str = ", ".join(map(str, running)) if isinstance(running, (list, tuple)) else str(running or "")
            failed_str = ", ".join(map(str, failed)) if isinstance(failed, (list, tuple)) else str(failed or "")
            running_out = self._wrap_text(running_str, run_w)
            failed_out = self._wrap_text(failed_str, fail_w)

            max_lines_right = max(
                max_lines_right,
                run_dir_out.count("\n") + 1,
                running_out.count("\n") + 1,
                failed_out.count("\n") + 1,
            )
            # Initial Open column label styled like a button
            row_id = self.tree_right.insert("", "end", values=(run_dir_out, running_out, failed_out, "[ Open ]"))
            self.right_item_to_record[row_id] = r  # map right row to its record

        if self.wrap_enabled:
            line_px = self.row_font.metrics("linespace")
            self.style.configure(self.right_style_name, rowheight=max(24, int(max_lines_right * (line_px + 2))))
        else:
            self.style.configure(self.right_style_name, rowheight=24)

    # NEW: open-details handlers and helpers
    def _on_left_activate(self, event=None):
        """Open run details when a run item is double-clicked or Enter is pressed on the left tree."""
        iid = self.tree_left.identify_row(event.y) if event is not None else None
        if not iid:
            sel = self.tree_left.selection()
            iid = sel[0] if sel else None
        if not iid:
            return
        payload = self.item_to_records.get(iid)
        if isinstance(payload, dict):  # only open for run rows
            self._open_run_detail(payload)

    def _on_right_activate(self, event=None):
        """Open run details when a row is double-clicked or Enter is pressed on the right table."""
        iid = self.tree_right.identify_row(event.y) if event is not None else None
        if not iid:
            sel = self.tree_right.selection()
            iid = sel[0] if sel else None
        if not iid:
            return
        rec = self.right_item_to_record.get(iid)
        if isinstance(rec, dict):
            self._open_run_detail(rec)

    def _stringify_value(self, v):
        if v is None:
            return ""
        if isinstance(v, (str, int, float, bool)):
            return str(v)
        try:
            return json.dumps(v, ensure_ascii=False)
        except Exception:
            return str(v)

    def _wrap_lines_for_table(self, text: str, max_px: int, font: tkfont.Font) -> list[str]:
        """
        Wrap text into a list of visual lines that fit within max_px using the given font.
        Always wraps (independent of the Display menu).
        Splits smartly on path separators, whitespace, underscores, hyphens, commas, and JSON punctuation.
        """
        s = "" if text is None else str(text)
        if not s:
            return [""]
        # Split existing newlines first; wrap each paragraph independently
        paragraphs = s.splitlines() or [""]
        out_lines: list[str] = []
        # Break tokens on separators to keep paths and JSON readable
        splitter = re.compile(r"([/\s,._\-\{\}\[\]:])")
        for para in paragraphs:
            tokens = splitter.split(para)
            cur = ""
            for tok in tokens:
                if tok == "":
                    continue
                trial = cur + tok
                if font.measure(trial) <= max_px or cur == "":
                    cur = trial
                else:
                    out_lines.append(cur)
                    cur = tok.lstrip()
            out_lines.append(cur)
        return out_lines or [""]

    def _open_run_detail(self, rec: dict):
        """Open a new window displaying the record as a two-column table: Attribute | Value, with wrapping."""
        win = tk.Toplevel(self.root)
        win.title("Run details")
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        w, h = int(sw * 0.6), int(sh * 0.6)
        x, y = (sw - w) // 2, (sh - h) // 2
        win.geometry(f"{w}x{h}+{x}+{y}")

        frame = ttk.Frame(win, padding=8)
        frame.pack(fill=tk.BOTH, expand=True)

        tree = ttk.Treeview(frame, columns=("ATTRIBUTE", "VALUE"), show="headings", height=20)
        tree.heading("ATTRIBUTE", text="Attribute")
        tree.heading("VALUE", text="Value")
        # Initial column widths; user can resize, but we wrap based on these at open time
        tree.column("ATTRIBUTE", width=250, anchor=tk.W)
        tree.column("VALUE", width=800, anchor=tk.W)

        vsb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        hsb = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        # Use the default font for measuring
        row_font = tkfont.nametofont("TkDefaultFont")
        key_w = int(tree.column("ATTRIBUTE", option="width"))
        val_w = int(tree.column("VALUE", option="width"))

        # Insert each attribute with wrapped continuation rows if needed
        for k, v in rec.items():
            k_lines = self._wrap_lines_for_table(k, key_w, row_font)
            v_str = self._stringify_value(v)
            v_lines = self._wrap_lines_for_table(v_str, val_w, row_font)
            rows = max(len(k_lines), len(v_lines))
            for i in range(rows):
                k_cell = k_lines[i] if i < len(k_lines) else ""
                v_cell = v_lines[i] if i < len(v_lines) else ""
                tree.insert("", "end", values=(k_cell, v_cell))

    def _setup_signals(self):
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGTSTP, getattr(signal, "SIGQUIT", None)):
            if sig is None:
                continue
            try:
                signal.signal(sig, self._on_signal)
            except Exception:
                pass

    def _on_signal(self, signum, frame):
        self._shutdown()

    def _shutdown(self):
        try:
            self.root.destroy()
        except Exception:
            pass
        os._exit(0)

    def run(self):
        self.root.mainloop()

    # --- New: Xterm launching support ---
    def _open_run_term(self, run_dir: str, title: str | None = None):
        if not run_dir:
            return
        run_path = Path(run_dir)
        if not run_path.is_dir():
            print(f"[WARN] Cannot open terminal: directory missing: {run_dir}")
            return
        title = title or run_path.name
        title_arg = f"-T {shlex.quote(title)}" if title else ""
        cmd = f"cd {shlex.quote(str(run_path))}; TileBuilderTerm {title_arg}".strip()
        try:
            subprocess.Popen(["tcsh", "-c", cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            print(f"[ERROR] Failed to launch terminal for {run_dir}: {e}")

    def _on_right_click(self, event):
        row_id = self.tree_right.identify_row(event.y)
        if not row_id:
            return
        col = self.tree_right.identify_column(event.x)
        try:
            col_index = int(col.lstrip('#')) - 1
        except ValueError:
            return
        if 0 <= col_index < len(self.right_columns) and self.right_columns[col_index] == 'OPEN_XTERM':
            rec = self.right_item_to_record.get(row_id)
            if isinstance(rec, dict):
                basedir = rec.get('basedir')
                self._open_run_term(basedir)
                # Visual pressed effect
                self._pressed_rows.add(row_id)
                self._set_open_label(row_id, 'pressed')
                # schedule revert after short delay
                self.root.after(180, lambda rid=row_id: self._end_press(rid))
                return 'break'

    def _on_right_motion(self, event):
        row_id = self.tree_right.identify_row(event.y)
        col = self.tree_right.identify_column(event.x)
        try:
            idx = int(col.lstrip('#')) - 1
        except ValueError:
            self.tree_right.config(cursor='')
            return
        if row_id and 0 <= idx < len(self.right_columns) and self.right_columns[idx] == 'OPEN_XTERM':
            self.tree_right.config(cursor='hand2')
            # manage hover label changes
            if row_id != self._hover_open_row and row_id not in self._pressed_rows:
                # revert previous hover if any
                if self._hover_open_row and self._hover_open_row not in self._pressed_rows:
                    self._set_open_label(self._hover_open_row, 'normal')
                self._set_open_label(row_id, 'hover')
                self._hover_open_row = row_id
        else:
            self.tree_right.config(cursor='')
            # leaving hover area
            if self._hover_open_row and self._hover_open_row not in self._pressed_rows:
                self._set_open_label(self._hover_open_row, 'normal')
            self._hover_open_row = None

    # --- Helper methods for Open column button states ---
    def _set_open_label(self, row_id: str, state: str):
        try:
            vals = list(self.tree_right.item(row_id, 'values'))
            if len(vals) < 4:
                return
            if state == 'normal':
                vals[3] = '[ Open ]'
                self.tree_right.item(row_id, values=vals, tags=())
            elif state == 'hover':
                vals[3] = '[Open]'
                self.tree_right.item(row_id, values=vals, tags=('open_hover',))
            elif state == 'pressed':
                vals[3] = '[OPEN]'
                self.tree_right.item(row_id, values=vals, tags=('open_pressed',))
            # configure tags (once only is fine)
            self.tree_right.tag_configure('open_hover', background='#e2f3ff')
            self.tree_right.tag_configure('open_pressed', background='#c8e7ff')
        except Exception:
            pass

    def _end_press(self, row_id: str):
        if row_id in self._pressed_rows:
            self._pressed_rows.discard(row_id)
        # keep hover style if still hovered
        if row_id == self._hover_open_row:
            self._set_open_label(row_id, 'hover')
        else:
            self._set_open_label(row_id, 'normal')


if __name__ == "__main__":
    TileBuilderMonitorApp().run()