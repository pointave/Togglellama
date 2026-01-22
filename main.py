import pystray
from PIL import Image, ImageDraw
import subprocess
import time
import threading
from pathlib import Path
import json
import tkinter as tk
from tkinter import ttk, messagebox
import requests
import webbrowser
import sys
import os
import psutil
import signal

class LlamaCppTray:
    def __init__(self):
        self.bat_file = Path(__file__).parent / "Llamacpp.bat"
        self.config_file = Path(__file__).parent / "llamacpp_config.json"
        self.server_running = False
        self.embedding_server_running = False
        self.monitor_thread = None
        self.last_click_time = 0
        self.double_click_threshold = 0.5  # 500ms for double click detection
        self.click_count = 0
        self.click_timer = None
        self.running = False
        self.embedding_server_check_counter = 0  # Add counter for less frequent health checks
        self.load_config()
        
    def signal_handler(self, signum, frame):
        """Handle Ctrl+C signal gracefully"""
        print("\nReceived interrupt signal. Shutting down...")
        self.running = False
        
        # Stop any running servers
        if self.server_running:
            try:
                subprocess.run(['taskkill', '/IM', 'llama-server.exe', '/T', '/F'], 
                             shell=True, check=True)
            except:
                pass
        
        # Stop the tray icon
        if hasattr(self, 'icon') and self.icon:
            self.icon.stop()
        
        # Exit the application
        sys.exit(0)
        
    def load_config(self):
        """Load configuration from file"""
        try:
            if self.config_file.exists():
                with open(self.config_file, 'r') as f:
                    self.config = json.load(f)
            else:
                self.config = {
                    "context_window": 32000,
                    "port": 8080,
                    "models_dir": "",
                    "llamacpp_dir": "",
                    "use_fit": False,
                    "max_models": 1,
                    "flags": [],
                    "theme": "light",
                    "embedding_model": "",
                    "embedding_port": 8082
                }
        except:
            self.config = {
                "context_window": 32000,
                "port": 8080,
                "models_dir": "",
                "llamacpp_dir": "",
                "use_fit": False,
                "max_models": 1,
                "flags": [],
                "theme": "light",
                "embedding_model": "",
                "embedding_port": 8082
            }
        
    def save_config(self):
        """Save configuration to file"""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=2)
            return True
        except:
            return False
        
    def check_server_status(self):
        """Check if llama-server.exe is running"""
        try:
            result = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq llama-server.exe'], 
                                  capture_output=True, text=True, shell=True)
            return 'llama-server.exe' in result.stdout
        except:
            return False
    
    def check_embedding_server_status(self):
        """Check if embedding server is running - simplified without health checks"""
        # Just check if the process is running via tasklist
        try:
            result = subprocess.run(['tasklist', '/FI', f'IMAGENAME eq llama-server.exe', '/V'], 
                                  capture_output=True, text=True, shell=True)
            # print(f"DEBUG: check_embedding_server_status tasklist result:\n{result.stdout}")
            
            # Look for process running on the embedding port
            for line in result.stdout.split('\n'):
                # print(f"DEBUG: Checking line: '{line.strip()}'")
                if f":{self.config['embedding_port']}" in line or 'embedding' in line.lower():
                    # print(f"DEBUG: Found embedding server line: '{line.strip()}'")
                    return True
            return False
        except Exception as e:
            # print(f"DEBUG: Exception in check_embedding_server_status: {e}")
            return False
    
    def update_status(self):
        """Update server status and icon"""
        was_running = self.server_running
        was_embedding_running = self.embedding_server_running
        
        # print(f"DEBUG: Before status check - Server: {self.server_running}, Embedding: {self.embedding_server_running}")
        
        self.server_running = self.check_server_status()
        self.embedding_server_running = self.check_embedding_server_status()
        
        # print(f"DEBUG: After status check - Server: {self.server_running}, Embedding: {self.embedding_server_running}")
        
        if was_running != self.server_running or was_embedding_running != self.embedding_server_running:
            # print("DEBUG: Status changed, updating icon")
            self.update_icon()
    
    def update_icon(self):
        """Update tray icon based on server status"""
        if self.server_running:
            self.icon.icon = self.load_icon(color='green')
            self.icon.title = "Llama.cpp - Running"
        else:
            self.icon.icon = self.load_icon(color='red')
            self.icon.title = "Llama.cpp - Stopped"
    
    def create_image(self, color='red'):
        """Create a simple colored square as an icon"""
        width = 64
        height = 64
        image = Image.new('RGB', (width, height), color=color)
        dc = ImageDraw.Draw(image)
        dc.rectangle([width // 4, height // 4, width * 3 // 4, height * 3 // 4], fill='white')
        return image
    
    def load_icon(self, color='red'):
        """Try to load an .ico file, fallback to generated image if not found"""
        icon_path = Path(__file__).parent / "llamacpp_tray.ico"
        if icon_path.exists() and icon_path.stat().st_size > 0:
            try:
                base_icon = Image.open(icon_path).convert('RGBA')
                if color == 'red':
                    overlay = Image.new('RGBA', base_icon.size, (255, 0, 0, 50))
                    return Image.alpha_composite(base_icon, overlay)
                return base_icon
            except:
                pass
        return self.create_image(color)
    
    def check_setup_required(self):
        """Check if setup is required (first run or missing config)"""
        required_fields = ['models_dir', 'llamacpp_dir']
        for field in required_fields:
            if not self.config.get(field, '').strip():
                return True
        return False
    
    def show_setup_wizard(self):
        """Show first-time setup wizard"""
        try:
            root = tk.Tk()
            root.title("Llama.cpp Tray - First Time Setup")
            root.geometry("500x700")
            root.resizable(False, False)
            
            # Center the window
            root.update_idletasks()
            width = root.winfo_width()
            height = root.winfo_height()
            screen_width = root.winfo_screenwidth()
            screen_height = root.winfo_screenheight()
            x = (screen_width - width) // 2
            y = (screen_height - height) // 2
            root.geometry(f"{width}x{height}+{x}+{y}")
            
            # Main frame with padding
            main_frame = tk.Frame(root, padx=20, pady=20)
            main_frame.pack(fill=tk.BOTH, expand=True)
            
            # Title
            title_label = tk.Label(main_frame, text="Welcome to Llama.cpp Tray!", 
                                 font=("Arial", 16, "bold"))
            title_label.pack(pady=(0, 20))
            
            # Instructions
            instructions = tk.Text(main_frame, height=12, wrap=tk.WORD, font=("Arial", 10))
            instructions.pack(fill=tk.X, pady=(0, 20))
            instructions.insert(tk.END, 
                "This is your first time running Llama.cpp Tray. Before you can use it, "
                "we need to configure a few essential paths:\n\n"
                "1. Llama.cpp Directory: The path to your llama.cpp build folder containing llama-server.exe\n"
                "   (e.g., C:\\llama.cpp\\build\\bin\\Release)\n\n"
                "2. Models Directory: Where your GGUF model files are stored\n"
                "   (e.g., C:\\Models\\GGUF)\n\n"
                "3. Embedding Model (optional): Select a specific embedding model file for embeddings\n"
                "   This is optional - you can configure it later if needed\n\n"
                "4. Server Port: Port for the main llama.cpp server\n"
                "   (default: 8080)\n\n"
                "You can change these settings later from the Configuration menu.")
            instructions.config(state=tk.DISABLED)
            
            # Input fields
            widgets = {}
            
            # Llama.cpp directory
            llamacpp_label = tk.Label(main_frame, text="Llama.cpp Directory (with llama-server.exe):", 
                                    font=("Arial", 10, "bold"))
            llamacpp_label.pack(anchor=tk.W, pady=(10, 5))
            widgets["label"] = [llamacpp_label]
            
            llamacpp_frame = tk.Frame(main_frame)
            llamacpp_frame.pack(fill=tk.X, pady=(0, 10))
            
            llamacpp_var = tk.StringVar(value=self.config.get("llamacpp_dir", ""))
            llamacpp_entry = tk.Entry(llamacpp_frame, textvariable=llamacpp_var, width=60)
            llamacpp_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
            widgets["entry"] = [llamacpp_entry]
            
            def browse_llamacpp():
                from tkinter import filedialog
                directory = filedialog.askdirectory(title="Select Llama.cpp Directory")
                if directory:
                    llamacpp_var.set(directory)
            
            browse_llamacpp_btn = tk.Button(llamacpp_frame, text="Browse...", command=browse_llamacpp)
            browse_llamacpp_btn.pack(side=tk.RIGHT, padx=(5, 0))
            widgets["button"] = [browse_llamacpp_btn]
            
            # Models directory
            models_label = tk.Label(main_frame, text="Models Directory (with .gguf files):", 
                                  font=("Arial", 10, "bold"))
            models_label.pack(anchor=tk.W, pady=(10, 5))
            widgets["label"].append(models_label)
            
            models_frame = tk.Frame(main_frame)
            models_frame.pack(fill=tk.X, pady=(0, 10))
            
            models_var = tk.StringVar(value=self.config.get("models_dir", ""))
            models_entry = tk.Entry(models_frame, textvariable=models_var, width=60)
            models_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
            widgets["entry"].append(models_entry)
            
            def browse_models():
                from tkinter import filedialog
                directory = filedialog.askdirectory(title="Select Models Directory")
                if directory:
                    models_var.set(directory)
            
            browse_models_btn = tk.Button(models_frame, text="Browse...", command=browse_models)
            browse_models_btn.pack(side=tk.RIGHT, padx=(5, 0))
            widgets["button"].append(browse_models_btn)
            
            # Embedding models directory (optional)
            embedding_label = tk.Label(main_frame, text="Embedding Model (optional):", 
                                  font=("Arial", 10, "bold"))
            embedding_label.pack(anchor=tk.W, pady=(10, 5))
            widgets["label"].append(embedding_label)
            
            embedding_frame = tk.Frame(main_frame)
            embedding_frame.pack(fill=tk.X, pady=(0, 10))
            
            embedding_var = tk.StringVar(value=self.config.get("embedding_model", ""))
            embedding_entry = tk.Entry(embedding_frame, textvariable=embedding_var, width=60)
            embedding_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
            widgets["entry"].append(embedding_entry)
            
            def browse_embedding():
                from tkinter import filedialog
                # For embedding models, we want to select a file, not a directory
                filename = filedialog.askopenfilename(
                    title="Select Embedding Model (optional)",
                    filetypes=[("GGUF files", "*.gguf"), ("All files", "*.*")]
                )
                if filename:
                    embedding_var.set(filename)
            
            browse_embedding_btn = tk.Button(embedding_frame, text="Browse...", command=browse_embedding)
            browse_embedding_btn.pack(side=tk.RIGHT, padx=(5, 0))
            widgets["button"].append(browse_embedding_btn)
            
            # Server port configuration
            port_label = tk.Label(main_frame, text="Server Port:", 
                                font=("Arial", 10, "bold"))
            port_label.pack(anchor=tk.W, pady=(10, 5))
            widgets["label"].append(port_label)
            
            port_frame = tk.Frame(main_frame)
            port_frame.pack(fill=tk.X, pady=(0, 10))
            
            port_var = tk.IntVar(value=self.config.get("port", 8080))
            port_entry = tk.Entry(port_frame, textvariable=port_var, width=20)
            port_entry.pack(side=tk.LEFT)
            widgets["entry"].append(port_entry)
            
            port_help = tk.Label(port_frame, text="(default: 8080)", font=("Arial", 9), fg="gray")
            port_help.pack(side=tk.LEFT, padx=(10, 0))
            widgets["label"].append(port_help)
            
            # Buttons
            button_frame = tk.Frame(main_frame)
            button_frame.pack(pady=(20, 0))
            
            def save_setup():
                llamacpp_dir = llamacpp_var.get().strip()
                models_dir = models_var.get().strip()
                embedding_model = embedding_var.get().strip()
                port = port_var.get()
                
                if not llamacpp_dir or not models_dir:
                    messagebox.showerror("Error", "Please fill in both directory paths.")
                    return
                
                # Verify llama-server.exe exists
                llama_server_path = Path(llamacpp_dir) / "llama-server.exe"
                if not llama_server_path.exists():
                    messagebox.showerror("Error", 
                        f"llama-server.exe not found in:\n{llamacpp_dir}\n\n"
                        "Please make sure you selected the correct llama.cpp build directory.")
                    return
                
                # Save configuration
                self.config["llamacpp_dir"] = llamacpp_dir
                self.config["models_dir"] = models_dir
                self.config["port"] = port
                if embedding_model:  # Only save if not empty
                    self.config["embedding_model"] = embedding_model
                self.save_config()
                
                messagebox.showinfo("Success", 
                    "Setup completed successfully!\n\n"
                    "You can now start using Llama.cpp Tray.\n"
                    "Right-click the tray icon for more options.")
                root.destroy()
            
            save_btn = tk.Button(button_frame, text="Save & Continue", command=save_setup, 
                               width=15, height=2)
            save_btn.pack(side=tk.LEFT, padx=(0, 10))
            
            def skip_setup():
                result = messagebox.askyesno("Skip Setup", 
                    "Are you sure you want to skip setup?\n\n"
                    "You'll need to configure the paths manually from the Configuration menu "
                    "before you can start the server.")
                if result:
                    root.destroy()
            
            skip_btn = tk.Button(button_frame, text="Skip", command=skip_setup, width=10)
            skip_btn.pack(side=tk.LEFT)
            
            root.mainloop()
        except Exception as e:
            messagebox.showerror("Setup Error", f"Failed to show setup wizard: {e}")
    
    def show_config(self, icon, item):
        """Show configuration window"""
        try:
            root = tk.Tk()
            root.title("Llama.cpp Configuration")
            root.geometry("400x770")
            root.resizable(False, False)
            
            root.update_idletasks()
            width = root.winfo_width()
            height = root.winfo_height()
            screen_width = root.winfo_screenwidth()
            screen_height = root.winfo_screenheight()
            x = screen_width - width - 20
            y = screen_height - height - 60
            root.geometry(f"{width}x{height}+{x}+{y}")
            
            themes = {
                "light": {
                    "bg": "#ffffff",
                    "fg": "#000000",
                    "entry_bg": "#f0f0f0",
                    "button_bg": "#e0e0e0"
                },
                "dark": {
                    "bg": "#2b2b2b",
                    "fg": "#ffffff",
                    "entry_bg": "#404040",
                    "button_bg": "#555555"
                }
            }
            
            current_theme = self.config.get("theme", "dark")
            colors = themes[current_theme]
            widgets = {}
            
            def apply_theme(theme_name):
                nonlocal colors, current_theme, widgets
                colors = themes[theme_name]
                current_theme = theme_name
                
                root.configure(bg=colors["bg"])
                
                for widget_type, widget_list in widgets.items():
                    for widget in widget_list:
                        if widget_type == "label":
                            widget.configure(bg=colors["bg"], fg=colors["fg"])
                        elif widget_type == "entry":
                            widget.configure(bg=colors["entry_bg"], fg=colors["fg"], insertbackground=colors["fg"])
                        elif widget_type == "checkbutton":
                            widget.configure(bg=colors["bg"], fg=colors["fg"], selectcolor=colors["entry_bg"])
                        elif widget_type == "button":
                            widget.configure(bg=colors["button_bg"], fg=colors["fg"])
                        elif widget_type == "frame":
                            widget.configure(bg=colors["bg"])
                
                theme_button.config(text=f"Theme: {current_theme.capitalize()}", bg=colors["button_bg"], fg=colors["fg"])
            
            root.configure(bg=colors["bg"])
            
            theme_frame = tk.Frame(root, bg=colors["bg"])
            theme_frame.pack(pady=5)
            widgets["frame"] = widgets.get("frame", []) + [theme_frame]
            
            def toggle_theme():
                new_theme = "light" if current_theme == "dark" else "dark"
                apply_theme(new_theme)
            
            theme_button = tk.Button(theme_frame, text=f"Theme: {current_theme.capitalize()}", command=toggle_theme, bg=colors["button_bg"], fg=colors["fg"])
            theme_button.pack()
            widgets["button"] = widgets.get("button", []) + [theme_button]
            
            context_label = tk.Label(root, text="Context Window Size:", bg=colors["bg"], fg=colors["fg"])
            context_label.pack(pady=10)
            widgets["label"] = widgets.get("label", []) + [context_label]
            
            context_frame = tk.Frame(root, bg=colors["bg"])
            context_frame.pack(pady=5)
            widgets["frame"] = widgets.get("frame", []) + [context_frame]
            
            context_var = tk.IntVar(value=self.config["context_window"])
            context_slider = ttk.Scale(
                context_frame, 
                from_=1000, 
                to=256000, 
                variable=context_var,
                orient="horizontal",
                length=200,
                command=lambda v: update_context_value(int(float(v)))
            )
            context_slider.pack(side=tk.LEFT, padx=5)
            
            context_entry = tk.Entry(context_frame, textvariable=context_var, width=10, bg=colors["entry_bg"], fg=colors["fg"], insertbackground=colors["fg"])
            context_entry.pack(side=tk.LEFT, padx=5)
            widgets["entry"] = widgets.get("entry", []) + [context_entry]
            
            context_value_label = tk.Label(root, text=f"Context: {context_var.get()}", bg=colors["bg"], fg=colors["fg"])
            context_value_label.pack()
            widgets["label"] = widgets.get("label", []) + [context_value_label]
            
            def update_context_value(value):
                context_var.set(value)
                context_value_label.config(text=f"Context: {value}")
            
            port_label = tk.Label(root, text="Port:", bg=colors["bg"], fg=colors["fg"])
            port_label.pack(pady=10)
            widgets["label"] = widgets.get("label", []) + [port_label]
            
            port_var = tk.IntVar(value=self.config["port"])
            port_entry = tk.Entry(root, textvariable=port_var, width=10, bg=colors["entry_bg"], fg=colors["fg"], insertbackground=colors["fg"])
            port_entry.pack()
            widgets["entry"] = widgets.get("entry", []) + [port_entry]
            
            max_models_label = tk.Label(root, text="Max Models:", bg=colors["bg"], fg=colors["fg"])
            max_models_label.pack(pady=10)
            widgets["label"] = widgets.get("label", []) + [max_models_label]
            
            max_models_var = tk.IntVar(value=self.config.get("max_models", 1))
            max_models_entry = tk.Entry(root, textvariable=max_models_var, width=10, bg=colors["entry_bg"], fg=colors["fg"], insertbackground=colors["fg"])
            max_models_entry.pack()
            widgets["entry"] = widgets.get("entry", []) + [max_models_entry]
            
            models_dir_label = tk.Label(root, text="Models Directory:", bg=colors["bg"], fg=colors["fg"])
            models_dir_label.pack(pady=10)
            widgets["label"] = widgets.get("label", []) + [models_dir_label]
            
            models_dir_var = tk.StringVar(value=self.config["models_dir"])
            models_entry = tk.Entry(root, textvariable=models_dir_var, width=50, bg=colors["entry_bg"], fg=colors["fg"], insertbackground=colors["fg"])
            models_entry.pack(pady=5)
            widgets["entry"] = widgets.get("entry", []) + [models_entry]
            
            llamacpp_dir_label = tk.Label(root, text="Llama.cpp Directory:", bg=colors["bg"], fg=colors["fg"])
            llamacpp_dir_label.pack(pady=10)
            widgets["label"] = widgets.get("label", []) + [llamacpp_dir_label]
            
            llamacpp_dir_var = tk.StringVar(value=self.config["llamacpp_dir"])
            llamacpp_dir_entry = tk.Entry(root, textvariable=llamacpp_dir_var, width=50, bg=colors["entry_bg"], fg=colors["fg"], insertbackground=colors["fg"])
            llamacpp_dir_entry.pack(pady=5)
            widgets["entry"] = widgets.get("entry", []) + [llamacpp_dir_entry]
            
            fit_var = tk.BooleanVar(value=self.config.get("use_fit", False))
            fit_check = tk.Checkbutton(root, text="Use --fit flag (auto context size)", variable=fit_var, bg=colors["bg"], fg=colors["fg"], selectcolor=colors["entry_bg"])
            fit_check.pack(pady=10)
            widgets["checkbutton"] = widgets.get("checkbutton", []) + [fit_check]
            
            flags_label = tk.Label(root, text="Additional Flags:", bg=colors["bg"], fg=colors["fg"])
            flags_label.pack(pady=10)
            widgets["label"] = widgets.get("label", []) + [flags_label]
            
            flags_frame = tk.Frame(root, bg=colors["bg"])
            flags_frame.pack(pady=5)
            widgets["frame"] = widgets.get("frame", []) + [flags_frame]
            
            flags_var = tk.StringVar(value=" ".join(self.config.get("flags", [])))
            flags_entry = tk.Entry(flags_frame, textvariable=flags_var, width=50, bg=colors["entry_bg"], fg=colors["fg"], insertbackground=colors["fg"])
            flags_entry.pack(side=tk.LEFT, padx=5)
            widgets["entry"] = widgets.get("entry", []) + [flags_entry]
            
            flags_help_label = tk.Label(root, text="Enter flags separated by spaces (e.g., --gpu-layers 35 --threads 8)", font=("Arial", 8), bg=colors["bg"], fg=colors["fg"])
            flags_help_label.pack()
            widgets["label"] = widgets.get("label", []) + [flags_help_label]
            
            separator_frame = tk.Frame(root, bg=colors["bg"], height=2)
            separator_frame.pack(pady=15, fill=tk.X)
            widgets["frame"] = widgets.get("frame", []) + [separator_frame]
            
            embedding_label = tk.Label(root, text="Embedding Server Configuration", font=("Arial", 10, "bold"), bg=colors["bg"], fg=colors["fg"])
            embedding_label.pack(pady=5)
            widgets["label"] = widgets.get("label", []) + [embedding_label]
            
            embedding_model_label = tk.Label(root, text="Embedding Model:", bg=colors["bg"], fg=colors["fg"])
            embedding_model_label.pack(pady=5)
            widgets["label"] = widgets.get("label", []) + [embedding_model_label]
            
            embedding_model_var = tk.StringVar(value=self.config.get("embedding_model", ""))
            embedding_model_entry = tk.Entry(root, textvariable=embedding_model_var, width=60, bg=colors["entry_bg"], fg=colors["fg"], insertbackground=colors["fg"])
            embedding_model_entry.pack(pady=5)
            widgets["entry"] = widgets.get("entry", []) + [embedding_model_entry]
            
            embedding_port_label = tk.Label(root, text="Embedding Port:", bg=colors["bg"], fg=colors["fg"])
            embedding_port_label.pack(pady=5)
            widgets["label"] = widgets.get("label", []) + [embedding_port_label]
            
            embedding_port_var = tk.IntVar(value=self.config.get("embedding_port", 8082))
            embedding_port_entry = tk.Entry(root, textvariable=embedding_port_var, width=10, bg=colors["entry_bg"], fg=colors["fg"], insertbackground=colors["fg"])
            embedding_port_entry.pack()
            widgets["entry"] = widgets.get("entry", []) + [embedding_port_entry]
            
            button_frame = tk.Frame(root, bg=colors["bg"])
            button_frame.pack(pady=20)
            widgets["frame"] = widgets.get("frame", []) + [button_frame]
            
            def save_and_close():
                self.config["context_window"] = context_var.get()
                self.config["port"] = port_var.get()
                self.config["max_models"] = max_models_var.get()
                self.config["models_dir"] = models_dir_var.get()
                self.config["llamacpp_dir"] = llamacpp_dir_var.get()
                self.config["use_fit"] = fit_var.get()
                self.config["theme"] = current_theme
                self.config["embedding_model"] = embedding_model_var.get()
                self.config["embedding_port"] = embedding_port_var.get()
                
                flags_text = flags_var.get().strip()
                if flags_text:
                    self.config["flags"] = flags_text.split()
                else:
                    self.config["flags"] = []
                
                if self.save_config():
                    root.destroy()
                    messagebox.showinfo("Success", "Configuration saved successfully!")
                else:
                    messagebox.showerror("Error", "Failed to save configuration")
            
            def reset_to_default():
                context_var.set(32000)
                port_var.set(8081)
                max_models_var.set(1)
                models_dir_var.set("")
                llamacpp_dir_var.set("")
                fit_var.set(False)
                flags_var.set("")
                embedding_model_var.set("")
                embedding_port_var.set(8082)
                context_value_label.config(text=f"Context: {context_var.get()}")
            
            save_button = tk.Button(button_frame, text="Save", command=save_and_close, width=10, bg=colors["button_bg"], fg=colors["fg"])
            save_button.pack(side=tk.LEFT, padx=5)
            widgets["button"] = widgets.get("button", []) + [save_button]
            
            cancel_button = tk.Button(button_frame, text="Cancel", command=root.destroy, width=10, bg=colors["button_bg"], fg=colors["fg"])
            cancel_button.pack(side=tk.LEFT, padx=5)
            widgets["button"] = widgets.get("button", []) + [cancel_button]
            
            reset_button = tk.Button(button_frame, text="Reset to Default", command=reset_to_default, width=12, bg=colors["button_bg"], fg=colors["fg"])
            reset_button.pack(side=tk.LEFT, padx=5)
            widgets["button"] = widgets.get("button", []) + [reset_button]
            
            root.mainloop()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open config window: {e}")
    
    def create_custom_batch(self):
        """Create a custom batch file with current config"""
        custom_bat = Path(__file__).parent / "server_llamacpp.bat"
        
        if self.config.get("use_fit", False):
            context_param = "--fit on"
        else:
            context_param = f"-c {self.config['context_window']}"
        
        flags_str = " " + " ".join(self.config["flags"])
        
        content = f"""@echo off
setlocal

set "LLAMA_EXE=llama-server.exe"
set "LLAMA_DIR={self.config.get('llamacpp_dir', '')}"
set "MODELS_DIR={self.config['models_dir']}"

:: Check if llama-server is running
tasklist /FI "IMAGENAME eq %LLAMA_EXE%" 2>NUL | find /I "%LLAMA_EXE%" >NUL

if "%ERRORLEVEL%"=="0" (
    echo llama-server is running. Shutting it down...
    taskkill /IM "%LLAMA_EXE%" /T /F >NUL 2>&1
) else (
    echo llama-server is not running. Starting it...
    pushd "%LLAMA_DIR%"
if "%LLAMA_DIR%"=="" (
    echo ERROR: llama.cpp directory not configured. Please set it in Configuration.
    pause
    exit /b 1
)
start "llama.cpp server" "%LLAMA_EXE%" --models-dir "%MODELS_DIR%" {context_param} --models-max {self.config.get('max_models', 1)} --port {self.config['port']} {flags_str}
    popd
)

timeout /t 1 /nobreak >NUL
endlocal
exit"""
        try:
            with open(custom_bat, 'w') as f:
                f.write(content)
            return custom_bat
        except:
            return self.bat_file
    
    def toggle_server(self, icon, item):
        """Toggle server on/off"""
        try:
            custom_bat = self.create_custom_batch()
            subprocess.run([str(custom_bat)], shell=True, check=True)
            time.sleep(1)
            self.update_status()
        except subprocess.CalledProcessError as e:
            print(f"Error running batch file: {e}")
    
    def start_server_internal(self):
        """Internal method to start server"""
        if not self.server_running:
            # Check if required configuration is set
            if not self.config.get('llamacpp_dir', '').strip() or not self.config.get('models_dir', '').strip():
                print("ERROR: Required paths not configured. Showing setup wizard...")
                self.show_setup_wizard()
                return
            
            try:
                print("Starting server...")
                custom_bat = self.create_custom_batch()
                subprocess.run([str(custom_bat)], shell=True, check=True)
                time.sleep(2)
                self.update_status()
                print(f"Server started. Running: {self.server_running}")
            except subprocess.CalledProcessError as e:
                print(f"Error starting server: {e}")
    
    def start_server(self, icon, item):
        """Start server only if not running"""
        self.start_server_internal()
    
    def stop_server(self, icon, item):
        """Stop server only if running"""
        if self.server_running:
            try:
                subprocess.run(['taskkill', '/IM', 'llama-server.exe', '/T', '/F'], 
                             shell=True, check=True)
                time.sleep(1)
            except subprocess.CalledProcessError as e:
                print(f"Error stopping server: {e}")
        
        # Also stop embedding server if it's running
        if self.embedding_server_running:
            try:
                print("Stopping embedding server...")
                result = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq llama-server.exe', '/V'], 
                                      capture_output=True, text=True, shell=True)
                
                # Find the specific embedding server process by port or command line
                embedding_pid = None
                for line in result.stdout.split('\n'):
                    if f":{self.config['embedding_port']}" in line or 'embedding' in line.lower():
                        try:
                            parts = line.split()
                            if len(parts) > 1:
                                embedding_pid = parts[1]  # PID is usually the second column
                                break
                        except:
                            continue
                
                if embedding_pid:
                    try:
                        subprocess.run(['taskkill', '/PID', embedding_pid, '/F'], shell=True, check=True)
                        print(f"Killed embedding server process {embedding_pid}")
                    except Exception as e:
                        print(f"Error killing embedding server process: {e}")
                else:
                    print("Could not find embedding server process to kill")
                    
            except Exception as e:
                print(f"Error stopping embedding server: {e}")
        
        # Update status after stopping both servers
        time.sleep(1)
        self.update_status()
    
    def toggle_embedding_server(self, icon, item):
        """Toggle embedding server on/off"""
        # print(f"DEBUG: toggle_embedding_server called. Current status: {self.embedding_server_running}")
        try:
            if self.embedding_server_running:
                # Stop embedding server
                print("Stopping embedding server...")
                
                # More precise process detection - look for embedding server specifically
                result = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq llama-server.exe', '/V'], 
                                      capture_output=True, text=True, shell=True)
                # print(f"DEBUG: tasklist result:\n{result.stdout}")
                
                # Find specific embedding server process by port or command line
                embedding_pid = None
                for line in result.stdout.split('\n'):
                    if f":{self.config['embedding_port']}" in line or 'embedding' in line.lower():
                        try:
                            parts = line.split()
                            if len(parts) > 1:
                                embedding_pid = parts[1]  # PID is usually the second column
                                break
                        except:
                            continue
                
                if embedding_pid:
                    try:
                        subprocess.run(['taskkill', '/PID', embedding_pid, '/F'], shell=True, check=True)
                        print(f"Killed embedding server process {embedding_pid}")
                    except Exception as e:
                        print(f"Error killing embedding server process: {e}")
                else:
                    print("Could not find embedding server process to kill")
                    
            else:
                # Check if required configuration is set
                if not self.config.get('llamacpp_dir', '').strip() or not self.config.get('embedding_model', '').strip():
                    print("ERROR: Llama.cpp directory or embedding model not configured. Please configure in Settings.")
                    return
                
                # Start embedding server
                print("Starting embedding server...")
                
                # Create a temporary batch file for embedding server
                embedding_bat = Path(__file__).parent / "server_embedding.bat"
                embedding_content = f"""@echo off
setlocal

set "LLAMA_DIR={self.config.get('llamacpp_dir', '')}"

if "%LLAMA_DIR%"=="" (
    echo ERROR: llama.cpp directory not configured. Please set it in Configuration.
    pause
    exit /b 1
)
pushd "%LLAMA_DIR%"
start "Embedding Server" llama-server.exe -m "{self.config['embedding_model']}" --embedding --pooling cls -ub 8192 -c 16000 --port {self.config['embedding_port']}
popd
endlocal
exit"""
                
                try:
                    with open(embedding_bat, 'w') as f:
                        f.write(embedding_content)
                    subprocess.run([str(embedding_bat)], shell=True, check=True)
                    print(f"Embedding server started on port {self.config['embedding_port']}")
                except Exception as e:
                    print(f"Error starting embedding server: {e}")
            
            time.sleep(2)
            self.update_status()
            # print(f"DEBUG: Final embedding server status: {self.embedding_server_running}")
            
        except subprocess.CalledProcessError as e:
            print(f"Error toggling embedding server: {e}")
        except Exception as e:
            print(f"Unexpected error toggling embedding server: {e}")
    
    def unload_model_internal(self):
        """Internal method to unload model"""
        if not self.server_running:
            print("Server is not running - cannot unload model")
            return
        
        try:
            print("Unloading model...")
            unload_url = f"http://localhost:{self.config['port']}/models/unload"
            
            try:
                response = requests.post(unload_url, json={}, timeout=0.5)
                if response.status_code == 200:
                    result = response.json()
                    if result.get('success'):
                        print("Model unloaded successfully")
                        return
            except:
                pass
            
            models_url = f"http://localhost:{self.config['port']}/models"
            response = requests.get(models_url, timeout=0.5)
            
            if response.status_code == 200:
                models_data = response.json()
                
                for model in models_data.get('data', []):
                    if model.get('status', {}).get('value') == 'loaded':
                        model_id = model['id']
                        payload = {"model": model_id}
                        unload_response = requests.post(unload_url, json=payload, timeout=0.5)
                        
                        if unload_response.status_code == 200:
                            result = unload_response.json()
                            if result.get('success'):
                                print(f"Successfully unloaded model: {model_id}")
                            else:
                                print(f"Failed to unload model: {model_id}")
                        else:
                            print(f"Error unloading model: HTTP {unload_response.status_code}")
                        return
                
                print("No models are currently loaded")
            else:
                print(f"Error getting models list: HTTP {response.status_code}")
                
        except requests.exceptions.RequestException as e:
            print(f"Network error while unloading model: {e}")
        except Exception as e:
            print(f"Error unloading model: {e}")
    
    def unload_model(self, icon, item):
        """Unload model using the server's /models/unload API endpoint"""
        self.unload_model_internal()
    
    def open_webui(self, icon, item):
        """Open the llama.cpp web UI in browser, starting server if needed"""
        if not self.server_running:
            print("Server is not running - starting it first...")
            self.start_server_internal()
            time.sleep(2)  # Give server time to start
        
        try:
            webui_url = f"http://localhost:{self.config['port']}"
            webbrowser.open(webui_url)
            print(f"Opening web UI at {webui_url}")
        except Exception as e:
            print(f"Error opening web UI: {e}")
    
    def on_quit(self, icon, item):
        """Quit the application"""
        if self.server_running:
            try:
                print("Stopping server before quitting...")
                subprocess.run(['taskkill', '/IM', 'llama-server.exe', '/T', '/F'], 
                             shell=True, check=True)
                time.sleep(1)
            except subprocess.CalledProcessError as e:
                print(f"Error stopping server: {e}")
        
        self.running = False
        icon.stop()
    
    def handle_double_click(self):
        """Handle double-click on tray icon"""
        print("\n=== DOUBLE CLICK DETECTED ===")
        # Get fresh server status
        self.update_status()
        print(f"Current server status: {'RUNNING' if self.server_running else 'STOPPED'}")
        
        if not self.server_running:
            # Server is off - start it
            print("Action: Starting server...")
            self.start_server_internal()
        else:
            # Server is on - unload model
            print("Action: Unloading model...")
            self.unload_model_internal()
        print("=== DOUBLE CLICK COMPLETE ===\n")
    
    def process_click_timer(self):
        """Process click after timer expires"""
        if self.click_count >= 2:
            # Double click detected
            self.handle_double_click()
        # Reset for next click
        self.click_count = 0
        self.click_timer = None
    
    def on_left_click(self, icon, item):
        """Handle left click - detect double-clicks using timer"""
        self.click_count += 1
        
        if self.click_timer is not None:
            # Cancel existing timer
            self.click_timer.cancel()
        
        # Start new timer
        self.click_timer = threading.Timer(self.double_click_threshold, self.process_click_timer)
        self.click_timer.start()
    
    def monitor_server(self):
        """Background thread to monitor server status"""
        while self.running:
            self.update_status()
            time.sleep(2)
    
    def run(self):
        """Start the system tray application"""
        self.running = True
        
        # Register signal handler for Ctrl+C
        signal.signal(signal.SIGINT, self.signal_handler)
        
        # Check if setup is required
        if self.check_setup_required():
            self.show_setup_wizard()
        
        # Create system tray
        self.icon = pystray.Icon("llamacpp_server")
        self.icon.icon = self.load_icon()
        self.icon.title = "Llama.cpp Server"
        
        # Set up menu - use the first "hidden" menu item as the default action
        self.icon.menu = pystray.Menu(
            pystray.MenuItem("Double-Click Action", self.on_left_click, default=True, visible=False),
            pystray.MenuItem("Quit", self.on_quit),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Configuration", self.show_config),
            pystray.MenuItem("Open Web UI", self.open_webui),
            pystray.MenuItem("Start Embedding Server", self.toggle_embedding_server),
            pystray.MenuItem("Stop Server", self.stop_server)
        )
        
        # Start monitoring thread
        self.monitor_thread = threading.Thread(target=self.monitor_server, daemon=True)
        self.monitor_thread.start()
        
        # Initial status update
        self.update_status()
        
        print("Starting Llama.cpp System Tray Application...")
        print("=" * 50)
        print("DOUBLE-CLICK the tray icon to:")
        print("  • Start server (if currently stopped)")
        print("  • Unload model (if server is running)")
        print("=" * 50)
        print("Press Ctrl+C to quit")
        
        # Run system tray (blocks until quit)
        try:
            self.icon.run()
        except KeyboardInterrupt:
            self.signal_handler(signal.SIGINT, None)
        
def is_already_running():
    """Check if another instance of llamacpp_tray.py is already running"""
    try:
        current_pid = os.getpid()
        
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                if proc.info['pid'] == current_pid:
                    continue
                    
                cmdline = proc.info.get('cmdline', [])
                if cmdline:
                    # Check if this is pythonw/python running our script
                    exe_name = os.path.basename(cmdline[0]).lower()
                    if exe_name in ['pythonw.exe', 'python.exe', 'pythonw', 'python']:
                        cmdline_str = ' '.join(cmdline)
                        if 'llamacpp_tray.py' in cmdline_str:
                            return True
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        return False
    except:
        return False

if __name__ == "__main__":
    # Check if already running
    if is_already_running():
        print("Llama.cpp Tray is already running!")
        sys.exit(0)
    
    tray = LlamaCppTray()
    tray.run()