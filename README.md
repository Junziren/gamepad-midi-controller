# Gamepad MIDI Studio（游戏手柄MIDI表演工具套件）

一个基于 **Python 3.13 + pywebview（玻璃拟态 UI）** 的独立 MIDI 表演工具套件：
游戏手柄 → MIDI 转换、鼠标/键盘演奏工具、音序器与 Clip、MIDI 中间件路由。
**无需安装 loopMIDI** —— 内置 teVirtualMIDI 虚拟端口内核（loopMIDI 同款签名驱动），启动自动创建端口。

## ✨ 功能总览

| 模块 | 说明 |
|------|------|
| 手柄引擎 | 加速度/相对模式 + 坐标映射模式（按住 L3/R3 绝对映射）、响应曲线、死区、力度模式、MIDI Learn |
| 虚拟 MIDI 端口 | teVirtualMIDI 内核自动创建端口（默认 `Gamepad MIDI 1`），内核接口预留 Windows MIDI Services |
| 鼠标 XY 控制器 | 按住热键（默认 Ctrl+Alt），鼠标屏幕位置 → 绝对双 CC |
| 屏幕 XY Pad | UI 内拖拽 → 绝对双 CC |
| 键盘打击垫 | 电脑键盘 → MIDI 音符，支持固定/随机力度与独占模式 |
| 和弦 / 琶音器 | 一键和弦，琶音模式：上行/下行/上下行/随机 |
| 热键 MIDI Clip | 全局热键触发预设 MIDI 事件序列（可循环），支持表演录制生成 Clip |
| 步进音序器 | 8/16/32 步循环、BPM、Swing、摇杆实时调制（音高/CC） |
| 滚轮弯音 | 按住热键 + 滚轮 → 14bit Pitch Bend 或 CC 增量 |
| MIDI 映射层 | 虚拟输入端口 → 通道转发/音高偏移/CC 缩放/音符过滤 → 输出端口 |
| 多预设 Profile | 配置一键切换、导入导出、旧版配置自动迁移 |

## 🎮 手柄操作说明

- **加速度 / 相对模式（默认）**：推动摇杆改变 CC 值，摇杆归位停止变化（不回中），灵敏度/死区/曲线可调。
- **坐标映射模式**（主控台切换，可选逻辑，不替代加速度模式）：
  - 按住 **L3**：左摇杆实时绝对映射 XY → CC（回中 = 64）
  - 按住 **R3**：右摇杆同理
  - 松开后停止更新，CC 值保持；按下瞬间从当前位置直接映射（触摸式拖拽手感）
- **扳机 LT/RT**：可配置为 开关音符 / 模拟 CC / 音符+扳机力度。
- **按键力度**：固定值 / 按住时长增长 / 随机。
- **MIDI Learn**：映射表中点「学习」→ 按手柄按键 / 推动摇杆 / 按键盘键，自动绑定。

## 📦 安装与运行

```bat
install_dependencies.bat        # 或 python -m pip install -r requirements.txt
python -m gms
```

系统要求：Windows 10/11 64 位、Python 3.11+、WebView2 运行时（Win11 自带）。

## 🔌 虚拟 MIDI 端口

- 程序启动自动创建虚拟端口（teVirtualMIDI 内核），DAW 中直接启用该输入端口即可，无需安装 loopMIDI。
- 系统已装 loopMIDI 时也兼容：端口列表会枚举全部系统输出端口，可在设置中选择。
- 内核缺失时自动降级为「仅使用系统端口」，界面状态灯提示。

## 🧪 测试

```bat
python -m unittest discover -s tests -v
```

## 📦 打包分发

```bat
build.bat   # 产物：dist\GamepadMIDIStudio\GamepadMIDIStudio.exe
```

打包后首次运行仍会自动创建虚拟 MIDI 端口；若目标机器缺少 teVirtualMIDI 驱动，将自动降级为系统端口模式。

## 🗂 目录结构

```
gms/
  main.py               # 入口（python -m gms）
  app.py                # pywebview 壳 + js_api 桥 + 组件装配
  bus.py                # 事件总线
  config.py             # 多预设 Profile + 旧版配置迁移
  core.py               # 纯计算函数（曲线/映射/音序器/规则）
  learn.py              # MIDI Learn 管理器
  midi/                 # teVirtualMIDI 内核 + MIDI 输出引擎
  input/                # 手柄引擎 + 全局键盘/鼠标钩子
  tools/                # 8 个可插拔工具
  ui/                   # 玻璃拟态前端（HTML/CSS/JS）
tests/                  # 单元测试
profiles/               # 用户预设（不入库）
```

## 📝 更新日志

### v0.1.1
- 修复十字键(hat)音符映射，主控台新增 ←→ 指示灯
- 音序器可视化编辑：编辑模式选中格子，调音高/力度/门限/八度
- 键盘打击垫逐格 MIDI Learn（格子右上角 L）
- 打包支持：`build.bat` → `dist\GamepadMIDIStudio\GamepadMIDIStudio.exe`

### v0.1.0（重构版）
- 全新玻璃拟态 UI（pywebview + WebView2）
- 内置 teVirtualMIDI 虚拟端口，摆脱 loopMIDI 依赖
- 新增坐标映射模式（按住 L3/R3 绝对映射）
- 扳机/力度/曲线/平滑全面升级，MIDI Learn 自动绑定
- 新增 8 个表演工具：鼠标 XY、屏幕 XY Pad、键盘打击垫、和弦琶音、热键 Clip、步进音序器、滚轮弯音、MIDI 映射层
- 多预设 Profile 与旧配置迁移

## 📄 许可证

本软件仅供个人和教育用途使用。teVirtualMIDI 为 Tobias Erichsen 免费 SDK（loopMIDI 同源内核）。