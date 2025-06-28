import pygame
import mido
import time

# 设置mido使用pygame作为MIDI后端
mido.set_backend('mido.backends.pygame')

# --- 配置 ---
# 确保这个名字与你在loopMIDI中创建的端口名完全一致
# 如果loopMIDI中端口名是 'loopMIDI Port', 这里就改成 'loopMIDI Port'
MIDI_PORT_NAME = 'Gamepad MIDI 1' 

JOYSTICK_ID = 0  # 通常第一个连接的手柄ID是0

# MIDI CC (Continuous Controller) 号码，用于摇杆控制
# 您可以在DAW中将这些CC号链接到不同的参数
LEFT_STICK_X_CC = 1   # 左摇杆左右移动
LEFT_STICK_Y_CC = 2   # 左摇杆上下移动
RIGHT_STICK_X_CC = 3  # 右摇杆左右移动
RIGHT_STICK_Y_CC = 4  # 右摇杆上下移动

# 摇杆相对控制配置
STICK_DEADZONE = 0.15  # 摇杆死区，避免微小抖动和意外触发
RELATIVE_SENSITIVITY = 15.0  # 相对控制灵敏度，数值越大变化越快
UPDATE_INTERVAL = 0.05  # 更新间隔（秒），控制发送频率

# MIDI 音符，用于按键触发 (可以根据喜好修改)
# ABXY按键
BUTTON_A_NOTE = 60  # 按钮 A -> C4 (中央C)
BUTTON_B_NOTE = 62  # 按钮 B -> D4
BUTTON_X_NOTE = 64  # 按钮 X -> E4
BUTTON_Y_NOTE = 65  # 按钮 Y -> F4

# 十字键
DPAD_UP_NOTE = 67     # 十字键上 -> G4
DPAD_DOWN_NOTE = 69   # 十字键下 -> A4
DPAD_LEFT_NOTE = 71   # 十字键左 -> B4
DPAD_RIGHT_NOTE = 72  # 十字键右 -> C5

# 肩键和扳机键
LB_NOTE = 74          # 左肩键 -> D5
RB_NOTE = 76          # 右肩键 -> E5
LT_NOTE = 77          # 左扳机键 -> F5
RT_NOTE = 79          # 右扳机键 -> G5

# ----------- #

def main():
    # 初始化pygame
    pygame.init()
    pygame.joystick.init()

    # 检查手柄是否连接
    joystick_count = pygame.joystick.get_count()
    if joystick_count == 0:
        print("错误：没有检测到手柄。请确保手柄已连接并被Windows识别。")
        return

    joystick = pygame.joystick.Joystick(JOYSTICK_ID)
    joystick.init()
    print(f"成功连接到手柄: {joystick.get_name()}")

    # 打开MIDI端口
    try:
        port = mido.open_output(MIDI_PORT_NAME)
        print(f"成功打开MIDI端口: {MIDI_PORT_NAME}")
    except (IOError, ValueError) as e:
        print(f"错误：无法打开MIDI端口 '{MIDI_PORT_NAME}'.")
        print("请确保loopMIDI已运行，并且上面的 MIDI_PORT_NAME 变量与loopMIDI中创建的端口名完全一致。")
        print(f"当前可用的MIDI输出端口: {mido.get_output_names()}")
        return

    print("\n驱动已启动（相对控制模式）。")
    print("摇杆控制说明：")
    print("- 向上/右推摇杆：增加对应参数的CC值")
    print("- 向下/左推摇杆：减少对应参数的CC值")
    print("- 摇杆归位：停止改变参数值")
    print("- 按键功能保持不变")
    print("按 Ctrl+C 退出。\n")

    # 用于存储按键状态，防止重复发送Note On消息
    button_states = {}
    
    # 用于跟踪当前CC值（从中心值64开始）
    current_cc_values = {
        LEFT_STICK_X_CC: 64,
        LEFT_STICK_Y_CC: 64,
        RIGHT_STICK_X_CC: 64,
        RIGHT_STICK_Y_CC: 64
    }
    
    # 用于控制更新频率
    last_update_time = time.time()

    try:
        while True:
            current_time = time.time()
            
            # 处理pygame事件队列
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return

            # 按照设定的间隔更新摇杆控制
            if current_time - last_update_time >= UPDATE_INTERVAL:
                # --- 处理左摇杆（相对控制模式）---
                left_stick_x = joystick.get_axis(0)  # 左右轴
                left_stick_y = -joystick.get_axis(1)  # 上下轴（取负值，使向上为正）

                handle_stick_relative(port, left_stick_x, LEFT_STICK_X_CC, current_cc_values, "左摇杆X")
                handle_stick_relative(port, left_stick_y, LEFT_STICK_Y_CC, current_cc_values, "左摇杆Y")

                # --- 处理右摇杆（相对控制模式）---
                right_stick_x = joystick.get_axis(2)  # 左右轴
                right_stick_y = -joystick.get_axis(3)  # 上下轴（取负值，使向上为正）

                handle_stick_relative(port, right_stick_x, RIGHT_STICK_X_CC, current_cc_values, "右摇杆X")
                handle_stick_relative(port, right_stick_y, RIGHT_STICK_Y_CC, current_cc_values, "右摇杆Y")
                
                last_update_time = current_time

            # --- 处理ABXY按键 ---
            # Xbox手柄按键ID通常是: 0:A, 1:B, 2:X, 3:Y
            handle_button(port, joystick, 0, BUTTON_A_NOTE, button_states)
            handle_button(port, joystick, 1, BUTTON_B_NOTE, button_states)
            handle_button(port, joystick, 2, BUTTON_X_NOTE, button_states)
            handle_button(port, joystick, 3, BUTTON_Y_NOTE, button_states)

            # --- 处理十字键 ---
            # 在某些手柄上，十字键可能是按钮或者是hat
            # 尝试使用hat（帽子开关）方式读取十字键
            try:
                hat = joystick.get_hat(0)  # 通常第一个hat是十字键
                
                # hat返回一个元组(x, y)，其中x是-1(左)、0(中)或1(右)，y是-1(下)、0(中)或1(上)
                # 处理上下方向
                handle_hat_button(port, hat[1] == 1, "dpad_up", DPAD_UP_NOTE, button_states)
                handle_hat_button(port, hat[1] == -1, "dpad_down", DPAD_DOWN_NOTE, button_states)
                
                # 处理左右方向
                handle_hat_button(port, hat[0] == -1, "dpad_left", DPAD_LEFT_NOTE, button_states)
                handle_hat_button(port, hat[0] == 1, "dpad_right", DPAD_RIGHT_NOTE, button_states)
            except pygame.error:
                # 如果没有hat，可能十字键是作为按钮实现的
                # 这里需要知道具体的按钮ID，可能需要调试确定
                pass

            # --- 处理肩键 ---
            # 肩键通常是按钮，但ID可能因手柄而异
            # 通常Xbox手柄上LB是4，RB是5
            handle_button(port, joystick, 4, LB_NOTE, button_states)
            handle_button(port, joystick, 5, RB_NOTE, button_states)

            # --- 处理扳机键 ---
            # 扳机键通常是轴，而不是按钮
            # 通常Xbox手柄上LT是轴4，RT是轴5
            try:
                lt_value = joystick.get_axis(4)  # 左扳机键
                rt_value = joystick.get_axis(5)  # 右扳机键
                
                # 扳机键通常从-1(未按)到1(完全按下)
                # 我们将其视为按钮，当值大于阈值时触发
                handle_trigger(port, lt_value > 0.5, "lt", LT_NOTE, button_states)
                handle_trigger(port, rt_value > 0.5, "rt", RT_NOTE, button_states)
            except pygame.error:
                # 如果读取轴失败，可能扳机键是以其他方式实现的
                pass

            # 稍微等待，避免CPU占用过高
            time.sleep(0.005)

    except KeyboardInterrupt:
        print("\n程序已退出。")
    finally:
        # 关闭端口和pygame
        port.close()
        pygame.quit()

