#!/usr/bin/env python3
import json
from pathlib import Path
from tkinter import *
import tkinter as tk
from tkinter import messagebox, scrolledtext

JSON_PATH = Path("tmp_test.json")

def load_runs(path):
    text = path.read_text() if path.exists() else ""
    if not text.strip():
        return []
    # if file is a proper JSON array
    if text.lstrip().startswith("["):
        return json.loads(text)
    # otherwise try to wrap concatenated objects into an array
    wrapped = "[" + text.replace("}\n{", "},\n{").replace("}{", "},{") + "]"
    return json.loads(wrapped)

class SimpleViewer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Basedir Viewer")
        self.geometry("800x400")
        self.create_widgets()
        self.load()

    def create_widgets(self):
        top = tk.Frame(self)
        top.pack(fill="x", padx=6, pady=6)
        self.refresh_btn = tk.Button(top, text="Refresh", command=self.load)
        self.refresh_btn.pack(side="left")
        self.count_label = tk.Label(top, text="")
        self.count_label.pack(side="left", padx=10)

        self.listbox = tk.Listbox(self, activestyle="none")
        self.listbox.pack(fill="both", expand=True, padx=6, pady=6)
        self.listbox.bind("<Double-1>", self.on_double)

        # small info area
        self.info = tk.Label(self, text="Double-click a line to view/copy full basedir", anchor="w")
        self.info.pack(fill="x", padx=6, pady=(0,6))

    def load(self):
        try:
            runs = load_runs(JSON_PATH)
        except Exception as e:
            messagebox.showerror("Error loading JSON", str(e))
            runs = []
        self.listbox.delete(0, tk.END)
        for r in runs:
            bd = r.get("basedir", "")
            # show only the last path component (short) for compactness:
            short = bd.split("/")[-1] if bd else "(no basedir)"
            self.listbox.insert(tk.END, short)
        self._runs = runs
        self.count_label.config(text=f"{len(runs)} runs")

    def on_double(self, event):
        sel = self.listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        run = self._runs[idx]
        basedir = run.get("basedir", "(no basedir)")
        # show a small popup with the full basedir and copy to clipboard
        self.clipboard_clear()
        self.clipboard_append(basedir)
        messagebox.showinfo("Basedir (copied to clipboard)", basedir)

if __name__ == "__main__":
    app = SimpleViewer()
    app.mainloop()