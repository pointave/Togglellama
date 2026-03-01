import pystray
from PIL import Image, ImageDraw
import subprocess
import time
import threading
from pathlib import Path
import json
import tkinter as tk
from tkinter import messagebox, filedialog
import customtkinter as ctk
import requests
import webbrowser
import sys
import os
import psutil
import signal

# ── Global CustomTkinter defaults ───────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")


def _make_window_foreground(win: ctk.CTk | ctk.CTkToplevel):
    """Force a window to the foreground and grab input focus reliably on Windows."""
    win.lift()
    win.attributes("-topmost", True)
    win.focus_force()
    win.after(150, lambda: win.attributes("-topmost", False))


# ── Reusable styled widgets ──────────────────────────────────────────────────

ACCENT   = "#4f8ef7"
ACCENT2  = "#2d6fd4"
BG_DARK  = "#1a1a2e"
BG_MID   = "#16213e"
BG_CARD  = "#0f3460"
TEXT     = "#e0e0e0"
TEXT_DIM = "#8a8aaa"
SUCCESS  = "#43c59e"
DANGER   = "#e05c5c"

FONT_TITLE  = ("Segoe UI", 18, "bold")
FONT_HEADER = ("Segoe UI", 12, "bold")
FONT_BODY   = ("Segoe UI", 11)
FONT_SMALL  = ("Segoe UI", 9)


def _section_label(parent, text):
    frm = ctk.CTkFrame(parent, fg_color="transparent")
    frm.pack(fill="x", padx=20, pady=(14, 2))
    ctk.CTkLabel(frm, text=text, font=FONT_HEADER,
                 text_color=ACCENT).pack(anchor="w")
    ctk.CTkFrame(frm, height=1, fg_color=ACCENT2).pack(fill="x", pady=(3, 0))


def _row(parent, label_text, widget_factory, pady=4, height=36):
    frm = ctk.CTkFrame(parent, fg_color="transparent")
    frm.pack(fill="x", padx=24, pady=pady)
    ctk.CTkLabel(frm, text=label_text, font=FONT_BODY,
                 text_color=TEXT, width=180, anchor="w").pack(side="left")
    widget = widget_factory(frm, height=height)
    widget.pack(side="left", fill="x", expand=True)
    return widget


