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
        self.root.geometry("800x600")
        
        # 配置文件路径
        self.config_file = "gamepad_midi_config.json"
        
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
        
        # 运行状态
        self.is_running = False
        self.controller_thread = None
        self.port = None
        self.joystick = None
        
        # 先创建GUI，再加载配置
        self.create_gui()
        self.load_config()
        
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
        ttk.Label(main_frame, text="MIDI端口:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.midi_port_var = tk.StringVar(value=self.config["midi_port"])
        midi_port_entry = ttk.Entry(main_frame, textvariable=self.midi_port_var, width=30)
        midi_port_entry.grid(row=1, column=1, sticky=(tk.W, tk.E), pady=5, padx=(10, 0))
        
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
        note_frame.columnconfigure(1, weight=1)
        note_frame.columnconfigure(3, weight=1)
        note_frame.columnconfigure(5, weight=1)
        note_frame.columnconfigure(7, weight=1)
        
        # 创建音符映射控件
        self.note_vars = {}
        note_labels = [
            ("A键:", "button_a"), ("B键:", "button_b"), ("X键:", "button_x"), ("Y键:", "button_y"),
            ("十字键↑:", "dpad_up"), ("十字键↓:", "dpad_down"), ("十字键←:", "dpad_left"), ("十字键→:", "dpad_right"),
            ("LB键:", "lb"), ("RB键:", "rb"), ("LT键:", "lt"), ("RT键:", "rt")
        ]
        
        for i, (label, key) in enumerate(note_labels):
            row = i // 4
            col = (i % 4) * 2
            
            ttk.Label(note_frame, text=label).grid(row=row, column=col, sticky=tk.W, pady=2)
            self.note_vars[key] = tk.IntVar(value=self.config["note_mappings"][key])
            ttk.Spinbox(note_frame, from_=0, to=127, textvariable=self.note_vars[key], width=8).grid(
                row=row, column=col+1, sticky=tk.W, pady=2, padx=(5, 15))
        
        # 控制按钮
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=5, column=0, columnspan=3, pady=20)
        
        self.start_button = ttk.Button(button_frame, text="启动控制器", command=self.toggle_controller)
        self.start_button.pack(side=tk.LEFT, padx=5)
        
        ttk.Button(button_frame, text="保存配置", command=self.save_config).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="加载配置", command=self.load_config).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="重置默认", command=self.reset_config).pack(side=tk.LEFT, padx=5)
        
        # 状态显示
        self.status_var = tk.StringVar(value="就绪")
        status_label = ttk.Label(main_frame, textvariable=self.status_var, font=("Arial", 10))
        status_label.grid(row=6, column=0, columnspan=3, pady=10)
        
        # 日志显示
        log_frame = ttk.LabelFrame(main_frame, text="运行日志", padding="5")
        log_frame.grid(row=7, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady=10)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        main_frame.rowconfigure(7, weight=1)
        
        self.log_text = tk.Text(log_frame, height=8, wrap=tk.WORD)
        scrollbar = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        
    def update_sensitivity_label(self, value):
        self.sensitivity_label.config(text=f"{float(value):.1f}")
        
    def log_message(self, message):
        """在日志区域显示消息"""
        if hasattr(self, 'log_text'):
            self.log_text.insert(tk.END, f"{time.strftime('%H:%M:%S')} - {message}\n")
            self.log_text.see(tk.END)
            self.root.update_idletasks()
        
    def toggle_controller(self):
        if not self.is_running:
            self.start_controller()
        else:
            self.stop_controller()
            
    def start_controller(self):
        try:
            # 更新配置
            self.update_config_from_gui()
            
            # 初始化pygame
            pygame.init()
            pygame.joystick.init()
            
            # 检查手柄
            joystick_count = pygame.joystick.get_count()
            if joystick_count == 0:
                raise Exception("没有检测到手柄")
                
            self.joystick = pygame.joystick.Joystick(self.config["joystick_id"])
            self.joystick.init()
            
            # 打开MIDI端口
            self.port = mido.open_output(self.config["midi_port"])
            
            # 启动控制线程
            self.is_running = True
            self.controller_thread = threading.Thread(target=self.controller_loop, daemon=True)
            self.controller_thread.start()
            
            self.start_button.config(text="停止控制器")
            self.status_var.set("运行中")
            self.log_message(f"控制器已启动 - 手柄: {self.joystick.get_name()}")
            
        except Exception as e:
            messagebox.showerror("错误", f"启动失败: {str(e)}")
            self.log_message(f"启动失败: {str(e)}")
            
    def stop_controller(self):
        self.is_running = False
        
        if self.controller_thread:
            self.controller_thread.join(timeout=1.0)
            
        if self.port:
            self.port.close()
            self.port = None
            
        if self.joystick:
            self.joystick.quit()
            self.joystick = None
            
        pygame.quit()
        
        self.start_button.config(text="启动控制器")
        self.status_var.set("已停止")
        self.log_message("控制器已停止")
        
    def controller_loop(self):
        """主控制循环"""
        button_states = {}
        current_cc_values = {
            self.config["cc_mappings"]["left_stick_x"]: 64,
            self.config["cc_mappings"]["left_stick_y"]: 64,
            self.config["cc_mappings"]["right_stick_x"]: 64,
            self.config["cc_mappings"]["right_stick_y"]: 64
        }
        
        last_update_time = time.time()
        
        try:
            while self.is_running:
                current_time = time.time()
                
                # 处理pygame事件
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        break
                        
                # 更新摇杆控制
                if current_time - last_update_time >= self.config["update_interval"]:
                    # 左摇杆
                    left_stick_x = self.joystick.get_axis(0)
                    left_stick_y = -self.joystick.get_axis(1)
                    
                    self.handle_stick_relative(left_stick_x, self.config["cc_mappings"]["left_stick_x"], 
                                             current_cc_values, "左摇杆X")
                    self.handle_stick_relative(left_stick_y, self.config["cc_mappings"]["left_stick_y"], 
                                             current_cc_values, "左摇杆Y")
                    
                    # 右摇杆
                    right_stick_x = self.joystick.get_axis(2)
                    right_stick_y = -self.joystick.get_axis(3)

                    self.handle_stick_relative(right_stick_x, self.config["cc_mappings"]["right_stick_x"], 
                                             current_cc_values, "右摇杆X")
                    self.handle_stick_relative(right_stick_y, self.config["cc_mappings"]["right_stick_y"], 
                                             current_cc_values, "右摇杆Y")
                    
                    # 更新按钮状态
                    for i in range(self.joystick.get_numbuttons()):
                        button_state = self.joystick.get_button(i)
                        if button_state != button_states.get(i, 0):
                            button_states[i] = button_state
                            if button_state:
                                note = self.config["note_mappings"].get(f"button_{chr(97 + i)}")
                                if note:
                                    self.port.send(mido.Message('note_on', note=note, velocity=64))
                                    self.log_message(f"按钮 {i} 被按下，发送音符 {note}")
                            else:
                                note = self.config["note_mappings"].get(f"button_{chr(97 + i)}")
                                if note:
                                    self.port.send(mido.Message('note_off', note=note, velocity=64))
                                    self.log_message(f"按钮 {i} 被释放，停止音符 {note}")

                    last_update_time = current_time

        except Exception as e:
            self.log_message(f"控制循环出错: {str(e)}")
        
    def handle_stick_relative(self, value, cc, current_cc_values, stick_name):
        """处理摇杆相对值并发送MIDI CC消息"""
        if abs(value) > self.config["stick_deadzone"]:
            cc_value = int((value + 1) / 2 * 127)  # 将[-1, 1]映射到[0, 127]
            if cc_value != current_cc_values[cc]:
                current_cc_values[cc] = cc_value
                self.port.send(mido.Message('control_change', channel=0, control=cc, value=cc_value))
                self.log_message(f"{stick_name} CC {cc} 发送值 {cc_value}")
    
    def update_config_from_gui(self):
        """从GUI更新配置"""
        self.config["midi_port"] = self.midi_port_var.get()
        self.config["relative_sensitivity"] = self.sensitivity_var.get()
        self.config["cc_mappings"]["left_stick_x"] = self.left_x_cc_var.get()
        self.config["cc_mappings"]["left_stick_y"] = self.left_y_cc_var.get()
        self.config["cc_mappings"]["right_stick_x"] = self.right_x_cc_var.get()
        self.config["cc_mappings"]["right_stick_y"] = self.right_y_cc_var.get()
        
        for key in self.note_vars:
            self.config["note_mappings"][key] = self.note_vars[key].get()
    
    def save_config(self):
        """保存配置到文件"""
        with open(self.config_file, 'w') as f:
            json.dump(self.config, f, ensure_ascii=False, indent=4)
        self.log_message("配置已保存")
    
    def load_config(self):
        """加载配置文件"""
        if os.path.exists(self.config_file):
            with open(self.config_file, 'r') as f:
                self.config = json.load(f)
            self.log_message("配置已加载")
            self.update_gui_from_config()
        else:
            self.log_message("配置文件不存在，使用默认配置")
    
    def update_gui_from_config(self):
        """从配置更新GUI"""
        self.midi_port_var.set(self.config["midi_port"])
        self.sensitivity_var.set(self.config["relative_sensitivity"])
        self.left_x_cc_var.set(self.config["cc_mappings"]["left_stick_x"])
        self.left_y_cc_var.set(self.config["cc_mappings"]["left_stick_y"])
        self.right_x_cc_var.set(self.config["cc_mappings"]["right_stick_x"])
        self.right_y_cc_var.set(self.config["cc_mappings"]["right_stick_y"])
        
        for key in self.note_vars:
            self.note_vars[key].set(self.config["note_mappings"][key])
    
    def reset_config(self):
        """重置为默认配置"""
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
    
if __name__ == "__main__":
    controller = GamepadMIDIController()
    controller.root.mainloop()