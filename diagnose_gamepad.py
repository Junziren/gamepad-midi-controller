# -*- coding: utf-8 -*-
"""手柄输入链路诊断工具（独立于 GMS 运行，不依赖配置/界面）。

用法：
    python diagnose_gamepad.py [手柄索引]

连接手柄后运行，然后依次按 A/B/X/Y、肩键、推动两个摇杆和扳机。
脚本分别用三条链路读取并打印变化：
    [XInput]   Windows 原生 XInput 状态（Xbox 兼容手柄主链路）
    [EVT]      SDL 事件驱动缓存（引擎 SdlEventJoystick 的机制）
    [HID]      pywinusb 语义解码（引擎 HidJoystick 的机制）
哪一路没有输出，就说明问题出在哪一层。
"""

import sys
import time

import pygame


def fmt_axes(axes):
    return " ".join(f"{v:+.3f}" for v in axes)


def fmt_buttons(buttons):
    return "".join("1" if b else "." for b in buttons)


def try_hid(vid, pid, source):
    try:
        from gms.input.gamepad_devices import HidJoystick
        from pywinusb import hid
    except Exception as exc:
        print(f"[HID] 不可用: {exc}")
        return None
    devices = hid.HidDeviceFilter(vendor_id=vid, product_id=pid).get_devices()
    for dev in devices:
        try:
            j = HidJoystick(dev, source)
            print(f"[HID] 已打开 {dev.product_name} backend=Windows HID "
                  f"buttons={j.get_numbuttons()} axes={j.get_numaxes()}")
            return j
        except Exception as exc:
            try:
                dev.close()
            except Exception:
                pass
            print(f"[HID] 打开失败({exc})，尝试下一个接口…")
    return None


def try_xinput(source=None):
    try:
        from gms.input.gamepad_devices import XInputJoystick
        joystick = XInputJoystick.try_open(source)
    except Exception as exc:
        print(f"[XInput] 不可用: {exc}")
        return None
    if joystick is not None:
        print(f"[XInput] 已打开 {joystick.get_name()} slot={joystick._slot}")
    return joystick