# ─────────────────────────────────────────────────────────────────────────────
class LlamaCppTray:
    def __init__(self):
        self.bat_file                       = Path(__file__).parent / "Llamacpp.bat"
        self.config_file                    = Path(__file__).parent / "llamacpp_config.json"
        self.server_running                 = False
        self.embedding_server_running       = False
        self.monitor_thread                 = None
        self.last_click_time                = 0
        self.double_click_threshold         = 0.5
        self.click_count                    = 0
        self.click_timer                    = None
        self.running                        = False
        self.embedding_server_check_counter = 0
        self.load_config()

    # ── signal / lifecycle ──────────────────────────────────────────────────
    def signal_handler(self, signum, frame):
        print("\nReceived interrupt signal. Shutting down...")
        self.running = False
        if self.server_running:
            try:
                subprocess.run(['taskkill', '/IM', 'llama-server.exe', '/T', '/F'],
                               shell=True, check=True)
            except Exception:
                pass
        if hasattr(self, 'icon') and self.icon:
            self.icon.stop()
        sys.exit(0)

    # ── config ──────────────────────────────────────────────────────────────
    def load_config(self):
        defaults = {
            "context_window": 32000,
            "port": 8080,
            "models_dir": "",
            "llamacpp_dir": "",
            "use_fit": False,
            "no_mmproj": False,
            "ctk_q8": False,
            "ctv_q8": False,
            "thinking": "off",
            "max_models": 1,
            "flags": [],
            "theme": "dark",
            "embedding_model": "",
            "embedding_port": 8082,
            "embedding_flags": [],
            "flash_attn": False,
        }
        try:
            if self.config_file.exists():
                with open(self.config_file, 'r') as f:
                    loaded = json.load(f)
                self.config = {**defaults, **loaded}
            else:
                self.config = defaults
        except Exception:
            self.config = defaults

    def save_config(self):
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=2)
            return True
        except Exception:
            return False

    # ── server checks ───────────────────────────────────────────────────────
    def check_server_status(self):
        try:
            result = subprocess.run(
                ['tasklist', '/FI', 'IMAGENAME eq llama-server.exe'],
                capture_output=True, text=True, shell=True)
            return 'llama-server.exe' in result.stdout
        except Exception:
            return False

    def check_embedding_server_status(self):
        try:
            result = subprocess.run(
                ['tasklist', '/FI', 'IMAGENAME eq llama-server.exe', '/V'],
                capture_output=True, text=True, shell=True)
            for line in result.stdout.split('\n'):
                if (f":{self.config['embedding_port']}" in line
                        or 'embedding' in line.lower()):
                    return True
            return False
        except Exception:
            return False

    def update_status(self):
        was_running           = self.server_running
        was_embedding_running = self.embedding_server_running
        self.server_running           = self.check_server_status()
        self.embedding_server_running = self.check_embedding_server_status()
        if was_running != self.server_running or was_embedding_running != self.embedding_server_running:
            self.update_icon()

    def update_icon(self):
        if self.server_running:
            self.icon.icon  = self.load_icon(color='green')
            self.icon.title = "Llama.cpp - Running"
        else:
            self.icon.icon  = self.load_icon(color='red')
            self.icon.title = "Llama.cpp - Stopped"

    # ── icon helpers ────────────────────────────────────────────────────────
    def create_image(self, color='red'):
        image = Image.new('RGB', (64, 64), color=color)
        dc = ImageDraw.Draw(image)
        dc.rectangle([16, 16, 48, 48], fill='white')
        return image

    def load_icon(self, color='red'):
        icon_path = Path(__file__).parent / "llamacpp_tray.ico"
        if icon_path.exists() and icon_path.stat().st_size > 0:
            try:
                base = Image.open(icon_path).convert('RGBA')
                if color == 'red':
                    overlay = Image.new('RGBA', base.size, (255, 0, 0, 50))
                    return Image.alpha_composite(base, overlay)
                return base
            except Exception:
                pass
        return self.create_image(color)

    # ── setup check ─────────────────────────────────────────────────────────
    def check_setup_required(self):
        for field in ('models_dir', 'llamacpp_dir'):
            if not self.config.get(field, '').strip():
                return True
        return False

    # ════════════════════════════════════════════════════════════════════════
    #  SETUP WIZARD
    # ════════════════════════════════════════════════════════════════════════
    def show_setup_wizard(self):
        root = ctk.CTk()
        root.title("Llama.cpp Tray — First-Time Setup")
        root.geometry("560x720")
        root.resizable(False, False)
        root.configure(fg_color=BG_DARK)

        root.update_idletasks()
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        root.geometry(f"560x720+{(sw-560)//2}+{(sh-720)//2}")
        _make_window_foreground(root)

        header = ctk.CTkFrame(root, fg_color=BG_CARD, corner_radius=0, height=72)
        header.pack(fill="x")
        header.pack_propagate(False)
        ctk.CTkLabel(header, text="⚙  Welcome to Llama.cpp Tray",
                     font=("Segoe UI", 17, "bold"), text_color=ACCENT).pack(
            side="left", padx=24, pady=16)

        scroll = ctk.CTkScrollableFrame(root, fg_color=BG_DARK)
        scroll.pack(fill="both", expand=True, padx=0, pady=0)

        ctk.CTkLabel(scroll,
                     text="Configure the required paths before you can start the server.\n"
                          "You can update everything later from the Configuration menu.",
                     font=FONT_BODY, text_color=TEXT_DIM, wraplength=500,
                     justify="left").pack(anchor="w", padx=24, pady=(12, 4))

        def browse_dir_row(parent, label, initial=""):
            _section_label(parent, label)
            frm = ctk.CTkFrame(parent, fg_color="transparent")
            frm.pack(fill="x", padx=24, pady=(2, 0))
            var = ctk.StringVar(value=initial)
            entry = ctk.CTkEntry(frm, textvariable=var, font=FONT_BODY,
                                 height=36, fg_color=BG_MID, border_color=ACCENT2,
                                 text_color=TEXT)
            entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

            def browse():
                d = filedialog.askdirectory(title=f"Select {label}")
                if d:
                    var.set(d)

            ctk.CTkButton(frm, text="Browse…", width=90, height=36,
                          fg_color=ACCENT2, hover_color=ACCENT,
                          command=browse).pack(side="right")
            return var

        def browse_file_row(parent, label, initial=""):
            _section_label(parent, label)
            frm = ctk.CTkFrame(parent, fg_color="transparent")
            frm.pack(fill="x", padx=24, pady=(2, 0))
            var = ctk.StringVar(value=initial)
            entry = ctk.CTkEntry(frm, textvariable=var, font=FONT_BODY,
                                 height=36, fg_color=BG_MID, border_color=ACCENT2,
                                 text_color=TEXT)
            entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

            def browse():
                f = filedialog.askopenfilename(
                    title=f"Select {label}",
                    filetypes=[("GGUF files", "*.gguf"), ("All files", "*.*")])
                if f:
                    var.set(f)

            ctk.CTkButton(frm, text="Browse…", width=90, height=36,
                          fg_color=ACCENT2, hover_color=ACCENT,
                          command=browse).pack(side="right")
            return var

        llamacpp_var  = browse_dir_row(scroll, "Llama.cpp Directory  (contains llama-server.exe)\n    Example: .../llama.cpp/build/bin/Release",
                                       self.config.get("llamacpp_dir", ""))
        models_var    = browse_dir_row(scroll, "Models Directory  (contains .gguf files)",
                                       self.config.get("models_dir", ""))
        embedding_var = browse_file_row(scroll, "Embedding Model  (optional .gguf file)",
                                        self.config.get("embedding_model", ""))

        _section_label(scroll, "Server Port")
        port_var = ctk.IntVar(value=self.config.get("port", 8080))
        port_row = ctk.CTkFrame(scroll, fg_color="transparent")
        port_row.pack(fill="x", padx=24, pady=(2, 0))
        ctk.CTkEntry(port_row, textvariable=port_var, width=120, height=36,
                     fg_color=BG_MID, border_color=ACCENT2,
                     text_color=TEXT, font=FONT_BODY).pack(side="left")
        ctk.CTkLabel(port_row, text="  default: 8080", font=FONT_SMALL,
                     text_color=TEXT_DIM).pack(side="left")

        status_var = ctk.StringVar(value="")
        status_lbl = ctk.CTkLabel(scroll, textvariable=status_var,
                                  font=FONT_SMALL, text_color=DANGER)
        status_lbl.pack(pady=(8, 0))

        btn_row = ctk.CTkFrame(scroll, fg_color="transparent")
        btn_row.pack(pady=20)

        def save_setup():
            lcpp = llamacpp_var.get().strip()
            mdir = models_var.get().strip()
            embd = embedding_var.get().strip()
            port = port_var.get()

            if not lcpp or not mdir:
                status_var.set("⚠  Please fill in both directory paths.")
                return

            server_exe = Path(lcpp) / "llama-server.exe"
            if not server_exe.exists():
                status_var.set("⚠  llama-server.exe not found in that directory.")
                return

            self.config["llamacpp_dir"] = lcpp
            self.config["models_dir"]   = mdir
            self.config["port"]         = port
            if embd:
                self.config["embedding_model"] = embd
            self.save_config()
            status_var.set("")
            messagebox.showinfo("Setup Complete",
                                "All set! Right-click the tray icon to get started.")
            root.destroy()

        def skip_setup():
            if messagebox.askyesno("Skip Setup",
                                   "Skip for now?\n\n"
                                   "You'll need to set the paths manually from the "
                                   "Configuration menu before starting the server."):
                root.destroy()

        ctk.CTkButton(btn_row, text="Save & Continue", width=160, height=40,
                      fg_color=SUCCESS, hover_color="#2fa882",
                      font=FONT_HEADER, command=save_setup).pack(side="left", padx=8)
        ctk.CTkButton(btn_row, text="Skip", width=80, height=40,
                      fg_color=BG_CARD, hover_color=BG_MID,
                      font=FONT_BODY, command=skip_setup).pack(side="left", padx=8)

        root.mainloop()

    # ════════════════════════════════════════════════════════════════════════
    #  CONFIGURATION WINDOW
    # ════════════════════════════════════════════════════════════════════════
    def show_config(self, icon=None, item=None):
        root = ctk.CTk()
        root.title("Llama.cpp — Configuration")
        root.resizable(True, True)
        root.minsize(500, 700)
        root.configure(fg_color=BG_DARK)

        root.update_idletasks()
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        margin = 50
        x_pos = sw - 620 - margin
        y_pos = max(0, sh - 900)
        root.geometry(f"620x860+{x_pos}+{y_pos}")
        root.lift()
        root.attributes("-topmost", True)
        root.focus_force()
        root.after(150, lambda: root.attributes("-topmost", False))

        hdr = ctk.CTkFrame(root, fg_color=BG_CARD, corner_radius=0, height=64)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        ctk.CTkLabel(hdr, text="⚙  Configuration",
                     font=("Segoe UI", 16, "bold"), text_color=ACCENT).pack(
            side="left", padx=20, pady=14)

        status_text = "● Running" if self.server_running else "● Stopped"
        status_col  = SUCCESS if self.server_running else DANGER
        status_pill = ctk.CTkLabel(hdr, text=status_text,
                                   font=("Segoe UI", 10, "bold"),
                                   text_color=status_col,
                                   fg_color=BG_MID, corner_radius=8,
                                   padx=10, pady=4)
        status_pill.pack(side="right", padx=20)

        scroll = ctk.CTkScrollableFrame(root, fg_color=BG_DARK)
        scroll.pack(fill="both", expand=True)

        def lentry(parent, label, var, width=None, placeholder=""):
            frm = ctk.CTkFrame(parent, fg_color="transparent")
            frm.pack(fill="x", padx=24, pady=3)
            ctk.CTkLabel(frm, text=label, font=FONT_BODY,
                         text_color=TEXT, width=200, anchor="w").pack(side="left")
            kw = dict(textvariable=var, height=34, fg_color=BG_MID,
                      border_color=ACCENT2, text_color=TEXT,
                      font=FONT_BODY, placeholder_text=placeholder)
            if width:
                kw["width"] = width
            e = ctk.CTkEntry(frm, **kw)
            e.pack(side="left", fill="x", expand=True)
            return e

        def browse_row(parent, label, var, mode="dir"):
            frm = ctk.CTkFrame(parent, fg_color="transparent")
            frm.pack(fill="x", padx=24, pady=3)
            ctk.CTkLabel(frm, text=label, font=FONT_BODY,
                         text_color=TEXT, width=200, anchor="w").pack(side="left")
            entry = ctk.CTkEntry(frm, textvariable=var, height=34,
                                 fg_color=BG_MID, border_color=ACCENT2,
                                 text_color=TEXT, font=FONT_BODY)
            entry.pack(side="left", fill="x", expand=True, padx=(0, 6))

            def browse():
                if mode == "dir":
                    d = filedialog.askdirectory(title=f"Select {label}")
                    if d:
                        var.set(d)
                else:
                    f = filedialog.askopenfilename(
                        title=f"Select {label}",
                        filetypes=[("GGUF files", "*.gguf"), ("All files", "*.*")])
                    if f:
                        var.set(f)

            ctk.CTkButton(frm, text="…", width=36, height=34,
                          fg_color=ACCENT2, hover_color=ACCENT,
                          command=browse).pack(side="right")

        # ── SECTION: Server ─────────────────────────────────────────────────
        _section_label(scroll, "Server")

        ctx_var     = ctk.IntVar(value=self.config["context_window"])
        ctx_lbl_var = ctk.StringVar(value=f"Context: {ctx_var.get():,}")

        ctx_frm = ctk.CTkFrame(scroll, fg_color="transparent")
        ctx_frm.pack(fill="x", padx=24, pady=3)
        ctk.CTkLabel(ctx_frm, text="Context Window", font=FONT_BODY,
                     text_color=TEXT, width=200, anchor="w").pack(side="left")
        slider = ctk.CTkSlider(ctx_frm, from_=1000, to=256000,
                               variable=ctx_var, width=220,
                               button_color=ACCENT, progress_color=ACCENT2,
                               command=lambda v: [ctx_var.set(int(v)),
                                                  ctx_lbl_var.set(f"Context: {int(v):,}")])
        slider.pack(side="left", padx=(0, 8))
        ctk.CTkEntry(ctx_frm, textvariable=ctx_var, width=80, height=34,
                     fg_color=BG_MID, border_color=ACCENT2,
                     text_color=TEXT, font=FONT_BODY).pack(side="left", padx=(0, 8))
        ctk.CTkLabel(ctx_frm, textvariable=ctx_lbl_var,
                     font=FONT_SMALL, text_color=TEXT_DIM, width=140).pack(side="left")

        port_var       = ctk.IntVar(value=self.config["port"])
        max_models_var = ctk.IntVar(value=self.config.get("max_models", 1))
        lentry(scroll, "Server Port",  port_var,       width=100)
        lentry(scroll, "Max Models",   max_models_var, width=100)

        fit_var       = ctk.BooleanVar(value=self.config.get("use_fit", False))
        no_mmproj_var = ctk.BooleanVar(value=self.config.get("no_mmproj", False))
        flash_attn_var = ctk.BooleanVar(value=self.config.get("flash_attn", False))
        ctk_q8_var    = ctk.BooleanVar(value=self.config.get("ctk_q8", False))
        ctv_q8_var    = ctk.BooleanVar(value=self.config.get("ctv_q8", False))
        thinking_var  = ctk.StringVar(value=self.config.get("thinking", "off"))

        toggles_frm = ctk.CTkFrame(scroll, fg_color="transparent")
        toggles_frm.pack(fill="x", padx=24, pady=3)
        ctk.CTkLabel(toggles_frm, text="Quick Flags", font=FONT_BODY,
                     text_color=TEXT, width=200, anchor="w").pack(side="left")
        ctk.CTkSwitch(toggles_frm, variable=fit_var, text="--fit",
                      font=FONT_BODY, text_color=TEXT_DIM,
                      button_color=ACCENT, progress_color=ACCENT2).pack(side="left", padx=(0, 24))
        ctk.CTkSwitch(toggles_frm, variable=no_mmproj_var, text="--no-mmproj",
                      font=FONT_BODY, text_color=TEXT_DIM,
                      button_color=ACCENT, progress_color=ACCENT2).pack(side="left", padx=(0, 24))
        ctk.CTkSwitch(toggles_frm, variable=flash_attn_var, text="--flash-attn on",
                      font=FONT_BODY, text_color=TEXT_DIM,
                      button_color=ACCENT, progress_color=ACCENT2).pack(side="left")

        kv_frm = ctk.CTkFrame(scroll, fg_color="transparent")
        kv_frm.pack(fill="x", padx=24, pady=3)
        ctk.CTkLabel(kv_frm, text="KV Cache  (q8_0)", font=FONT_BODY,
                     text_color=TEXT, width=200, anchor="w").pack(side="left")
        ctk.CTkSwitch(kv_frm, variable=ctk_q8_var, text="-ctk q8_0",
                      font=FONT_BODY, text_color=TEXT_DIM,
                      button_color=ACCENT, progress_color=ACCENT2).pack(side="left", padx=(0, 24))
        ctk.CTkSwitch(kv_frm, variable=ctv_q8_var, text="-ctv q8_0",
                      font=FONT_BODY, text_color=TEXT_DIM,
                      button_color=ACCENT, progress_color=ACCENT2).pack(side="left")
        ctk.CTkLabel(kv_frm, text="",
                     font=FONT_SMALL, text_color=TEXT_DIM).pack(side="left", padx=(12, 0))

        think_frm = ctk.CTkFrame(scroll, fg_color="transparent")
        think_frm.pack(fill="x", padx=24, pady=3)
        ctk.CTkLabel(think_frm, text="Thinking Mode", font=FONT_BODY,
                     text_color=TEXT, width=200, anchor="w").pack(side="left")
        ctk.CTkSegmentedButton(think_frm, values=["off", "true", "false"],
                               variable=thinking_var, font=FONT_BODY,
                               selected_color=ACCENT, selected_hover_color=ACCENT2,
                               unselected_color=BG_CARD, unselected_hover_color=BG_MID,
                               text_color=TEXT).pack(side="left")
        ctk.CTkLabel(think_frm, text="   off = don't pass flag,  true/false = explicit",
                     font=FONT_SMALL, text_color=TEXT_DIM).pack(side="left", padx=(10, 0))

        _managed = {"--no-mmproj", "--fit", "--flash-attn", "-ctk", "-ctv", "q8_0", "on",
                    "--chat-template-kwargs"}
        raw_flags   = self.config.get("flags", [])
        clean_flags = []
        skip_next   = False
        for f in raw_flags:
            if skip_next:
                skip_next = False
                continue
            if f == "--chat-template-kwargs":
                skip_next = True
                continue
            if f not in _managed:
                clean_flags.append(f)
        flags_var = ctk.StringVar(value=" ".join(clean_flags))
        lentry(scroll, "Additional Flags", flags_var,
               placeholder="e.g. --gpu-layers 35 --threads 8")
        ctk.CTkLabel(scroll, text="",
                     font=FONT_SMALL, text_color=TEXT_DIM).pack(anchor="w", padx=24)

        # ── SECTION: Paths ──────────────────────────────────────────────────
        _section_label(scroll, "Paths")

        models_dir_var   = ctk.StringVar(value=self.config.get("models_dir", ""))
        llamacpp_dir_var = ctk.StringVar(value=self.config.get("llamacpp_dir", ""))
        browse_row(scroll, "Models Directory",    models_dir_var,   mode="dir")
        browse_row(scroll, "Llama.cpp Directory", llamacpp_dir_var, mode="dir")

        # ── SECTION: Embedding Server ────────────────────────────────────────
        _section_label(scroll, "Embedding Server  (optional)")

        embedding_model_var = ctk.StringVar(value=self.config.get("embedding_model", ""))
        embedding_port_var  = ctk.IntVar(value=self.config.get("embedding_port", 8082))
        embedding_flags_var = ctk.StringVar(value=" ".join(self.config.get("embedding_flags", [])))
        browse_row(scroll, "Embedding Model (.gguf)", embedding_model_var, mode="file")
        lentry(scroll, "Embedding Port",        embedding_port_var,  width=100)
        lentry(scroll, "Embedding Extra Flags", embedding_flags_var,
               placeholder="e.g. --threads 4")
        ctk.CTkLabel(scroll, text="   Space-separated, applied to embedding server only",
                     font=FONT_SMALL, text_color=TEXT_DIM).pack(anchor="w", padx=24)

        feedback_var = ctk.StringVar(value="")
        feedback_lbl = ctk.CTkLabel(scroll, textvariable=feedback_var,
                                    font=FONT_SMALL, text_color=SUCCESS)
        feedback_lbl.pack(pady=(6, 0))

        btn_frm = ctk.CTkFrame(root, fg_color=BG_MID, corner_radius=0, height=60)
        btn_frm.pack(fill="x", side="bottom")
        btn_frm.pack_propagate(False)

        def save_and_close():
            self.config["context_window"]  = ctx_var.get()
            self.config["port"]            = port_var.get()
            self.config["max_models"]      = max_models_var.get()
            self.config["models_dir"]      = models_dir_var.get()
            self.config["llamacpp_dir"]    = llamacpp_dir_var.get()
            self.config["use_fit"]         = fit_var.get()
            self.config["no_mmproj"]       = no_mmproj_var.get()
            self.config["flash_attn"]      = flash_attn_var.get()
            self.config["ctk_q8"]          = ctk_q8_var.get()
            self.config["ctv_q8"]          = ctv_q8_var.get()
            self.config["thinking"]        = thinking_var.get()
            self.config["embedding_model"] = embedding_model_var.get()
            self.config["embedding_port"]  = embedding_port_var.get()

            base_flags = flags_var.get().strip().split() if flags_var.get().strip() else []
            if fit_var.get():
                base_flags += ["--fit", "on"]
            if no_mmproj_var.get():
                base_flags.append("--no-mmproj")
            if flash_attn_var.get():
                base_flags += ["--flash-attn", "on"]
            if ctk_q8_var.get():
                base_flags += ["-ctk", "q8_0"]
            if ctv_q8_var.get():
                base_flags += ["-ctv", "q8_0"]
            # ── FIX: store thinking kwargs as plain list items, no f-string ──
            if thinking_var.get() != "off":
                base_flags += ["--chat-template-kwargs",
                               '{"enable_thinking": ' + thinking_var.get() + '}']
            self.config["flags"] = base_flags

            emb = embedding_flags_var.get().strip()
            self.config["embedding_flags"] = emb.split() if emb else []

            if self.save_config():
                messagebox.showinfo("Saved", "Configuration saved successfully!")
                root.destroy()
            else:
                feedback_var.set("⚠  Failed to save — check file permissions.")

        def reset_defaults():
            if messagebox.askyesno("Reset", "Reset all values to defaults?"):
                ctx_var.set(32000)
                ctx_lbl_var.set("Context: 32,000")
                port_var.set(8080)
                max_models_var.set(1)
                models_dir_var.set("")
                llamacpp_dir_var.set("")
                fit_var.set(False)
                no_mmproj_var.set(False)
                flash_attn_var.set(False)
                ctk_q8_var.set(False)
                ctv_q8_var.set(False)
                thinking_var.set("off")
                flags_var.set("")
                embedding_model_var.set("")
                embedding_port_var.set(8082)
                embedding_flags_var.set("")

        ctk.CTkButton(btn_frm, text="Save", width=110, height=38,
                      fg_color=SUCCESS, hover_color="#2fa882",
                      font=FONT_HEADER, command=save_and_close).pack(
            side="left", padx=(20, 6), pady=11)
        ctk.CTkButton(btn_frm, text="Cancel", width=90, height=38,
                      fg_color=BG_CARD, hover_color=BG_MID,
                      font=FONT_BODY, command=root.destroy).pack(
            side="left", padx=6, pady=11)
        ctk.CTkButton(btn_frm, text="Reset Defaults", width=120, height=38,
                      fg_color=DANGER, hover_color="#c04040",
                      font=FONT_BODY, command=reset_defaults).pack(
            side="right", padx=20, pady=11)

        root.mainloop()

    # ════════════════════════════════════════════════════════════════════════
    #  BATCH FILE GENERATION
    #  Key rule: never use f-strings for the batch file body — cmd.exe eats
    #  bare { } characters.  Build every line with plain string concatenation.
    # ════════════════════════════════════════════════════════════════════════
    def create_custom_batch(self):
        custom_bat = Path(__file__).parent / "server_llamacpp.bat"

        if self.config.get("use_fit", False):
            context_param = "--fit on"
        else:
            context_param = "-c " + str(self.config["context_window"])

        # Build the flags string — replace any bare { } from the
        # --chat-template-kwargs value with CMD-safe escaped versions.
        safe_flags_parts = []
        flags = self.config.get("flags", [])
        i = 0
        while i < len(flags):
            flag = flags[i]
            if flag == "--chat-template-kwargs" and i + 1 < len(flags):
                # The JSON value must have its quotes escaped for CMD
                json_val = flags[i + 1]
                # Wrap in double-quotes, escape inner double-quotes as \"
                escaped = '"' + json_val.replace('"', '\\"') + '"'
                safe_flags_parts.append("--chat-template-kwargs")
                safe_flags_parts.append(escaped)
                i += 2
            else:
                safe_flags_parts.append(flag)
                i += 1

        flags_str = " ".join(safe_flags_parts)

        llama_dir   = self.config.get("llamacpp_dir", "")
        models_dir  = self.config["models_dir"]
        port        = str(self.config["port"])
        max_models  = str(self.config.get("max_models", 1))

        # Build bat using plain concatenation — zero f-strings touching user data
        lines = [
            "@echo off",
            "setlocal",
            "",
            'set "LLAMA_EXE=llama-server.exe"',
            'set "LLAMA_DIR=' + llama_dir + '"',
            'set "MODELS_DIR=' + models_dir + '"',
            "",
            'tasklist /FI "IMAGENAME eq %LLAMA_EXE%" 2>NUL | find /I "%LLAMA_EXE%" >NUL',
            "",
            'if "%ERRORLEVEL%"=="0" (',
            "    echo llama-server is running. Shutting it down...",
            "    taskkill /IM \"%LLAMA_EXE%\" /T /F >NUL 2>&1",
            ") else (",
            "    echo llama-server is not running. Starting it...",
            '    if "%LLAMA_DIR%"=="" (',
            "        echo ERROR: llama.cpp directory not configured. Please set it in Configuration.",
            "        pause",
            "        exit /b 1",
            "    )",
            '    pushd "%LLAMA_DIR%"',
            '    start "llama.cpp server" "%LLAMA_EXE%"'
            + ' --models-dir "%MODELS_DIR%"'
            + " " + context_param
            + " --models-max " + max_models
            + " --port " + port
            + (" " + flags_str if flags_str.strip() else ""),
            "    popd",
            ")",
            "",
            "timeout /t 1 /nobreak >NUL",
            "endlocal",
            "exit",
        ]
        content = "\r\n".join(lines)

        try:
            with open(custom_bat, 'w', newline='') as f:
                f.write(content)
            return custom_bat
        except Exception:
            return self.bat_file

    # ════════════════════════════════════════════════════════════════════════
    #  Server control
    # ════════════════════════════════════════════════════════════════════════
    def toggle_server(self, icon, item):
        try:
            custom_bat = self.create_custom_batch()
            subprocess.run([str(custom_bat)], shell=True, check=True)
            time.sleep(1)
            self.update_status()
        except subprocess.CalledProcessError as e:
            print(f"Error running batch file: {e}")

    def start_server_internal(self):
        if not self.server_running:
            if not self.config.get('llamacpp_dir', '').strip() or \
               not self.config.get('models_dir', '').strip():
                print("ERROR: Required paths not configured. Showing setup wizard...")
                self.show_setup_wizard()
                return
            try:
                print("Starting server...")
                custom_bat = self.create_custom_batch()
                subprocess.run([str(custom_bat)], shell=True, check=True)
                time.sleep(2)
                self.update_status()
            except subprocess.CalledProcessError as e:
                print(f"Error starting server: {e}")

    def start_server(self, icon, item):
        self.start_server_internal()

    def stop_server(self, icon, item):
        if self.server_running:
            try:
                subprocess.run(['taskkill', '/IM', 'llama-server.exe', '/T', '/F'],
                               shell=True, check=True)
                time.sleep(1)
            except subprocess.CalledProcessError as e:
                print(f"Error stopping server: {e}")

        if self.embedding_server_running:
            try:
                result = subprocess.run(
                    ['tasklist', '/FI', 'IMAGENAME eq llama-server.exe', '/V'],
                    capture_output=True, text=True, shell=True)
                for line in result.stdout.split('\n'):
                    if (f":{self.config['embedding_port']}" in line
                            or 'embedding' in line.lower()):
                        parts = line.split()
                        if len(parts) > 1:
                            try:
                                subprocess.run(['taskkill', '/PID', parts[1], '/F'],
                                               shell=True, check=True)
                            except Exception:
                                pass
                            break
            except Exception as e:
                print(f"Error stopping embedding server: {e}")

        time.sleep(1)
        self.update_status()

    def toggle_embedding_server(self, icon, item):
        try:
            if self.embedding_server_running:
                result = subprocess.run(
                    ['tasklist', '/FI', 'IMAGENAME eq llama-server.exe', '/V'],
                    capture_output=True, text=True, shell=True)
                for line in result.stdout.split('\n'):
                    if (f":{self.config['embedding_port']}" in line
                            or 'embedding' in line.lower()):
                        parts = line.split()
                        if len(parts) > 1:
                            try:
                                subprocess.run(['taskkill', '/PID', parts[1], '/F'],
                                               shell=True, check=True)
                            except Exception:
                                pass
                            break
            else:
                if not self.config.get('llamacpp_dir', '').strip() or \
                   not self.config.get('embedding_model', '').strip():
                    print("ERROR: Llama.cpp dir or embedding model not configured.")
                    return

                embedding_bat   = Path(__file__).parent / "server_embedding.bat"
                emb_flags_str   = " ".join(self.config.get("embedding_flags", []))
                emb_model       = self.config["embedding_model"]
                emb_port        = str(self.config["embedding_port"])
                llama_dir       = self.config.get("llamacpp_dir", "")

                emb_lines = [
                    "@echo off",
                    "setlocal",
                    'set "LLAMA_DIR=' + llama_dir + '"',
                    'if "%LLAMA_DIR%"=="" (',
                    "    echo ERROR: llama.cpp directory not configured.",
                    "    pause",
                    "    exit /b 1",
                    ")",
                    'pushd "%LLAMA_DIR%"',
                    'start "Embedding Server" llama-server.exe'
                    + ' -m "' + emb_model + '"'
                    + " --embedding --pooling cls -ub 8192 -c 16000"
                    + " --port " + emb_port
                    + (" " + emb_flags_str if emb_flags_str.strip() else ""),
                    "popd",
                    "endlocal",
                    "exit",
                ]
                content = "\r\n".join(emb_lines)
                with open(embedding_bat, 'w', newline='') as f:
                    f.write(content)
                subprocess.run([str(embedding_bat)], shell=True, check=True)

            time.sleep(2)
            self.update_status()
        except Exception as e:
            print(f"Error toggling embedding server: {e}")

    def unload_model_internal(self):
        if not self.server_running:
            return
        try:
            unload_url = f"http://localhost:{self.config['port']}/models/unload"
            try:
                response = requests.post(unload_url, json={}, timeout=0.5)
                if response.status_code == 200 and response.json().get('success'):
                    print("Model unloaded successfully")
                    return
            except Exception:
                pass

            models_url = f"http://localhost:{self.config['port']}/models"
            response   = requests.get(models_url, timeout=0.5)
            if response.status_code == 200:
                for model in response.json().get('data', []):
                    if model.get('status', {}).get('value') == 'loaded':
                        model_id = model['id']
                        r2 = requests.post(unload_url, json={"model": model_id}, timeout=0.5)
                        print(f"Unloaded: {model_id}" if r2.status_code == 200
                              else f"Failed to unload: {model_id}")
                        return
        except Exception as e:
            print(f"Error unloading model: {e}")

    def unload_model(self, icon, item):
        self.unload_model_internal()

    def open_webui(self, icon, item):
        if not self.server_running:
            self.start_server_internal()
            time.sleep(2)
        webbrowser.open(f"http://localhost:{self.config['port']}")

    def on_quit(self, icon, item):
        if self.server_running:
            try:
                subprocess.run(['taskkill', '/IM', 'llama-server.exe', '/T', '/F'],
                               shell=True, check=True)
                time.sleep(1)
            except Exception:
                pass
        self.running = False
        icon.stop()

    # ── click handling ───────────────────────────────────────────────────────
    def handle_double_click(self):
        self.update_status()
        if not self.server_running:
            self.start_server_internal()
        else:
            self.unload_model_internal()

    def process_click_timer(self):
        if self.click_count >= 2:
            self.handle_double_click()
        self.click_count = 0
        self.click_timer = None

    def on_left_click(self, icon, item):
        self.click_count += 1
        if self.click_timer is not None:
            self.click_timer.cancel()
        self.click_timer = threading.Timer(self.double_click_threshold,
                                           self.process_click_timer)
        self.click_timer.start()

    # ── monitor thread ───────────────────────────────────────────────────────
    def monitor_server(self):
        while self.running:
            self.update_status()
            time.sleep(2)

    # ════════════════════════════════════════════════════════════════════════
    #  MAIN RUN
    # ════════════════════════════════════════════════════════════════════════
    def run(self):
        self.running = True
        signal.signal(signal.SIGINT, self.signal_handler)

        if self.check_setup_required():
            self.show_setup_wizard()

        self.icon       = pystray.Icon("llamacpp_server")
        self.icon.icon  = self.load_icon()
        self.icon.title = "Llama.cpp Server"

        self.icon.menu = pystray.Menu(
            pystray.MenuItem("Double-Click Action", self.on_left_click,
                             default=True, visible=False),
            pystray.MenuItem("Quit", self.on_quit),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Configuration",          self.show_config),
            pystray.MenuItem("Open Web UI",            self.open_webui),
            pystray.MenuItem("Start Embedding Server", self.toggle_embedding_server),
            pystray.MenuItem("Stop Server",            self.stop_server),
        )

        self.monitor_thread = threading.Thread(target=self.monitor_server, daemon=True)
        self.monitor_thread.start()
        self.update_status()

        print("Starting Llama.cpp System Tray Application…")
        print("=" * 50)
        print("DOUBLE-CLICK tray icon to start/stop server or unload model")
        print("Press Ctrl+C to quit")

        try:
            self.icon.run()
        except KeyboardInterrupt:
            self.signal_handler(signal.SIGINT, None)


# ── single-instance guard ────────────────────────────────────────────────────
def is_already_running():
    try:
        current_pid = os.getpid()
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                if proc.info['pid'] == current_pid:
                    continue
                cmdline = proc.info.get('cmdline') or []
                exe     = os.path.basename(cmdline[0]).lower() if cmdline else ""
                if exe in ('pythonw.exe', 'python.exe', 'pythonw', 'python'):
                    if 'llamacpp_tray.py' in ' '.join(cmdline):
                        return True
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
    except Exception:
        pass
    return False


if __name__ == "__main__":
    if is_already_running():
        print("Llama.cpp Tray is already running!")
        sys.exit(0)

    tray = LlamaCppTray()
    tray.run()
