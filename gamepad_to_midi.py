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
# 您可以在DAW中将这两个CC号链接到不同的参数
LEFT_STICK_X_CC = 1  # 左摇杆左右移动
LEFT_STICK_Y_CC = 2  # 左摇杆上下移动

# MIDI 音符，用于按键触发 (可以根据喜好修改)
BUTTON_A_NOTE = 60  # 按钮 A -> C4 (中央C)
BUTTON_B_NOTE = 62  # 按钮 B -> D4
BUTTON_X_NOTE = 64  # 按钮 X -> E4
BUTTON_Y_NOTE = 65  # 按钮 Y -> F4

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

    print("\n驱动已启动。移动摇杆或按下按键来发送MIDI信号。按 Ctrl+C 退出。")

    # 用于存储按键状态，防止重复发送Note On消息
    button_states = {}
    # 用于存储摇杆CC值，只有在值变化时才发送，以提高效率
    last_cc_values = {}

    try:
        while True:
            # 处理pygame事件队列
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return

            # --- 处理摇杆 ---
            # 读取左摇杆的X和Y轴 (-1.0 to 1.0)
            left_stick_x = joystick.get_axis(0)
            left_stick_y = joystick.get_axis(1)

            # 将 -1.0 到 1.0 的范围映射到 0 到 127
            cc_x_val = int((left_stick_x + 1) * 63.5)
            cc_y_val = int((left_stick_y + 1) * 63.5)

            # 仅当CC值变化时才发送MIDI消息
            send_cc_if_changed(port, LEFT_STICK_X_CC, cc_x_val, last_cc_values)
            send_cc_if_changed(port, LEFT_STICK_Y_CC, cc_y_val, last_cc_values)

            # --- 处理按键 ---
            # Xbox手柄按键ID通常是: 0:A, 1:B, 2:X, 3:Y
            handle_button(port, joystick, 0, BUTTON_A_NOTE, button_states)
            handle_button(port, joystick, 1, BUTTON_B_NOTE, button_states)
            handle_button(port, joystick, 2, BUTTON_X_NOTE, button_states)
            handle_button(port, joystick, 3, BUTTON_Y_NOTE, button_states)

            # 稍微等待，避免CPU占用过高
            time.sleep(0.01)

    except KeyboardInterrupt:
        print("\n程序已退出。")
    finally:
        # 关闭端口和pygame
        port.close()
        pygame.quit()

def send_cc_if_changed(port, cc_num, value, last_values):
    """仅当CC值发生变化时才发送MIDI CC消息"""
    if last_values.get(cc_num) != value:
        port.send(mido.Message('control_change', control=cc_num, value=value))
        # print(f"CC {cc_num}: {value}") # 取消此行注释以查看CC值的实时输出
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

if __name__ == '__main__':
    main()