def main():
    idx = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    pygame.init()
    pygame.joystick.init()
    count = pygame.joystick.get_count()
    if count == 0:
        xinput_joy = try_xinput()
        if xinput_joy is None:
            print("未检测到手柄。请先连接手柄（蓝牙配对或 USB 插入）后重试。")
            return
        print("\n使用无 SDL 句柄的 XInput 手柄，10 秒内请操作：\n")
        last = None
        deadline = time.time() + 10.0
        while time.time() < deadline:
            xinput_joy.poll_refresh()
            axes, buttons, hat, *_ = xinput_joy.snapshot()
            current = (axes, buttons, hat)
            if current != last:
                print(f"[XInput] axes=[{fmt_axes(axes)}] buttons=[{fmt_buttons(buttons)}] hat={hat}")
                last = current
            time.sleep(0.02)
        xinput_joy.quit()
        return
    print(f"检测到 {count} 个手柄：")
    for i in range(count):
        j = pygame.joystick.Joystick(i)
        j.init()
        vid = pid = 0
        try:
            vid, pid = j.get_vendor(), j.get_product()
        except Exception:
            pass
        print(f"  [{i}] {j.get_name()}  guid={j.get_guid()}  "
              f"vid={vid:04x} pid={pid:04x}  "
              f"axes={j.get_numaxes()} buttons={j.get_numbuttons()} hats={j.get_numhats()}")

    js = pygame.joystick.Joystick(idx)
    js.init()
    print(f"\n使用手柄 [{idx}] {js.get_name()}，10 秒内请操作：\n")
    n_axes = js.get_numaxes()
    n_buttons = js.get_numbuttons()
    n_hats = js.get_numhats()

    vid = pid = 0
    try:
        vid, pid = js.get_vendor(), js.get_product()
    except Exception:
        pass
    hid_joy = try_hid(vid, pid, js)
    xinput_joy = try_xinput(js) if vid == 0x045E or "xbox" in js.get_name().lower() else None

    last_sdl = [js.get_axis(i) for i in range(n_axes)]
    last_sdl_b = [bool(js.get_button(i)) for i in range(n_buttons)]
    last_sdl_h = js.get_hat(0) if n_hats else (0, 0)
    evt_axes = list(last_sdl)
    evt_buttons = list(last_sdl_b)
    evt_hat = last_sdl_h
    last_hid = None
    if hid_joy is not None:
        last_hid = ([hid_joy.get_axis(i) for i in range(hid_joy.get_numaxes())],
                     [bool(hid_joy.get_button(i)) for i in range(hid_joy.get_numbuttons())],
                     hid_joy.get_hat(0))
    last_xinput = None
    if xinput_joy is not None:
        last_xinput = xinput_joy.snapshot()[:3]

    def snapshot_sdl():
        axes = [js.get_axis(i) for i in range(n_axes)]
        buttons = [bool(js.get_button(i)) for i in range(n_buttons)]
        hat = js.get_hat(0) if n_hats else (0, 0)
        return axes, buttons, hat

    def snapshot_hid():
        if hid_joy is None:
            return None
        return ([hid_joy.get_axis(i) for i in range(hid_joy.get_numaxes())],
                [bool(hid_joy.get_button(i)) for i in range(hid_joy.get_numbuttons())],
                hid_joy.get_hat(0))

    deadline = time.time() + 10.0
    while time.time() < deadline:
        pygame.event.pump()
        for ev in pygame.event.get():
            if ev.type in (pygame.JOYAXISMOTION, pygame.JOYBUTTONDOWN,
                           pygame.JOYBUTTONUP, pygame.JOYHATMOTION):
                print(f"[EVT] {pygame.event.event_name(ev.type)} "
                      f"joy={getattr(ev, 'joy', '?')} "
                      f"instance={getattr(ev, 'instance_id', '?')} "
                      f"{getattr(ev, 'axis', '')}{getattr(ev, 'value', '')}"
                      f"{getattr(ev, 'button', '')}{getattr(ev, 'hat', '')}")
                if ev.type == pygame.JOYAXISMOTION:
                    evt_axes[ev.axis] = float(ev.value)
                elif ev.type in (pygame.JOYBUTTONDOWN, pygame.JOYBUTTONUP):
                    evt_buttons[ev.button] = ev.type == pygame.JOYBUTTONDOWN
                elif ev.type == pygame.JOYHATMOTION:
                    evt_hat = tuple(ev.value)
        axes, buttons, hat = snapshot_sdl()
        if (axes, buttons, hat) != (last_sdl, last_sdl_b, last_sdl_h):
            print(f"[SDL] axes=[{fmt_axes(axes)}] buttons=[{fmt_buttons(buttons)}] "
                  f"hat={hat}  |  EVT缓存 buttons=[{fmt_buttons(evt_buttons)}]")
            last_sdl, last_sdl_b, last_sdl_h = axes, buttons, hat
        if hid_joy is not None:
            hid_state = snapshot_hid()
            if hid_state != last_hid:
                ha, hb, hh = hid_state
                print(f"[HID] axes=[{fmt_axes(ha)}] buttons=[{fmt_buttons(hb)}] hat={hh}")
                last_hid = hid_state
            if hid_joy.has_fault():
                print(f"[HID] 故障: {hid_joy.fault_reason()}")
        if xinput_joy is not None:
            xinput_joy.poll_refresh()
            xinput_state = xinput_joy.snapshot()[:3]
            if xinput_state != last_xinput:
                xa, xb, xh = xinput_state
                print(f"[XInput] axes=[{fmt_axes(xa)}] buttons=[{fmt_buttons(xb)}] hat={xh}")
                last_xinput = xinput_state
        time.sleep(0.02)
    print("\n诊断完成。")
    if hid_joy is not None:
        hid_joy.quit()
    if xinput_joy is not None:
        xinput_joy.quit()


if __name__ == "__main__":
    main()