def handle_stick_relative(port, stick_value, cc_num, current_cc_values, stick_name):
    """
    处理摇杆的相对控制
    stick_value: 摇杆当前位置 (-1.0 到 1.0)
    cc_num: 对应的MIDI CC号
    current_cc_values: 当前CC值字典
    stick_name: 摇杆名称（用于调试输出）
    """
    # 应用死区，避免微小抖动
    if abs(stick_value) < STICK_DEADZONE:
        return  # 在死区内，不做任何改变
    
    # 计算CC值的变化量
    # stick_value范围是-1到1，我们将其映射到CC变化量
    # 最大变化量基于灵敏度设置
    max_change_per_update = RELATIVE_SENSITIVITY
    cc_delta = stick_value * max_change_per_update
    
    # 获取当前CC值
    current_value = current_cc_values[cc_num]
    
    # 计算新的CC值
    new_value = current_value + cc_delta
    
    # 限制在0-127范围内
    new_value = max(0, min(127, new_value))
    
    # 转换为整数
    new_value_int = int(round(new_value))
    
    # 只有当值发生变化时才发送MIDI消息
    if new_value_int != int(round(current_value)):
        port.send(mido.Message('control_change', control=cc_num, value=new_value_int))
        print(f"{stick_name} CC{cc_num}: {int(round(current_value))} -> {new_value_int} (摇杆: {stick_value:.2f})")
        
        # 更新存储的当前值
        current_cc_values[cc_num] = new_value

def send_cc_if_changed(port, cc_num, value, last_values):
    """仅当CC值发生变化时才发送MIDI CC消息（保留用于其他可能的用途）"""
    if last_values.get(cc_num) != value:
        port.send(mido.Message('control_change', control=cc_num, value=value))
        last_values[cc_num] = value

def handle_button(port, joystick, button_id, note, states):
    """处理单个按键的按下和释放事件"""
    is_pressed = joystick.get_button(button_id)
    last_state = states.get(button_id, False)

    if is_pressed and not last_state:
        # 按下
        port.send(mido.Message('note_on', note=note, velocity=127))
        print(f"Note On: {note}")
        states[button_id] = True
    elif not is_pressed and last_state:
        # 释放
        port.send(mido.Message('note_off', note=note, velocity=0))
        print(f"Note Off: {note}")
        states[button_id] = False

def handle_hat_button(port, is_pressed, button_id, note, states):
    """处理十字键（hat）的按下和释放事件"""
    last_state = states.get(button_id, False)

    if is_pressed and not last_state:
        # 按下
        port.send(mido.Message('note_on', note=note, velocity=127))
        print(f"Note On: {note} (Hat {button_id})")
        states[button_id] = True
    elif not is_pressed and last_state:
        # 释放
        port.send(mido.Message('note_off', note=note, velocity=0))
        print(f"Note Off: {note} (Hat {button_id})")
        states[button_id] = False

def handle_trigger(port, is_pressed, trigger_id, note, states):
    """处理扳机键的按下和释放事件"""
    last_state = states.get(trigger_id, False)

    if is_pressed and not last_state:
        # 按下
        port.send(mido.Message('note_on', note=note, velocity=127))
        print(f"Note On: {note} (Trigger {trigger_id})")
        states[trigger_id] = True
    elif not is_pressed and last_state:
        # 释放
        port.send(mido.Message('note_off', note=note, velocity=0))
        print(f"Note Off: {note} (Trigger {trigger_id})")
        states[trigger_id] = False

if __name__ == '__main__':
    main()