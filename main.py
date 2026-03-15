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
            "preset_1_flags": [],
            "preset_1_name": "Preset 1",
            "preset_2_flags": [],
            "preset_2_name": "Preset 2",
            "preset_3_flags": [],
            "preset_3_name": "Preset 3",
            "preset_4_flags": [],
            "preset_4_name": "Preset 4",
            "preset_5_flags": [],
            "preset_5_name": "Preset 5",
            "preset_6_flags": [],
            "preset_6_name": "Preset 6",
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
        root.title("ToggleLlama")
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

        fit_var         = ctk.BooleanVar(value=self.config.get("use_fit", False))
        no_mmproj_var   = ctk.BooleanVar(value=self.config.get("no_mmproj", False))
        flash_attn_var  = ctk.BooleanVar(value=self.config.get("flash_attn", False))
        webui_mcp_var   = ctk.BooleanVar(value=self.config.get("use_webui_mcp_proxy", False))
        no_mmap_var     = ctk.BooleanVar(value=self.config.get("use_no_mmap", False))
        ctk_q8_var      = ctk.BooleanVar(value=self.config.get("ctk_q8", False))
        ctv_q8_var      = ctk.BooleanVar(value=self.config.get("ctv_q8", False))
        thinking_var    = ctk.StringVar(value=self.config.get("thinking", "off"))
  
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

        toggles_frm2 = ctk.CTkFrame(scroll, fg_color="transparent")
        toggles_frm2.pack(fill="x", padx=24, pady=3)
        ctk.CTkLabel(toggles_frm2, text="", font=FONT_BODY,
                      text_color=TEXT, width=200, anchor="w").pack(side="left")
        ctk.CTkSwitch(toggles_frm2, variable=no_mmap_var, text="--no-mmap",
                        font=FONT_BODY, text_color=TEXT_DIM,
                        button_color=ACCENT, progress_color=ACCENT2).pack(side="left", padx=(0, 24))
        ctk.CTkSwitch(toggles_frm2, variable=webui_mcp_var, text="--webui-mcp-proxy",
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

        # Strip only the flags that are exclusively owned by the UI toggles.
        # Rules:
        #   - Simple toggle flags (no value): always remove.
        #   - --fit / --flash-attn: always remove (value is always "on").
        #   - --chat-template-kwargs: always remove (value is JSON from Thinking toggle).
        #   - -ctk / -ctv: ONLY remove when the next token is "q8_0" (the toggle value).
        #     When the user has typed e.g. "-ctk bf16", those tokens are NOT owned by
        #     the toggle and must be kept in the Additional Flags field.
        _toggle_flags_no_value = {"--no-mmproj", "--no-mmap", "--webui-mcp-proxy"}
        _toggle_flags_always_with_value = {"--fit", "--flash-attn", "--chat-template-kwargs"}
        _toggle_flags_q8_only = {"-ctk", "-ctv"}   # only strip when value == "q8_0"

        raw_flags   = self.config.get("flags", [])
        clean_flags = []
        i = 0
        while i < len(raw_flags):
            f = raw_flags[i]
            if f in _toggle_flags_no_value:
                i += 1  # skip flag only
            elif f in _toggle_flags_always_with_value:
                i += 2  # skip flag + its value
            elif f in _toggle_flags_q8_only:
                next_val = raw_flags[i + 1] if i + 1 < len(raw_flags) else ""
                if next_val == "q8_0":
                    i += 2  # toggle-owned — skip both
                else:
                    # User-typed custom value (e.g. bf16) — keep both tokens
                    clean_flags.append(f)
                    if next_val:
                        clean_flags.append(next_val)
                    i += 2
            else:
                clean_flags.append(f)
                i += 1

        flags_var = ctk.StringVar(value=" ".join(clean_flags))
        lentry(scroll, "Additional Flags", flags_var,
               placeholder="e.g. --gpu-layers 35 -ctk bf16 -ctv bf16")
        ctk.CTkLabel(scroll, text="   Use this for any flags not covered by the toggles above "
                                  "(e.g. -ctk bf16, --gpu-layers 35)",
                     font=FONT_SMALL, text_color=TEXT_DIM).pack(anchor="w", padx=24)

        # ── SECTION: Flag Presets ────────────────────────────────────────────
        _section_label(scroll, "Flag Presets")

        def create_preset_row(preset_num, parent):
            """Create a single preset row inside the given parent frame."""
            flags_key   = f"preset_{preset_num}_flags"
            name_key    = f"preset_{preset_num}_name"
            preset_name = self.config.get(name_key, f"Preset {preset_num}")

            preset_frame = ctk.CTkFrame(parent, fg_color=BG_MID)
            preset_frame.pack(fill="x", pady=4)

            name_var = ctk.StringVar(value=preset_name)
            ctk.CTkEntry(preset_frame, textvariable=name_var, width=110, height=30,
                         fg_color=BG_CARD, border_color=ACCENT2, text_color=TEXT,
                         font=FONT_BODY).pack(side="left", padx=(6, 6))

            def load_preset(n=preset_num, nv=name_var):
                pflags_key   = f"preset_{n}_flags"
                preset_flags = self.config.get(pflags_key, [])
                self.config["context_window"]  = self.config.get(f"preset_{n}_context", 32000)
                self.config["port"]            = self.config.get(f"preset_{n}_port", 8080)
                self.config["max_models"]      = self.config.get(f"preset_{n}_max_models", 1)
                self.config["flags"]           = preset_flags
                self.config["use_fit"]         = "--fit" in preset_flags
                self.config["no_mmproj"]       = "--no-mmproj" in preset_flags
                self.config["flash_attn"]      = "--flash-attn" in preset_flags
                self.config["use_no_mmap"]     = "--no-mmap" in preset_flags
                self.config["use_webui_mcp_proxy"] = "--webui-mcp-proxy" in preset_flags
                self.config["ctk_q8"]          = ("-ctk" in preset_flags and
                                                   _preset_kv_value(preset_flags, "-ctk") == "q8_0")
                self.config["ctv_q8"]          = ("-ctv" in preset_flags and
                                                   _preset_kv_value(preset_flags, "-ctv") == "q8_0")
                if "--chat-template-kwargs" in preset_flags:
                    idx = preset_flags.index("--chat-template-kwargs")
                    if idx + 1 < len(preset_flags):
                        kwargs = preset_flags[idx + 1]
                        self.config["thinking"] = "true" if '"enable_thinking": true' in kwargs else "false"
                    else:
                        self.config["thinking"] = "off"
                else:
                    self.config["thinking"] = "off"
                self.save_config()
                self.create_custom_batch()
                root.destroy()
                self.show_config()

            def save_preset(n=preset_num, nv=name_var):
                base_flags = flags_var.get().strip().split() if flags_var.get().strip() else []
                if fit_var.get():
                    base_flags += ["--fit", "on"]
                if no_mmap_var.get():
                    base_flags.append("--no-mmap")
                if webui_mcp_var.get():
                    base_flags.append("--webui-mcp-proxy")
                if no_mmproj_var.get():
                    base_flags.append("--no-mmproj")
                if flash_attn_var.get():
                    base_flags += ["--flash-attn", "on"]
                if ctk_q8_var.get():
                    base_flags += ["-ctk", "q8_0"]
                if ctv_q8_var.get():
                    base_flags += ["-ctv", "q8_0"]
                if thinking_var.get() != "off":
                    base_flags += ["--chat-template-kwargs",
                                   '{"enable_thinking": ' + thinking_var.get() + '}']
                self.config[f"preset_{n}_flags"]       = base_flags
                self.config[f"preset_{n}_name"]        = nv.get()
                self.config[f"preset_{n}_context"]     = ctx_var.get()
                self.config[f"preset_{n}_port"]        = port_var.get()
                self.config[f"preset_{n}_max_models"]  = max_models_var.get()
                self.config["flags"]                   = base_flags
                self.save_config()
                self.create_custom_batch()

            ctk.CTkButton(preset_frame, text="Load", width=52, height=30,
                          fg_color=ACCENT, hover_color=ACCENT2,
                          font=FONT_BODY,
                          command=lambda p=preset_num: load_preset(p)).pack(side="left", padx=(0, 4))
            ctk.CTkButton(preset_frame, text="Save", width=52, height=30,
                          fg_color=SUCCESS, hover_color="#2fa882",
                          font=FONT_BODY,
                          command=lambda p=preset_num: save_preset(p)).pack(side="left", padx=(0, 4))

        # ── 2-column grid: presets 1–3 left, 4–6 right ──────────────────────
        presets_grid = ctk.CTkFrame(scroll, fg_color="transparent")
        presets_grid.pack(fill="x", padx=24, pady=(2, 4))
        presets_grid.columnconfigure(0, weight=1)
        presets_grid.columnconfigure(1, weight=1)

        left_col  = ctk.CTkFrame(presets_grid, fg_color="transparent")
        right_col = ctk.CTkFrame(presets_grid, fg_color="transparent")
        left_col.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        right_col.grid(row=0, column=1, sticky="nsew", padx=(4, 0))

        create_preset_row(1, left_col)
        create_preset_row(2, left_col)
        create_preset_row(3, left_col)
        create_preset_row(4, right_col)
        create_preset_row(5, right_col)
        create_preset_row(6, right_col)

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
            self.config["use_no_mmap"]     = no_mmap_var.get()
            self.config["use_webui_mcp_proxy"] = webui_mcp_var.get()
            self.config["no_mmproj"]       = no_mmproj_var.get()
            self.config["flash_attn"]      = flash_attn_var.get()
            self.config["ctk_q8"]          = ctk_q8_var.get()
            self.config["ctv_q8"]          = ctv_q8_var.get()
            self.config["thinking"]        = thinking_var.get()
            self.config["embedding_model"] = embedding_model_var.get()
            self.config["embedding_port"]  = embedding_port_var.get()

            base_flags = flags_var.get().strip().split() if flags_var.get().strip() else []
            if no_mmap_var.get():
                base_flags.append("--no-mmap")
            if webui_mcp_var.get():
                base_flags.append("--webui-mcp-proxy")
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
            if thinking_var.get() != "off":
                base_flags += ["--chat-template-kwargs",
                               '{"enable_thinking": ' + thinking_var.get() + '}']
            self.config["flags"] = base_flags

            emb = embedding_flags_var.get().strip()
            self.config["embedding_flags"] = emb.split() if emb else []

            if self.save_config():
                self.create_custom_batch()
                root.destroy()
            else:
                feedback_var.set("⚠  Failed to save — check file permissions.")

        def toggle_server_switch(is_on):
            import threading
            def run_toggle():
                if is_on:
                    self.start_server(None, None)
                else:
                    self.stop_server(None, None)
            threading.Thread(target=run_toggle, daemon=True).start()

        ctk.CTkButton(btn_frm, text="Save", width=110, height=38,
                      fg_color=SUCCESS, hover_color="#2fa882",
                      font=FONT_HEADER, command=save_and_close).pack(
            side="left", padx=(20, 6), pady=11)
        ctk.CTkButton(btn_frm, text="Cancel", width=90, height=38,
                      fg_color=BG_CARD, hover_color=BG_MID,
                      font=FONT_BODY, command=root.destroy).pack(
            side="left", padx=6, pady=11)
        server_switch = ctk.CTkSwitch(btn_frm, text="Server",
                                      command=lambda: toggle_server_switch(server_switch.get()))
        server_switch.pack(side="right", padx=20, pady=11)

        root.mainloop()

    # ── helper: get the value token after a flag in a list ──────────────────
    @staticmethod
    def _preset_kv_value(flags, flag_name):
        try:
            idx = flags.index(flag_name)
            return flags[idx + 1] if idx + 1 < len(flags) else ""
        except ValueError:
            return ""

    # ════════════════════════════════════════════════════════════════════════
    #  BATCH FILE GENERATION
    # ════════════════════════════════════════════════════════════════════════
    def create_custom_batch(self):
        custom_bat = Path(__file__).parent / "server_llamacpp.bat"

        if self.config.get("use_fit", False):
            context_param = "--fit on"
        else:
            context_param = "-c " + str(self.config["context_window"])

        safe_flags_parts = []
        flags = self.config.get("flags", [])
        i = 0
        while i < len(flags):
            flag = flags[i]
            if flag == "--chat-template-kwargs" and i + 1 < len(flags):
                json_val = flags[i + 1]
                escaped  = '"' + json_val.replace('"', '\\"') + '"'
                safe_flags_parts.append("--chat-template-kwargs")
                safe_flags_parts.append(escaped)
                i += 2
            else:
                safe_flags_parts.append(flag)
                i += 1

        flags_str  = " ".join(safe_flags_parts)
        llama_dir  = self.config.get("llamacpp_dir", "")
        models_dir = self.config["models_dir"]
        port       = str(self.config["port"])
        max_models = str(self.config.get("max_models", 1))

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
    #  PRESET ACTIONS (called from tray menu)
    # ════════════════════════════════════════════════════════════════════════
    def _apply_preset(self, preset_num):
        """Load a preset, rebuild the batch, optionally restart the server."""
        flags_key    = f"preset_{preset_num}_flags"
        preset_flags = self.config.get(flags_key, [])

        if not preset_flags:
            print(f"Preset {preset_num} has no flags saved — open Configuration to save it first.")
            return

        self.config["context_window"]      = self.config.get(f"preset_{preset_num}_context", 32000)
        self.config["port"]                = self.config.get(f"preset_{preset_num}_port", 8080)
        self.config["max_models"]          = self.config.get(f"preset_{preset_num}_max_models", 1)
        self.config["flags"]               = preset_flags
        self.config["use_fit"]             = "--fit" in preset_flags
        self.config["no_mmproj"]           = "--no-mmproj" in preset_flags
        self.config["flash_attn"]          = "--flash-attn" in preset_flags
        self.config["use_no_mmap"]         = "--no-mmap" in preset_flags
        self.config["use_webui_mcp_proxy"] = "--webui-mcp-proxy" in preset_flags
        self.config["ctk_q8"]              = (
            "-ctk" in preset_flags and
            self._preset_kv_value(preset_flags, "-ctk") == "q8_0"
        )
        self.config["ctv_q8"]              = (
            "-ctv" in preset_flags and
            self._preset_kv_value(preset_flags, "-ctv") == "q8_0"
        )
        if "--chat-template-kwargs" in preset_flags:
            idx = preset_flags.index("--chat-template-kwargs")
            if idx + 1 < len(preset_flags):
                kwargs = preset_flags[idx + 1]
                self.config["thinking"] = "true" if '"enable_thinking": true' in kwargs else "false"
            else:
                self.config["thinking"] = "off"
        else:
            self.config["thinking"] = "off"

        self.save_config()
        self.create_custom_batch()
        print(f"Preset {preset_num} applied.")

        # If server is running, restart it with the new flags
        if self.server_running:
            print("Restarting server with new preset…")
            self.stop_server(None, None)
            time.sleep(1)
            self.start_server_internal()

    def _make_preset_action(self, n):
        """Return a callable suitable for pystray that applies preset n."""
        def action(icon, item):
            threading.Thread(target=self._apply_preset, args=(n,), daemon=True).start()
        return action

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

                embedding_bat = Path(__file__).parent / "server_embedding.bat"
                emb_flags_str = " ".join(self.config.get("embedding_flags", []))
                emb_model     = self.config["embedding_model"]
                emb_port      = str(self.config["embedding_port"])
                llama_dir     = self.config.get("llamacpp_dir", "")

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

    # ── mmproj toggle ────────────────────────────────────────────────────────
    def toggle_mmproj(self, icon, item):
        """Flip the --no-mmproj flag, save config, rebuild batch."""
        current = self.config.get("no_mmproj", False)
        self.config["no_mmproj"] = not current

        # Keep the flags list consistent with the new toggle state
        flags = self.config.get("flags", [])
        if self.config["no_mmproj"]:
            if "--no-mmproj" not in flags:
                flags.append("--no-mmproj")
        else:
            flags = [f for f in flags if f != "--no-mmproj"]
        self.config["flags"] = flags

        self.save_config()
        self.create_custom_batch()
        state = "ON (--no-mmproj active)" if self.config["no_mmproj"] else "OFF"
        print(f"mmproj toggled: {state}")

    # ── build tray menu (called at startup and after config changes) ─────────
    def _build_menu(self):
        """Build the pystray Menu, pulling live preset names from config."""
        preset_items = []
        for n in range(1, 7):
            name = self.config.get(f"preset_{n}_name", f"Preset {n}").strip() or f"Preset {n}"
            has_flags = bool(self.config.get(f"preset_{n}_flags"))
            label = name if has_flags else f"{name} (empty)"
            preset_items.append(
                pystray.MenuItem(label, self._make_preset_action(n))
            )

        return pystray.Menu(
            pystray.MenuItem("Double-Click Action", self.on_left_click,
                             default=True, visible=False),
            pystray.MenuItem("Presets", pystray.Menu(*preset_items)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Configuration",          self.show_config),
            pystray.MenuItem("Open Web UI",            self.open_webui),
            pystray.MenuItem("Start Embedding Server", self.toggle_embedding_server),
            pystray.MenuItem("Disable Vision", self.toggle_mmproj,
                             checked=lambda item: self.config.get("no_mmproj", False)),
            pystray.MenuItem("Stop Server",            self.stop_server),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self.on_quit),
        )

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
        self.icon.menu  = self._build_menu()

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


# ── module-level helper (also used inside show_config via self.) ─────────────
def _preset_kv_value(flags, flag_name):
    try:
        idx = flags.index(flag_name)
        return flags[idx + 1] if idx + 1 < len(flags) else ""
    except ValueError:
        return ""


if __name__ == "__main__":
    if is_already_running():
        print("Llama.cpp Tray is already running!")
        sys.exit(0)

    tray = LlamaCppTray()
    tray.run()
