import pygame
import mido
import time
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import json
import os

# 设置mido使用pygame作为MIDI后端
mido.set_backend('mido.backends.pygame')

class GamepadMIDIController:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("游戏手柄MIDI控制器")
        self.root.geometry("850x700")
        
        # 配置文件路径
        self.config_file = "gamepad_midi_config.json"
        
        # MIDI音符到音名的映射
        self.note_names = {}
        self.name_to_note = {}
        self.create_note_mapping()
        
        # 默认配置
        self.config = {
            "midi_port": "Gamepad MIDI 1",
            "joystick_id": 0,
            "relative_sensitivity": 3.0,
            "stick_deadzone": 0.15,
            "update_interval": 0.05,
            "cc_mappings": {
                "left_stick_x": 1,
                "left_stick_y": 2,
                "right_stick_x": 3,
                "right_stick_y": 4
            },
            "note_mappings": {
                "button_a": 60,      # 按钮0 - A键
                "button_b": 62,      # 按钮1 - B键  
                "button_x": 64,      # 按钮2 - X键
                "button_y": 65,      # 按钮3 - Y键
                "dpad_up": 67,       # 十字键上
                "dpad_down": 69,     # 十字键下
                "dpad_left": 71,     # 十字键左
                "dpad_right": 72,    # 十字键右
                "lb": 74,            # 左肩键
                "rb": 76,            # 右肩键
                "lt": 77,            # 左扳机键
                "rt": 79             # 右扳机键
            }
        }
        
        # 运行状态
        self.is_running = False
        self.controller_thread = None
        self.port = None
        self.joystick = None
        self.config_lock = threading.Lock()  # 添加配置锁
        
        # 按键映射表（按钮ID到配置键的映射）
        self.button_mapping = {
            0: "button_a",
            1: "button_b", 
            2: "button_x",
            3: "button_y",
            4: "lb",
            5: "rb",
            6: "lt",  # 备用，有些手柄LT是按钮
            7: "rt",  # 备用，有些手柄RT是按钮
            8: "dpad_up",    # 备用映射
            9: "dpad_down",  # 备用映射
            10: "dpad_left", # 备用映射
            11: "dpad_right" # 备用映射
        }
        
        # 先创建GUI，再加载配置
        self.create_gui()
        self.load_config()
        
        # 绑定窗口关闭事件
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
    def create_note_mapping(self):
        """创建MIDI音符到音名的映射"""
        note_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
        
        for i in range(128):
            octave = (i // 12) - 1
            note_name = note_names[i % 12]
            full_name = f"{note_name}{octave}"
            self.note_names[i] = full_name
            self.name_to_note[full_name] = i
    
    def create_gui(self):
        # 创建主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # 配置网格权重
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        
        # 标题
        title_label = ttk.Label(main_frame, text="游戏手柄MIDI控制器", font=("Arial", 16, "bold"))
        title_label.grid(row=0, column=0, columnspan=3, pady=(0, 20))
        
        # MIDI端口设置
        port_frame = ttk.Frame(main_frame)
        port_frame.grid(row=1, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=5)
        port_frame.columnconfigure(1, weight=1)
        
        ttk.Label(port_frame, text="MIDI端口:").grid(row=0, column=0, sticky=tk.W, pady=5)
        
        # MIDI端口选择下拉框
        self.midi_port_var = tk.StringVar(value=self.config["midi_port"])
        self.port_combobox = ttk.Combobox(port_frame, textvariable=self.midi_port_var, width=30)
        self.port_combobox.grid(row=0, column=1, sticky=(tk.W, tk.E), pady=5, padx=(10, 5))
        
        # 刷新端口按钮
        ttk.Button(port_frame, text="刷新端口", command=self.refresh_midi_ports).grid(row=0, column=2, pady=5, padx=(5, 0))
        
        # 初始化端口列表
        self.refresh_midi_ports()
        
        # 灵敏度设置
        ttk.Label(main_frame, text="摇杆灵敏度:").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.sensitivity_var = tk.DoubleVar(value=self.config["relative_sensitivity"])
        sensitivity_scale = ttk.Scale(main_frame, from_=0.5, to=10.0, variable=self.sensitivity_var, 
                                    orient=tk.HORIZONTAL, length=200)
        sensitivity_scale.grid(row=2, column=1, sticky=(tk.W, tk.E), pady=5, padx=(10, 0))
        self.sensitivity_label = ttk.Label(main_frame, text=f"{self.sensitivity_var.get():.1f}")
        self.sensitivity_label.grid(row=2, column=2, pady=5, padx=(10, 0))
        sensitivity_scale.configure(command=self.update_sensitivity_label)
        
        # CC映射设置
        cc_frame = ttk.LabelFrame(main_frame, text="摇杆CC映射", padding="10")
        cc_frame.grid(row=3, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=10)
        cc_frame.columnconfigure(1, weight=1)
        cc_frame.columnconfigure(3, weight=1)
        
        # 左摇杆
        ttk.Label(cc_frame, text="左摇杆X轴 CC:").grid(row=0, column=0, sticky=tk.W, pady=2)
        self.left_x_cc_var = tk.IntVar(value=self.config["cc_mappings"]["left_stick_x"])
        ttk.Spinbox(cc_frame, from_=1, to=127, textvariable=self.left_x_cc_var, width=10).grid(row=0, column=1, sticky=tk.W, pady=2, padx=(10, 20))
        
        ttk.Label(cc_frame, text="左摇杆Y轴 CC:").grid(row=0, column=2, sticky=tk.W, pady=2)
        self.left_y_cc_var = tk.IntVar(value=self.config["cc_mappings"]["left_stick_y"])
        ttk.Spinbox(cc_frame, from_=1, to=127, textvariable=self.left_y_cc_var, width=10).grid(row=0, column=3, sticky=tk.W, pady=2, padx=(10, 0))
        
        # 右摇杆
        ttk.Label(cc_frame, text="右摇杆X轴 CC:").grid(row=1, column=0, sticky=tk.W, pady=2)
        self.right_x_cc_var = tk.IntVar(value=self.config["cc_mappings"]["right_stick_x"])
        ttk.Spinbox(cc_frame, from_=1, to=127, textvariable=self.right_x_cc_var, width=10).grid(row=1, column=1, sticky=tk.W, pady=2, padx=(10, 20))
        
        ttk.Label(cc_frame, text="右摇杆Y轴 CC:").grid(row=1, column=2, sticky=tk.W, pady=2)
        self.right_y_cc_var = tk.IntVar(value=self.config["cc_mappings"]["right_stick_y"])
        ttk.Spinbox(cc_frame, from_=1, to=127, textvariable=self.right_y_cc_var, width=10).grid(row=1, column=3, sticky=tk.W, pady=2, padx=(10, 0))
        
        # 音符映射设置
        note_frame = ttk.LabelFrame(main_frame, text="按键音符映射", padding="10")
        note_frame.grid(row=4, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=10)
        
        # 创建音符映射控件
        self.note_vars = {}
        self.note_labels = {}  # 存储音符标签，用于更新显示
        note_configs = [
            ("A键:", "button_a"), ("B键:", "button_b"), ("X键:", "button_x"), ("Y键:", "button_y"),
            ("十字键↑:", "dpad_up"), ("十字键↓:", "dpad_down"), ("十字键←:", "dpad_left"), ("十字键→:", "dpad_right"),
            ("LB键:", "lb"), ("RB键:", "rb"), ("LT键:", "lt"), ("RT键:", "rt")
        ]
        
        for i, (label, key) in enumerate(note_configs):
            row = i // 3
            col = (i % 3) * 4
            
            # 按键名称标签
            ttk.Label(note_frame, text=label).grid(row=row, column=col, sticky=tk.W, pady=2, padx=(0, 5))
            
            # 音符数值输入框
            self.note_vars[key] = tk.IntVar(value=self.config["note_mappings"][key])
            spinbox = ttk.Spinbox(note_frame, from_=0, to=127, textvariable=self.note_vars[key], 
                                width=5, command=lambda k=key: self.update_note_display(k))
            spinbox.grid(row=row, column=col+1, sticky=tk.W, pady=2, padx=(0, 5))
            
            # 绑定变量变化事件
            self.note_vars[key].trace('w', lambda *args, k=key: self.update_note_display(k))
            
            # 音符名称显示标签
            note_name = self.note_names.get(self.config["note_mappings"][key], "Unknown")
            self.note_labels[key] = ttk.Label(note_frame, text=note_name, foreground="blue")
            self.note_labels[key].grid(row=row, column=col+2, sticky=tk.W, pady=2, padx=(0, 15))
        
        # 实时更新选项
        update_frame = ttk.Frame(main_frame)
        update_frame.grid(row=5, column=0, columnspan=3, pady=10)
        
        self.real_time_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(update_frame, text="启用实时参数更新", variable=self.real_time_var).pack(side=tk.LEFT)
        ttk.Label(update_frame, text="（勾选后在运行时可实时调节参数）").pack(side=tk.LEFT, padx=(10, 0))
        
        # 控制按钮
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=6, column=0, columnspan=3, pady=20)
        
        self.start_button = ttk.Button(button_frame, text="启动控制器", command=self.toggle_controller)
        self.start_button.pack(side=tk.LEFT, padx=5)
        
        ttk.Button(button_frame, text="保存配置", command=self.save_config).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="加载配置", command=self.load_config).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="重置默认", command=self.reset_config).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="测试按键", command=self.test_buttons).pack(side=tk.LEFT, padx=5)
        
        # 状态显示
        self.status_var = tk.StringVar(value="就绪")
        status_label = ttk.Label(main_frame, textvariable=self.status_var, font=("Arial", 10))
        status_label.grid(row=7, column=0, columnspan=3, pady=10)
        
        # 日志显示
        log_frame = ttk.LabelFrame(main_frame, text="运行日志", padding="5")
        log_frame.grid(row=8, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady=10)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        main_frame.rowconfigure(8, weight=1)
        
        self.log_text = tk.Text(log_frame, height=8, wrap=tk.WORD)
        scrollbar = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
    
    def refresh_midi_ports(self):
        """刷新可用的MIDI输出端口"""
        try:
            available_ports = mido.get_output_names()
            self.port_combobox['values'] = available_ports
            
            if available_ports:
                # 如果当前设置的端口在可用列表中，保持选择
                if self.midi_port_var.get() not in available_ports:
                    self.midi_port_var.set(available_ports[0])  # 默认选择第一个
                self.log_message(f"找到 {len(available_ports)} 个MIDI输出端口")
            else:
                self.log_message("未找到可用的MIDI输出端口")
                self.port_combobox['values'] = ["没有可用端口"]
                
        except Exception as e:
            self.log_message(f"刷新MIDI端口时出错: {e}")
    
    def update_note_display(self, key):
        """更新音符名称显示"""
        try:
            note_value = self.note_vars[key].get()
            note_name = self.note_names.get(note_value, "Unknown")
            self.note_labels[key].config(text=note_name)
        except:
            pass
    
    def test_buttons(self):
        """测试按键功能，显示手柄按键ID"""
        if not self.is_running:
            messagebox.showwarning("提示", "请先启动控制器再测试按键")
            return
            
        test_window = tk.Toplevel(self.root)
        test_window.title("按键测试")
        test_window.geometry("500x400")
        
        ttk.Label(test_window, text="按下手柄按键查看对应ID", font=("Arial", 12)).pack(pady=10)
        
        button_status = tk.Text(test_window, height=20, width=60, font=("Consolas", 10))
        button_status.pack(pady=10, padx=10, fill=tk.BOTH, expand=True)
        
        def update_button_status():
            if self.joystick and test_window.winfo_exists():
                try:
                    pygame.event.pump()
                    button_status.delete(1.0, tk.END)
                    
                    # 显示按钮状态
                    button_status.insert(tk.END, "=== 按钮状态 ===\n")
                    pressed_buttons = []
                    for i in range(self.joystick.get_numbuttons()):
                        if self.joystick.get_button(i):
                            config_key = self.button_mapping.get(i, f"未映射按钮{i}")
                            note = self.config["note_mappings"].get(config_key.replace("button_", "button_"), "N/A")
                            pressed_buttons.append(f"按钮 {i}: {config_key} -> 音符 {note}")
                    
                    if pressed_buttons:
                        for btn in pressed_buttons:
                            button_status.insert(tk.END, btn + "\n")
                    else:
                        button_status.insert(tk.END, "没有按钮被按下\n")
                    
                    # 显示摇杆状态
                    button_status.insert(tk.END, "\n=== 摇杆状态 ===\n")
                    left_x = self.joystick.get_axis(0)
                    left_y = self.joystick.get_axis(1)
                    right_x = self.joystick.get_axis(2) if self.joystick.get_numaxes() > 2 else 0
                    right_y = self.joystick.get_axis(3) if self.joystick.get_numaxes() > 3 else 0
                    
                    button_status.insert(tk.END, f"左摇杆: X={left_x:.2f}, Y={left_y:.2f}\n")
                    button_status.insert(tk.END, f"右摇杆: X={right_x:.2f}, Y={right_y:.2f}\n")
                    
                    # 显示扳机状态
                    if self.joystick.get_numaxes() > 4:
                        lt_value = self.joystick.get_axis(4)
                        rt_value = self.joystick.get_axis(5)
                        button_status.insert(tk.END, f"LT扳机: {lt_value:.2f}\n")
                        button_status.insert(tk.END, f"RT扳机: {rt_value:.2f}\n")
                    
                    # 显示十字键状态
                    if self.joystick.get_numhats() > 0:
                        hat = self.joystick.get_hat(0)
                        button_status.insert(tk.END, f"十字键: {hat}\n")
                    
                    test_window.after(50, update_button_status)
                except:
                    pass
        
        update_button_status()
        
        def close_test():
            test_window.destroy()
            
        ttk.Button(test_window, text="关闭", command=close_test).pack(pady=5)
    
    def update_sensitivity_label(self, value):
        self.sensitivity_label.config(text=f"{float(value):.1f}")
    
    def log_message(self, message):
        """添加日志消息"""
        if hasattr(self, 'log_text'):
            timestamp = time.strftime("%H:%M:%S")
            self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
            self.log_text.see(tk.END)
            self.root.update_idletasks()
    
    def save_config(self):
        """保存配置到文件"""
        try:
            with self.config_lock:
                self.config["midi_port"] = self.midi_port_var.get()
                self.config["relative_sensitivity"] = self.sensitivity_var.get()
                
                # 更新CC映射
                self.config["cc_mappings"]["left_stick_x"] = self.left_x_cc_var.get()
                self.config["cc_mappings"]["left_stick_y"] = self.left_y_cc_var.get()
                self.config["cc_mappings"]["right_stick_x"] = self.right_x_cc_var.get()
                self.config["cc_mappings"]["right_stick_y"] = self.right_y_cc_var.get()
                
                # 更新音符映射
                for key, var in self.note_vars.items():
                    self.config["note_mappings"][key] = var.get()
            
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
            
            self.log_message("配置已保存")
            messagebox.showinfo("成功", "配置已保存到文件")
        except Exception as e:
            self.log_message(f"保存配置失败: {e}")
            messagebox.showerror("错误", f"保存配置失败: {e}")
    
    def load_config(self):
        """从文件加载配置"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    loaded_config = json.load(f)
                
                with self.config_lock:
                    # 更新配置，保留默认值
                    for key, value in loaded_config.items():
                        if key in self.config:
                            self.config[key] = value
                
                # 更新GUI
                self.update_gui_from_config()
                self.log_message("配置已加载")
            else:
                self.log_message("配置文件不存在，使用默认配置")
        except Exception as e:
            self.log_message(f"加载配置失败: {e}")
            messagebox.showerror("错误", f"加载配置失败: {e}")
    
    def update_gui_from_config(self):
        """根据配置更新GUI"""
        self.midi_port_var.set(self.config["midi_port"])
        self.sensitivity_var.set(self.config["relative_sensitivity"])
        self.update_sensitivity_label(self.config["relative_sensitivity"])
        
        # 更新CC映射
        self.left_x_cc_var.set(self.config["cc_mappings"]["left_stick_x"])
        self.left_y_cc_var.set(self.config["cc_mappings"]["left_stick_y"])
        self.right_x_cc_var.set(self.config["cc_mappings"]["right_stick_x"])
        self.right_y_cc_var.set(self.config["cc_mappings"]["right_stick_y"])
        
        # 更新音符映射
        for key, var in self.note_vars.items():
            if key in self.config["note_mappings"]:
                var.set(self.config["note_mappings"][key])
                self.update_note_display(key)
    
    def reset_config(self):
        """重置为默认配置"""
        if messagebox.askyesno("确认", "确定要重置为默认配置吗？"):
            with self.config_lock:
                # 重置配置
                self.config = {
                    "midi_port": "Gamepad MIDI 1",
                    "joystick_id": 0,
                    "relative_sensitivity": 3.0,
                    "stick_deadzone": 0.15,
                    "update_interval": 0.05,
                    "cc_mappings": {
                        "left_stick_x": 1,
                        "left_stick_y": 2,
                        "right_stick_x": 3,
                        "right_stick_y": 4
                    },
                    "note_mappings": {
                        "button_a": 60,
                        "button_b": 62,
                        "button_x": 64,
                        "button_y": 65,
                        "dpad_up": 67,
                        "dpad_down": 69,
                        "dpad_left": 71,
                        "dpad_right": 72,
                        "lb": 74,
                        "rb": 76,
                        "lt": 77,
                        "rt": 79
                    }
                }
            
            self.update_gui_from_config()
            self.log_message("配置已重置为默认值")
    
    def toggle_controller(self):
        """切换控制器运行状态"""
        if self.is_running:
            self.stop_controller()
        else:
            self.start_controller()
    
    def start_controller(self):
        """启动控制器"""
        try:
            # 初始化pygame
            pygame.init()
            pygame.joystick.init()
            
            # 检查手柄
            if pygame.joystick.get_count() == 0:
                raise Exception("未检测到游戏手柄")
            
            self.joystick = pygame.joystick.Joystick(self.config["joystick_id"])
            self.joystick.init()
            
            # 安全关闭现有MIDI端口
            self.close_midi_port()
            
            # 打开MIDI端口（不使用virtual参数）
            port_name = self.midi_port_var.get()
            if not port_name or port_name == "没有可用端口":
                raise Exception("请选择有效的MIDI端口")
                
            self.port = mido.open_output(port_name)
            
            self.is_running = True
            self.start_button.config(text="停止控制器")
            self.status_var.set("运行中")
            
            # 启动控制线程
            self.controller_thread = threading.Thread(target=self.controller_loop, daemon=True)
            self.controller_thread.start()
            
            self.log_message(f"控制器已启动")
            self.log_message(f"手柄: {self.joystick.get_name()}")
            self.log_message(f"MIDI端口: {port_name}")
            self.log_message(f"按钮数量: {self.joystick.get_numbuttons()}")
            self.log_message(f"摇杆轴数量: {self.joystick.get_numaxes()}")
            
        except Exception as e:
            self.log_message(f"启动失败: {e}")
            messagebox.showerror("错误", f"启动失败: {e}")
            self.is_running = False
    
    def close_midi_port(self):
        """安全关闭MIDI端口"""
        if self.port:
            try:
                self.port.close()
                self.log_message("MIDI端口已关闭")
            except Exception as e:
                self.log_message(f"关闭MIDI端口时出错: {e}")
            finally:
                self.port = None
    
    def stop_controller(self):
        """停止控制器"""
        self.is_running = False
        
        if self.controller_thread:
            self.controller_thread.join(timeout=1.0)
        
        self.close_midi_port()
        
        if self.joystick:
            self.joystick.quit()
            self.joystick = None
        
        try:
            pygame.quit()
        except:
            pass
        
        self.start_button.config(text="启动控制器")
        self.status_var.set("已停止")
        self.log_message("控制器已停止")
    
    def get_current_config(self):
        """安全获取当前配置"""
        try:
            with self.config_lock:
                if self.real_time_var.get():
                    # 实时读取GUI配置
                    return {
                        "relative_sensitivity": self.sensitivity_var.get(),
                        "stick_deadzone": self.config["stick_deadzone"],
                        "cc_mappings": {
                            "left_stick_x": self.left_x_cc_var.get(),
                            "left_stick_y": self.left_y_cc_var.get(),
                            "right_stick_x": self.right_x_cc_var.get(),
                            "right_stick_y": self.right_y_cc_var.get()
                        },
                        "note_mappings": {key: var.get() for key, var in self.note_vars.items()}
                    }
                else:
                    # 使用保存的配置
                    return self.config.copy()
        except Exception as e:
            self.log_message(f"获取配置时出错: {e}")
            # 返回默认配置
            return {
                "relative_sensitivity": 3.0,
                "stick_deadzone": 0.15,
                "cc_mappings": {
                    "left_stick_x": 1,
                    "left_stick_y": 2,
                    "right_stick_x": 3,
                    "right_stick_y": 4
                },
                "note_mappings": {
                    "button_a": 60,
                    "button_b": 62,
                    "button_x": 64,
                    "button_y": 65,
                    "dpad_up": 67,
                    "dpad_down": 69,
                    "dpad_left": 71,
                    "dpad_right": 72,
                    "lb": 74,
                    "rb": 76,
                    "lt": 77,
                    "rt": 79
                }
            }
    
    def controller_loop(self):
        """主控制循环"""
        button_states = {}
        # 初始化CC值字典，使用安全的配置获取
        current_config = self.get_current_config()
        current_cc_values = {}
        
        # 安全初始化CC值
        try:
            for key in ["left_stick_x", "left_stick_y", "right_stick_x", "right_stick_y"]:
                if key in current_config["cc_mappings"]:
                    current_cc_values[current_config["cc_mappings"][key]] = 64
        except Exception as e:
            self.log_message(f"初始化CC值时出错: {e}")
            return
        
        last_update_time = time.time()
        
        try:
            while self.is_running:
                current_time = time.time()
                
                # 处理pygame事件
                pygame.event.pump()
                
                # 获取当前配置（带错误处理）
                current_config = self.get_current_config()
                
                # 处理摇杆控制
                if current_time - last_update_time >= 0.05:  # 使用固定更新间隔
                    try:
                        # 左摇杆
                        if self.joystick.get_numaxes() > 1:
                            left_stick_x = self.joystick.get_axis(0)
                            left_stick_y = -self.joystick.get_axis(1)  # 反转Y轴
                            
                            # 安全处理CC映射
                            if "left_stick_x" in current_config["cc_mappings"]:
                                self.handle_stick_relative(left_stick_x, current_config["cc_mappings"]["left_stick_x"], 
                                                         current_cc_values, "左摇杆X", current_config)
                            if "left_stick_y" in current_config["cc_mappings"]:
                                self.handle_stick_relative(left_stick_y, current_config["cc_mappings"]["left_stick_y"], 
                                                         current_cc_values, "左摇杆Y", current_config)
                        
                        # 右摇杆
                        if self.joystick.get_numaxes() > 3:
                            right_stick_x = self.joystick.get_axis(2)
                            right_stick_y = -self.joystick.get_axis(3)  # 反转Y轴
                            
                            # 安全处理CC映射
                            if "right_stick_x" in current_config["cc_mappings"]:
                                self.handle_stick_relative(right_stick_x, current_config["cc_mappings"]["right_stick_x"], 
                                                         current_cc_values, "右摇杆X", current_config)
                            if "right_stick_y" in current_config["cc_mappings"]:
                                self.handle_stick_relative(right_stick_y, current_config["cc_mappings"]["right_stick_y"], 
                                                         current_cc_values, "右摇杆Y", current_config)
                        
                        last_update_time = current_time
                        
                    except Exception as e:
                        self.log_message(f"处理摇杆时出错: {e}")
                
                # 处理按钮
                try:
                    for i in range(self.joystick.get_numbuttons()):
                        is_pressed = self.joystick.get_button(i)
                        last_state = button_states.get(i, False)
                        
                        if is_pressed and not last_state:
                            # 按钮被按下
                            button_key = self.button_mapping.get(i)
                            if button_key and button_key in current_config["note_mappings"]:
                                note = current_config["note_mappings"][button_key]
                                if 0 <= note <= 127:  # 验证音符范围
                                    self.port.send(mido.Message('note_on', note=note, velocity=127))
                                    note_name = self.note_names.get(note, "Unknown")
                                    self.log_message(f"按钮{i}({button_key}) 按下 -> 音符{note}({note_name})")
                            button_states[i] = True
                            
                        elif not is_pressed and last_state:
                            # 按钮被释放
                            button_key = self.button_mapping.get(i)
                            if button_key and button_key in current_config["note_mappings"]:
                                note = current_config["note_mappings"][button_key]
                                if 0 <= note <= 127:  # 验证音符范围
                                    self.port.send(mido.Message('note_off', note=note, velocity=0))
                            button_states[i] = False
                except Exception as e:
                    self.log_message(f"处理按钮时出错: {e}")
                
                # 处理十字键（Hat）
                try:
                    if self.joystick.get_numhats() > 0:
                        hat = self.joystick.get_hat(0)
                        
                        # 处理十字键按下和释放
                        hat_mappings = [
                            (hat[1] == 1, "dpad_up"),      # 上
                            (hat[1] == -1, "dpad_down"),   # 下
                            (hat[0] == -1, "dpad_left"),   # 左
                            (hat[0] == 1, "dpad_right")    # 右
                        ]
                        
                        for is_pressed, hat_key in hat_mappings:
                            last_state = button_states.get(hat_key, False)
                            
                            if is_pressed and not last_state:
                                if hat_key in current_config["note_mappings"]:
                                    note = current_config["note_mappings"][hat_key]
                                    if 0 <= note <= 127:
                                        self.port.send(mido.Message('note_on', note=note, velocity=127))
                                        note_name = self.note_names.get(note, "Unknown")
                                        self.log_message(f"十字键{hat_key} 按下 -> 音符{note}({note_name})")
                                    button_states[hat_key] = True
                                    
                            elif not is_pressed and last_state:
                                if hat_key in current_config["note_mappings"]:
                                    note = current_config["note_mappings"][hat_key]
                                    if 0 <= note <= 127:
                                        self.port.send(mido.Message('note_off', note=note, velocity=0))
                                    button_states[hat_key] = False
                                    
                except Exception as e:
                    self.log_message(f"处理十字键时出错: {e}")
                
                # 处理扳机键（轴）
                try:
                    if self.joystick.get_numaxes() > 4:  # 确保有扳机轴
                        lt_value = self.joystick.get_axis(4)  # 左扳机
                        rt_value = self.joystick.get_axis(5)  # 右扳机
                        
                        # 处理LT
                        lt_pressed = lt_value > 0.5
                        lt_last_state = button_states.get("trigger_lt", False)
                        
                        if lt_pressed and not lt_last_state:
                            if "lt" in current_config["note_mappings"]:
                                note = current_config["note_mappings"]["lt"]
                                if 0 <= note <= 127:
                                    self.port.send(mido.Message('note_on', note=note, velocity=127))
                                    note_name = self.note_names.get(note, "Unknown")
                                    self.log_message(f"LT扳机按下 -> 音符{note}({note_name})")
                                button_states["trigger_lt"] = True
                        elif not lt_pressed and lt_last_state:
                            if "lt" in current_config["note_mappings"]:
                                note = current_config["note_mappings"]["lt"]
                                if 0 <= note <= 127:
                                    self.port.send(mido.Message('note_off', note=note, velocity=0))
                                button_states["trigger_lt"] = False
                        
                        # 处理RT
                        rt_pressed = rt_value > 0.5
                        rt_last_state = button_states.get("trigger_rt", False)
                        
                        if rt_pressed and not rt_last_state:
                            if "rt" in current_config["note_mappings"]:
                                note = current_config["note_mappings"]["rt"]
                                if 0 <= note <= 127:
                                    self.port.send(mido.Message('note_on', note=note, velocity=127))
                                    note_name = self.note_names.get(note, "Unknown")
                                    self.log_message(f"RT扳机按下 -> 音符{note}({note_name})")
                                button_states["trigger_rt"] = True
                        elif not rt_pressed and rt_last_state:
                            if "rt" in current_config["note_mappings"]:
                                note = current_config["note_mappings"]["rt"]
                                if 0 <= note <= 127:
                                    self.port.send(mido.Message('note_off', note=note, velocity=0))
                                button_states["trigger_rt"] = False
                            
                except Exception as e:
                    self.log_message(f"处理扳机键时出错: {e}")

                time.sleep(0.005)

        except Exception as e:
            if self.is_running:  # 只在运行时记录错误
                self.log_message(f"控制循环错误: {e}")
    
    def handle_stick_relative(self, stick_value, cc_num, current_cc_values, stick_name, config):
        """处理摇杆的相对控制"""
        try:
            # 验证参数
            if not isinstance(cc_num, int) or cc_num < 1 or cc_num > 127:
                return
                
            # 应用死区
            if abs(stick_value) < config.get("stick_deadzone", 0.15):
                return  # 在死区内，不做任何改变
            
            # 计算CC值的变化量
            max_change_per_update = config.get("relative_sensitivity", 3.0)
            cc_delta = stick_value * max_change_per_update
            
            # 获取当前CC值，如果不存在则初始化为64
            current_value = current_cc_values.get(cc_num, 64)
            
            # 计算新的CC值
            new_value = current_value + cc_delta
            
            # 限制在0-127范围内
            new_value = max(0, min(127, new_value))
            
            # 转换为整数
            new_value_int = int(round(new_value))
            
            # 只有当值发生变化时才发送MIDI消息
            if new_value_int != int(round(current_value)):
                self.port.send(mido.Message('control_change', control=cc_num, value=new_value_int))
                self.log_message(f"{stick_name} CC{cc_num}: {int(round(current_value))} -> {new_value_int}")
                
                # 更新存储的当前值
                current_cc_values[cc_num] = new_value
                
        except Exception as e:
            self.log_message(f"处理摇杆{stick_name}时出错: {e}")
    
    def on_closing(self):
        """窗口关闭事件处理"""
        if self.is_running:
            self.stop_controller()
        self.root.destroy()
    
    def run(self):
        """运行应用"""
        self.root.mainloop()

if __name__ == "__main__":
    app = GamepadMIDIController()
    app.run()