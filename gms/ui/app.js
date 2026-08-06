/* ===== Gamepad MIDI Studio 前端逻辑 ===== */

"use strict";

const state = { config: null, app: null, page: "main", learn: { active: false }, toolStates: {} };
let seqEdit = { mode: false, sel: -1 };
let clipEdit = null;  // {index, name, hotkey, loop, channel, events}

/* ---------- API 桥 ---------- */
function api(name, ...args) {
  return window.pywebview.api[name](...args);
}

/* ---------- 工具函数 ---------- */
function esc(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
function noteName(n) {
  const names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
  n = Math.max(0, Math.min(127, Math.round(n)));
  return names[n % 12] + (Math.floor(n / 12) - 1);
}
function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }

const $page = document.getElementById("page");
const toastEl = document.getElementById("toast");
function toast(msg) {
  toastEl.textContent = msg;
  toastEl.classList.add("show");
  setTimeout(() => toastEl.classList.remove("show"), 2200);
}

/* ---------- 控件生成器 ---------- */
function el(tag, cls, html) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html !== undefined) e.innerHTML = html;
  return e;
}

function field(labelText, controlEl, extra) {
  const l = el("label", "field");
  const span = el("span");
  span.appendChild(el("span", null, esc(labelText)));
  if (extra) span.appendChild(extra);
  l.appendChild(span);
  l.appendChild(controlEl);
  return l;
}

function toggleInput(checked, onchange) {
  const wrap = el("label", "switch");
  const inp = document.createElement("input");
  inp.type = "checkbox";
  inp.checked = !!checked;
  inp.addEventListener("change", () => onchange(inp.checked));
  wrap.appendChild(inp);
  wrap.appendChild(el("span", "sl"));
  return wrap;
}

function sliderInput(value, min, max, step, onchange) {
  const inp = document.createElement("input");
  inp.type = "range"; inp.min = min; inp.max = max; inp.step = step; inp.value = value;
  const out = el("output", null, value);
  inp.addEventListener("input", () => { out.textContent = inp.value; });
  inp.addEventListener("change", () => onchange(parseFloat(inp.value)));
  const holder = el("div", "row");
  holder.appendChild(inp);
  holder.appendChild(out);
  inp.style.flex = "1";
  return { holder, inp, out };
}

function selectInput(options, value, onchange) {
  const sel = document.createElement("select");
  for (const [v, label] of Object.entries(options)) {
    const o = document.createElement("option");
    o.value = v; o.textContent = label;
    if (String(v) === String(value)) o.selected = true;
    sel.appendChild(o);
  }
  sel.addEventListener("change", () => onchange(sel.value));
  return sel;
}

function numberInput(value, min, max, onchange, width) {
  const inp = document.createElement("input");
  inp.type = "number"; inp.value = value; inp.min = min; inp.max = max;
  if (width) inp.style.width = width;
  inp.addEventListener("change", () => onchange(parseInt(inp.value, 10) || 0));
  return inp;
}

function textInput(value, onchange, width) {
  const inp = document.createElement("input");
  inp.type = "text"; inp.value = value;
  if (width) inp.style.width = width;
  inp.addEventListener("change", () => onchange(inp.value));
  return inp;
}

function tdWith(control) {
  const td = document.createElement("td");
  td.appendChild(control);
  return td;
}

function card(title, hint) {
  const c = el("div", "card");
  const h = el("h3", null, esc(title));
  if (hint) h.appendChild(el("span", "hint", esc(hint)));
  c.appendChild(h);
  return c;
}

async function savePatch(patch, toolId) {
  state.config = await api("set_config", patch, toolId || "");
  updateLeds();
}

/* ---------- 页面渲染 ---------- */

function render() {
  if (!state.config) return;
  const pages = { main: renderMain, play: renderPlay, seq: renderSeq, mod: renderMod, mapper: renderMapper, settings: renderSettings };
  $page.innerHTML = "";
  (pages[state.page] || renderMain)();
  if (state.page === "play") initXYPad();
}

function pageHead(title, sub) {
  const h = el("div", "page-head");
  h.appendChild(el("h2", null, esc(title)));
  if (sub) h.appendChild(el("p", null, esc(sub)));
  return h;
}

function toggleRow(labelText, checked, onchange) {
  const r = el("div", "row");
  r.style.marginBottom = "12px";
  r.appendChild(el("span", null, esc(labelText)));
  r.appendChild(el("span", "spacer"));
  r.appendChild(toggleInput(checked, onchange));
  return r;
}

function stickViz(label, idPrefix) {
  const wrap = el("div", "stick-viz");
  const cv = document.createElement("canvas");
  cv.width = 96; cv.height = 96;
  cv.id = idPrefix + "-cv";
  const span = el("span", null, esc(label));
  const val = el("span", "muted", "");
  val.id = idPrefix + "-val";
  wrap.appendChild(cv); wrap.appendChild(span); wrap.appendChild(val);
  return wrap;
}

/* ===== 主控页 ===== */
function renderMain() {
  const cfg = state.config.gamepad;
  const vm = state.config.virtual_midi;
  $page.appendChild(pageHead("主控台", "手柄 → MIDI 核心引擎"));

  const cGp = card("手柄", "连接状态与实时可视化");
  const gp = state.app.gamepad || {};
  const row = el("div", "row");
  row.appendChild(el("span", "badge " + (gp.connected ? "ok" : "err"), esc(gp.name || (gp.connected ? "已连接" : "未连接"))));
  const startBtn = el("button", "btn primary small", gp.connected ? "重新检测" : "启动手柄");
  startBtn.onclick = async () => {
    const ok = await api("gamepad_start");
    if (!ok) toast("未检测到手柄，请连接后重试");
    refreshApp();
  };
  row.appendChild(startBtn);
  const stopBtn = el("button", "btn small", "停止");
  stopBtn.onclick = async () => { await api("gamepad_stop"); refreshApp(); };
  row.appendChild(stopBtn);
  const swBtn = el("button", "btn small", "切换手柄…");
  swBtn.onclick = async () => {
    const list = await api("gamepad_detect");
    if (!list.length) { toast("未检测到手柄"); return; }
    const desc = list.map((n, i) => i + ":" + n).join(" / ");
    const v = prompt("选择手柄索引（" + desc + "）：", String(state.config.gamepad.joystick_id));
    if (v !== null && v.trim() !== "") {
      const ok = await api("gamepad_switch", parseInt(v, 10));
      toast(ok ? "已切换手柄" : "切换失败");
      refreshApp();
    }
  };
  row.appendChild(swBtn);
  row.appendChild(el("span", "muted", "ID " + state.config.gamepad.joystick_id));
  cGp.appendChild(row);

  const viz = el("div", "pad-viz");
  viz.appendChild(stickViz("左摇杆", "lsL"));
  viz.appendChild(stickViz("右摇杆", "lsR"));
  cGp.appendChild(viz);
  const btnViz = el("div", "btn-viz");
  btnViz.style.gridTemplateColumns = "repeat(7, 1fr)";
  [["A", 0], ["B", 1], ["X", 2], ["Y", 3], ["LB", 4], ["RB", 5],
   ["◀", 6], ["▶", 7], ["L3", 8], ["R3", 9], ["↑", 10], ["↓", 11],
   ["←", 12], ["→", 13]].forEach(([name, idx]) => {
    const cell = el("div", "btn-cell");
    cell.id = "bcell-" + idx;
    cell.innerHTML = "<b>" + name + "</b>";
    btnViz.appendChild(cell);
  });
  cGp.appendChild(btnViz);
  $page.appendChild(cGp);

  const cMode = card("摇杆模式", "坐标映射模式：按住 L3/R3 才映射绝对坐标，松开保持；不替代加速度模式");
  const modeRow = el("div", "row");
  modeRow.appendChild(el("span", null, "当前模式"));
  const modeSel = selectInput(
    { relative: "加速度 / 相对模式", xy_absolute: "坐标映射模式（按住 L3/R3）" },
    cfg.mode, async v => { await savePatch({ gamepad: { mode: v } }); render(); });
  modeRow.appendChild(modeSel);
  modeRow.appendChild(el("span", "muted", cfg.mode === "xy_absolute" ? "按住 L3=左摇杆绝对XY，R3=右摇杆绝对XY；松开后 CC 值保持" : "摇杆归位停止改变参数值（不回中）"));
  cMode.appendChild(modeRow);
  $page.appendChild(cMode);

  const cParam = card("响应参数", "灵敏度 / 死区 / 曲线 / 反转 / 平滑");
  const grid = el("div", "grid cols-2");
  const sen = sliderInput(cfg.sensitivity, 0.5, 10, 0.1, debounce(v => savePatch({ gamepad: { sensitivity: v } }), 120));
  grid.appendChild(field("摇杆灵敏度", sen.holder));
  const dz = sliderInput(cfg.deadzone, 0, 0.5, 0.01, debounce(v => savePatch({ gamepad: { deadzone: v } }), 120));
  grid.appendChild(field("死区", dz.holder));
  const curveSel = selectInput({ linear: "线性", exponential: "指数" }, cfg.curve, async v => { await savePatch({ gamepad: { curve: v } }); render(); });
  grid.appendChild(field("响应曲线", curveSel));
  const expRow = el("div");
  if (cfg.curve === "exponential") {
    const expInp = sliderInput(cfg.curve_exp, 1, 4, 0.1, debounce(v => savePatch({ gamepad: { curve_exp: v } }), 120));
    expRow.appendChild(field("指数指数", expInp.holder));
  }
  grid.appendChild(expRow);
  const invRow = el("div", "row");
  invRow.appendChild(el("span", null, "Y 轴反转"));
  invRow.appendChild(toggleInput(cfg.invert_y, async v => savePatch({ gamepad: { invert_y: v } })));
  grid.appendChild(invRow);
  const sm = sliderInput(state.config.midi.smoothing, 0, 0.9, 0.05, debounce(v => savePatch({ midi: { smoothing: v } }), 120));
  grid.appendChild(field("CC 平滑 (EMA)", sm.holder));
  cParam.appendChild(grid);
  $page.appendChild(cParam);
  // 扳机 + 力度
  const cTrig = card("扳机 LT / RT", "开关音符 / 模拟 CC / 力度=扳机深度");
  const tg = el("div", "row wrap");
  tg.appendChild(field("扳机模式", selectInput(
    { note: "开关音符", cc: "模拟 CC", velocity: "音符 + 扳机力度" }, cfg.trigger_mode,
    async v => { await savePatch({ gamepad: { trigger_mode: v } }); render(); })));
  if (cfg.trigger_mode === "cc") {
    tg.appendChild(field("LT → CC", numberInput(cfg.trigger_cc_lt, 1, 127, debounce(v => savePatch({ gamepad: { trigger_cc_lt: v } }), 200))));
    tg.appendChild(field("RT → CC", numberInput(cfg.trigger_cc_rt, 1, 127, debounce(v => savePatch({ gamepad: { trigger_cc_rt: v } }), 200))));
  }
  cTrig.appendChild(tg);
  $page.appendChild(cTrig);

  const cVel = card("按键力度", "固定 / 按住增长 / 随机");
  const vg = el("div", "row wrap");
  vg.appendChild(field("力度模式", selectInput(
    { fixed: "固定值", hold: "按住时长增长", random: "随机" }, cfg.velocity_mode,
    async v => { await savePatch({ gamepad: { velocity_mode: v } }); render(); })));
  if (cfg.velocity_mode === "fixed") {
    vg.appendChild(field("固定力度", numberInput(cfg.velocity_fixed, 1, 127, debounce(v => savePatch({ gamepad: { velocity_fixed: v } }), 200))));
  } else {
    vg.appendChild(field("力度下限", numberInput(cfg.velocity_min, 1, 127, debounce(v => savePatch({ gamepad: { velocity_min: v } }), 200))));
    vg.appendChild(field("力度上限", numberInput(cfg.velocity_max, 1, 127, debounce(v => savePatch({ gamepad: { velocity_max: v } }), 200))));
  }
  cVel.appendChild(vg);
  $page.appendChild(cVel);

  // 映射表
  const cMap = card("控制映射", "点击「学习」后按下手柄按键 / 推动摇杆自动绑定");
  const btnLabels = { button_a: "A", button_b: "B", button_x: "X", button_y: "Y", lb: "LB", rb: "RB", lt: "LT", rt: "RT", dpad_up: "DPAD↑", dpad_down: "DPAD↓", dpad_left: "DPAD←", dpad_right: "DPAD→" };
  const t1 = el("table", "tbl");
  t1.innerHTML = "<tr><th>按键</th><th>音符</th><th>音名</th><th></th></tr>";
  for (const [key, label] of Object.entries(btnLabels)) {
    if (!(key in cfg.note_mappings)) continue;
    const tr = el("tr");
    tr.appendChild(el("td", null, esc(label)));
    const nInp = numberInput(cfg.note_mappings[key], 0, 127, debounce(v => savePatch({ gamepad: { note_mappings: { [key]: v } } }), 200));
    const tdN = el("td"); tdN.appendChild(nInp); tr.appendChild(tdN);
    tr.appendChild(el("td", null, '<span class="muted">' + noteName(cfg.note_mappings[key]) + "</span>"));
    const lb = el("button", "btn learn", "学习");
    lb.onclick = () => api("learn_start", { kind: "note", key });
    const tdL = el("td"); tdL.appendChild(lb); tr.appendChild(tdL);
    t1.appendChild(tr);
  }
  cMap.appendChild(t1);
  const t2 = el("table", "tbl");
  t2.innerHTML = "<tr><th>摇杆轴</th><th>CC</th><th></th></tr>";
  const axisLabels = { left_stick_x: "左摇杆 X", left_stick_y: "左摇杆 Y", right_stick_x: "右摇杆 X", right_stick_y: "右摇杆 Y" };
  for (const [key, label] of Object.entries(axisLabels)) {
    if (!(key in cfg.cc_mappings)) continue;
    const tr = el("tr");
    tr.appendChild(el("td", null, esc(label)));
    const cInp = numberInput(cfg.cc_mappings[key], 1, 127, debounce(v => savePatch({ gamepad: { cc_mappings: { [key]: v } } }), 200));
    const tdC = el("td"); tdC.appendChild(cInp); tr.appendChild(tdC);
    const lb = el("button", "btn learn", "学习");
    lb.onclick = () => api("learn_start", { kind: "cc", key });
    const tdL = el("td"); tdL.appendChild(lb); tr.appendChild(tdL);
    t2.appendChild(tr);
  }
  cMap.appendChild(t2);
  $page.appendChild(cMap);

  // 虚拟端口卡片
  const cV = card("虚拟 MIDI 端口", "teVirtualMIDI 内核（loopMIDI 同源驱动），无需安装 loopMIDI");
  const vRow = el("div", "row wrap");
  vRow.appendChild(el("span", "badge " + (state.app.ports.virtual_running ? "ok" : state.app.ports.virtual_available ? "warn" : "err"),
    state.app.ports.virtual_running ? "运行中" : state.app.ports.virtual_available ? "未运行" : "内核不可用"));
  vRow.appendChild(el("span", "muted", esc(state.app.ports.virtual_error || "")));
  vRow.appendChild(el("span", "spacer"));
  vRow.appendChild(el("span", null, "启用"));
  vRow.appendChild(toggleInput(vm.enabled, async v => savePatch({ virtual_midi: { enabled: v } })));
  cV.appendChild(vRow);
  const portRow = el("div", "row");
  portRow.appendChild(field("端口名称", textInput(vm.port_name, debounce(v => savePatch({ virtual_midi: { port_name: v } }), 400), 180)));
  cV.appendChild(portRow);
  cV.appendChild(el("div", "small-note", "修改端口名/开关会自动重建虚拟端口（热应用）"));
  $page.appendChild(cV);
}

/* ===== 演奏工具页 ===== */
function renderPlay() {
  $page.appendChild(pageHead("演奏工具", "鼠标 / 屏幕 / 键盘 / 和弦琶音"));
  const grid = el("div", "grid cols-2");

  // 鼠标XY
  const c1 = card("鼠标 XY 控制器", "按住热键时，鼠标屏幕位置 → 绝对双 CC");
  const t1 = state.config.tools.mouse_xy;
  c1.appendChild(toggleRow("启用", t1.enabled, async v => api("tool_toggle", "mouse_xy", v)));
  c1.appendChild(field("热键（按住生效）", textInput(t1.hotkey.join("+"), debounce(v => savePatch({ tools: { mouse_xy: { hotkey: v.split("+").map(s => s.trim()).filter(Boolean) } } }, "mouse_xy"), 250), 140)));
  const mrow = el("div", "row wrap");
  mrow.appendChild(field("X → CC", numberInput(t1.cc_x, 1, 127, debounce(v => savePatch({ tools: { mouse_xy: { cc_x: v } } }, "mouse_xy"), 200))));
  mrow.appendChild(field("Y → CC", numberInput(t1.cc_y, 1, 127, debounce(v => savePatch({ tools: { mouse_xy: { cc_y: v } } }, "mouse_xy"), 200))));
  const yRow = el("div", "row");
  yRow.appendChild(el("span", null, "Y 反转"));
  yRow.appendChild(toggleInput(t1.invert_y, async v => savePatch({ tools: { mouse_xy: { invert_y: v } } }, "mouse_xy")));
  mrow.appendChild(yRow);
  c1.appendChild(mrow);
  const act = el("span", "badge", "未激活");
  act.id = "mousexy-active";
  const aRow = el("div", "row");
  aRow.appendChild(el("span", "muted", "状态："));
  aRow.appendChild(act);
  c1.appendChild(aRow);
  grid.appendChild(c1);

  // 屏幕 XY Pad
  const c2 = card("屏幕 XY Pad", "拖拽 Pad → 绝对双 CC（释放保持）");
  const t2 = state.config.tools.screen_xy_pad;
  c2.appendChild(toggleRow("启用", t2.enabled, async v => api("tool_toggle", "screen_xy_pad", v)));
  const padWrap = el("div", "xy-pad-wrap");
  const pad = el("div", "xy-pad");
  pad.id = "xy-pad";
  pad.appendChild(el("div", "cross"));
  pad.appendChild(el("span", "lbl tl", "CC" + t2.cc_x + " →"));
  pad.appendChild(el("span", "lbl br", "← CC" + t2.cc_y));
  const marker = el("div", "marker");
  marker.id = "xy-marker";
  pad.appendChild(marker);
  padWrap.appendChild(pad);
  const pcfg = el("div", "grid");
  pcfg.appendChild(field("X → CC", numberInput(t2.cc_x, 1, 127, debounce(v => savePatch({ tools: { screen_xy_pad: { cc_x: v } } }, "screen_xy_pad"), 200))));
  pcfg.appendChild(field("Y → CC", numberInput(t2.cc_y, 1, 127, debounce(v => savePatch({ tools: { screen_xy_pad: { cc_y: v } } }, "screen_xy_pad"), 200))));
  const yrow = el("div", "row");
  yrow.appendChild(el("span", null, "Y 反转"));
  yrow.appendChild(toggleInput(t2.invert_y, async v => savePatch({ tools: { screen_xy_pad: { invert_y: v } } }, "screen_xy_pad")));
  pcfg.appendChild(yrow);
  padWrap.appendChild(pcfg);
  c2.appendChild(padWrap);
  grid.appendChild(c2);

  // 键盘打击垫
  const c3 = card("键盘打击垫", "电脑键盘 → MIDI 音符（全局生效）");
  const t3 = state.config.tools.keyboard_pads;
  c3.appendChild(toggleRow("启用", t3.enabled, async v => api("tool_toggle", "keyboard_pads", v)));
  const krow = el("div", "row wrap");
  krow.appendChild(field("力度模式", selectInput({ fixed: "固定", random: "随机" }, t3.velocity_mode, async v => savePatch({ tools: { keyboard_pads: { velocity_mode: v } } }, "keyboard_pads"))));
  krow.appendChild(field("力度", numberInput(t3.velocity_fixed, 1, 127, debounce(v => savePatch({ tools: { keyboard_pads: { velocity_fixed: v } } }, "keyboard_pads"), 200))));
  const supRow = el("div", "row");
  supRow.appendChild(el("span", null, "独占键盘"));
  supRow.appendChild(toggleInput(t3.suppress, async v => savePatch({ tools: { keyboard_pads: { suppress: v } } }, "keyboard_pads")));
  krow.appendChild(supRow);
  c3.appendChild(krow);
  const padGrid = el("div", "seq-grid");
  padGrid.style.gridTemplateColumns = "repeat(7, 1fr)";
  t3.pads.forEach((p, i) => {
    const cell = el("div", "seq-cell");
    cell.innerHTML = "<b>" + esc(p.key) + "</b><br>" + noteName(p.note);
    cell.title = "点击修改音符";
    cell.onclick = async () => {
      const v = prompt("音符 (0-127)：", p.note);
      if (v !== null) {
        const note = parseInt(v, 10);
        if (!isNaN(note)) await savePatch({ tools: { keyboard_pads: { pads: t3.pads.map((q, j) => j === i ? Object.assign({}, q, { note: note }) : q) } } }, "keyboard_pads");
      }
    };
    const lb = el("span", "pad-learn", "L");
    lb.title = "学习此格键盘键";
    lb.onclick = (e) => {
      e.stopPropagation();
      api("learn_start", { kind: "pad_key", index: i });
    };
    cell.appendChild(lb);
    padGrid.appendChild(cell);
  });
  c3.appendChild(padGrid);
  c3.appendChild(el("div", "small-note", "点击格子改音符；点格子右上角 L 学习键盘键（点后按任意键绑定）"));
  grid.appendChild(c3);

  // 和弦/琶音
  const c4 = card("和弦 / 琶音器", "按住键 → 一键和弦或琶音循环");
  const t4 = state.config.tools.chord_arp;
  c4.appendChild(toggleRow("启用", t4.enabled, async v => api("tool_toggle", "chord_arp", v)));
  t4.pads.forEach((p, i) => {
    const rowE = el("div", "row");
    rowE.style.marginBottom = "6px";
    rowE.appendChild(el("span", "chip", esc(p.key)));
    const chordInp = textInput(p.chord.join(" "), debounce(v => savePatch({ tools: { chord_arp: { pads: t4.pads.map((q, j) => j === i ? Object.assign({}, q, { chord: v.split(/\s+/).map(Number).filter(n => !isNaN(n)) }) : q) } } }, "chord_arp"), 250), 130);
    rowE.appendChild(field("和弦 (音高)", chordInp));
    rowE.appendChild(toggleInput(p.arp, async v => savePatch({ tools: { chord_arp: { pads: t4.pads.map((q, j) => j === i ? Object.assign({}, q, { arp: v }) : q) } } }, "chord_arp")));
    rowE.appendChild(el("span", "muted", "琶音"));
    rowE.appendChild(selectInput({ up: "上行", down: "下行", updown: "上下行", random: "随机" }, p.arp_mode, async v => savePatch({ tools: { chord_arp: { pads: t4.pads.map((q, j) => j === i ? Object.assign({}, q, { arp_mode: v }) : q) } } }, "chord_arp")));
    const lb = el("button", "btn learn small", "学习");
    lb.onclick = () => api("learn_start", { kind: "chord_key", index: i });
    rowE.appendChild(lb);
    c4.appendChild(rowE);
  });
  grid.appendChild(c4);

  $page.appendChild(grid);
}

/* ===== 序列页 ===== */
function renderSeq() {
  $page.appendChild(pageHead("序列工具", "热键 Clip 与步进音序器"));
  const grid = el("div", "grid cols-2");

  const c1 = card("热键 MIDI Clip", "全局热键触发预设 MIDI 事件序列，可循环；支持表演录制");
  const t1 = state.config.tools.hotkey_clip;
  c1.appendChild(toggleRow("启用", t1.enabled, async v => api("tool_toggle", "hotkey_clip", v)));
  const recBtn = el("button", "btn", "● 开始录制表演");
  recBtn.id = "clip-rec-btn";
  recBtn.onclick = async () => {
    await api("tool_action", "hotkey_clip", "record_start", {});
    toast("录制中：演奏的 MIDI 将保存为新 Clip（再次点击停止）");
  };
  c1.appendChild(recBtn);
  const list = el("div");
  list.id = "clip-list";
  t1.clips.forEach((clip, i) => {
    const item = el("div", "clip-item");
    item.id = "clip-" + i;
    const info = el("div");
    info.appendChild(el("div", "name", esc(clip.name)));
    info.appendChild(el("div", "meta", esc(clip.hotkey || "无热键") + " · " + clip.events.length + " 事件 · " + (clip.loop ? "循环" : "单次")));
    item.appendChild(info);
    const playBtn = el("button", "btn small", "播放");
    playBtn.onclick = () => api("tool_action", "hotkey_clip", "play", { name: clip.name });
    const editBtn = el("button", "btn small", "编辑");
    editBtn.onclick = () => {
      clipEdit = {
        index: i,
        name: clip.name,
        hotkey: clip.hotkey || "",
        loop: !!clip.loop,
        channel: clip.channel,
        events: (clip.events || []).map(e => Object.assign({}, e))
      };
      renderClipModal();
    };
    const delBtn = el("button", "btn small danger", "删除");
    delBtn.onclick = async () => {
      const clips = t1.clips.filter((_, j) => j !== i);
      await savePatch({ tools: { hotkey_clip: { clips: clips } } }, "hotkey_clip");
    };
    item.appendChild(el("span", "spacer"));
    item.appendChild(playBtn);
    item.appendChild(editBtn);
    item.appendChild(delBtn);
    list.appendChild(item);
  });
  c1.appendChild(list);
  grid.appendChild(c1);

  const c2 = card("步进音序器", "8/16/32 步循环 · 摇杆实时调制");
  const t2 = state.config.tools.step_sequencer;
  c2.appendChild(toggleRow("启用", t2.enabled, async v => api("tool_toggle", "step_sequencer", v)));
  const ctrl = el("div", "row wrap");
  const playBtn = el("button", "btn primary", "▶ 播放");
  playBtn.id = "seq-play-btn";
  playBtn.onclick = () => api("tool_action", "step_sequencer", "play", {});
  const stopBtn = el("button", "btn", "■ 停止");
  stopBtn.onclick = () => api("tool_action", "step_sequencer", "stop", {});
  ctrl.appendChild(playBtn);
  ctrl.appendChild(stopBtn);
  const editBtn = el("button", "btn" + (seqEdit.mode ? " primary" : ""), seqEdit.mode ? "✎ 编辑中（点击格子选择）" : "✎ 编辑音序");
  editBtn.onclick = () => {
    seqEdit.mode = !seqEdit.mode;
    if (!seqEdit.mode) seqEdit.sel = -1;
    renderSeq();
  };
  ctrl.appendChild(editBtn);
  ctrl.appendChild(field("BPM", numberInput(t2.bpm, 30, 300, debounce(v => savePatch({ tools: { step_sequencer: { bpm: v } } }), 200), 70)));
  ctrl.appendChild(field("步数", selectInput({ "8": "8", "16": "16", "32": "32" }, t2.steps, async v => savePatch({ tools: { step_sequencer: { steps: parseInt(v, 10) } } }))));
  ctrl.appendChild(field("调制", selectInput({ none: "关", note: "摇杆→音高", cc: "摇杆→CC" }, t2.modulate, async v => savePatch({ tools: { step_sequencer: { modulate: v } } }))));
  const swingS = sliderInput(Math.round(t2.swing * 100), 0, 60, 5, v => savePatch({ tools: { step_sequencer: { swing: v / 100 } } }));
  ctrl.appendChild(field("Swing %", swingS.holder));
  c2.appendChild(ctrl);
  const gridEl = el("div", "seq-grid");
  gridEl.id = "seq-grid";
  gridEl.dataset.steps = t2.steps;
  t2.on.forEach((on, i) => {
    const cell = el("div", "seq-cell" + (on ? " on" : "") +
      (seqEdit.mode && seqEdit.sel === i ? " selected" : ""));
    cell.id = "seq-cell-" + i;
    cell.innerHTML = "<b>" + noteName(t2.notes[i]) + "</b>" + (on ? "<br>" + t2.velocities[i] : "");
    cell.onclick = () => {
      if (seqEdit.mode) {
        seqEdit.sel = i;
        renderSeq();
      } else {
        api("tool_action", "step_sequencer", "toggle_step", { index: i });
      }
    };
    gridEl.appendChild(cell);
  });
  c2.appendChild(gridEl);
  grid.appendChild(c2);

  // 步编辑面板
  if (seqEdit.mode && seqEdit.sel >= 0) {
    const s = seqEdit.sel;
    const panel = card("步 " + (s + 1) + " 编辑", "音高 / 力度 / 门限（拖动松手保存）");
    const pRow = el("div", "row wrap");
    const noteInp = numberInput(t2.notes[s], 0, 127, debounce(v => savePatch({ tools: { step_sequencer: { notes: t2.notes.map((n, j) => j === s ? v : n) } } }), 250));
    pRow.appendChild(field("音高", noteInp));
    pRow.appendChild(el("span", "muted", noteName(t2.notes[s])));
    const velS = sliderInput(t2.velocities[s], 1, 127, 1, v => savePatch({ tools: { step_sequencer: { velocities: t2.velocities.map((n, j) => j === s ? v : n) } } }));
    pRow.appendChild(field("力度", velS.holder));
    const gateS = sliderInput(Math.round(t2.gates[s] * 100), 10, 100, 5, v => savePatch({ tools: { step_sequencer: { gates: t2.gates.map((n, j) => j === s ? v / 100 : n) } } }));
    pRow.appendChild(field("门限 %", gateS.holder));
    const upBtn = el("button", "btn small", "▲ 高八度");
    upBtn.onclick = () => savePatch({ tools: { step_sequencer: { notes: t2.notes.map((n, j) => j === s ? Math.min(127, n + 12) : n) } } });
    const dnBtn = el("button", "btn small", "▼ 低八度");
    dnBtn.onclick = () => savePatch({ tools: { step_sequencer: { notes: t2.notes.map((n, j) => j === s ? Math.max(0, n - 12) : n) } } });
    pRow.appendChild(upBtn);
    pRow.appendChild(dnBtn);
    // 每步 CC 输出
    const ccOpts = { none: "无 CC" };
    for (let c = 1; c <= 127; c++) ccOpts[c] = "CC " + c;
    const curCc = (t2.ccs && t2.ccs[s] != null) ? String(t2.ccs[s]) : "none";
    const ccSel = selectInput(ccOpts, curCc, async v => {
      const ccs = (t2.ccs || []).slice();
      ccs[s] = v === "none" ? null : parseInt(v, 10);
      await savePatch({ tools: { step_sequencer: { ccs: ccs } } });
    });
    pRow.appendChild(field("步 CC 输出", ccSel));
    panel.appendChild(pRow);
    grid.appendChild(panel);
  }

  $page.appendChild(grid);
}

/* ===== 调制页 ===== */
function renderMod() {
  $page.appendChild(pageHead("调制工具", "滚轮弯音"));
  const c = card("滚轮弯音", "按住热键 + 滚动鼠标滚轮 → Pitch Bend 或 CC 增量");
  const t = state.config.tools.wheel_bend;
  c.appendChild(toggleRow("启用", t.enabled, async v => api("tool_toggle", "wheel_bend", v)));
  const r = el("div", "row wrap");
  r.appendChild(field("热键（按住）", textInput(t.hotkey.join("+"), debounce(v => savePatch({ tools: { wheel_bend: { hotkey: v.split("+").map(s => s.trim()).filter(Boolean) } } }, "wheel_bend"), 250), 140)));
  r.appendChild(field("模式", selectInput({ pitch: "Pitch Bend (14bit)", cc: "CC 增量" }, t.mode, async v => savePatch({ tools: { wheel_bend: { mode: v } } }, "wheel_bend"))));
  if (t.mode === "cc") {
    r.appendChild(field("CC 号", numberInput(t.cc, 1, 127, debounce(v => savePatch({ tools: { wheel_bend: { cc: v } } }, "wheel_bend"), 200))));
    r.appendChild(field("每格步进", numberInput(t.step_size, 1, 24, debounce(v => savePatch({ tools: { wheel_bend: { step_size: v } } }, "wheel_bend"), 200))));
  } else {
    r.appendChild(field("每格步进 (341=半音)", numberInput(t.step_size, 1, 682, debounce(v => savePatch({ tools: { wheel_bend: { step_size: v } } }, "wheel_bend"), 200))));
  }
  c.appendChild(r);
  const cur = el("div", "ledbar");
  cur.id = "wheel-cur";
  cur.innerHTML = "<span class='dot'></span><span>当前值：0</span>";
  c.appendChild(cur);
  $page.appendChild(c);
}

/* ===== 映射层页 ===== */
function renderMapper() {
  $page.appendChild(pageHead("MIDI 映射层", "虚拟输入端口 → 规则链 → 输出（中间件路由）"));
  const c = card("映射规则", "从 DAW/其他设备发往虚拟端口的 MIDI 将按规则处理后转发到输出端口");
  const t = state.config.tools.midi_mapper;
  c.appendChild(toggleRow("启用", t.enabled, async v => api("tool_toggle", "midi_mapper", v)));
  const rules = t.rules;
  const list = el("div");
  list.id = "rule-list";
  rules.forEach((rule, i) => {
    const rowE = el("div", "rule-row");
    rowE.appendChild(selectInput(
      { channel: "通道转发", note_shift: "音高偏移", cc_scale: "CC 缩放", note_filter: "音符过滤" },
      rule.action, async v => savePatch({ tools: { midi_mapper: { rules: rules.map((q, j) => j === i ? Object.assign({}, q, { action: v }) : q) } } }, "midi_mapper")));
    if (rule.action === "channel") {
      rowE.appendChild(field("从", numberInput(rule.from, 1, 16, debounce(v => savePatch({ tools: { midi_mapper: { rules: rules.map((q, j) => j === i ? Object.assign({}, q, { from: v }) : q) } } }, "midi_mapper"), 200), 60)));
      rowE.appendChild(field("到", numberInput(rule.to, 1, 16, debounce(v => savePatch({ tools: { midi_mapper: { rules: rules.map((q, j) => j === i ? Object.assign({}, q, { to: v }) : q) } } }, "midi_mapper"), 200), 60)));
    } else if (rule.action === "note_shift") {
      rowE.appendChild(field("偏移", numberInput(rule.offset, -48, 48, debounce(v => savePatch({ tools: { midi_mapper: { rules: rules.map((q, j) => j === i ? Object.assign({}, q, { offset: v }) : q) } } }, "midi_mapper"), 200), 60)));
    } else if (rule.action === "cc_scale") {
      rowE.appendChild(field("CC", numberInput(rule.cc, 1, 127, debounce(v => savePatch({ tools: { midi_mapper: { rules: rules.map((q, j) => j === i ? Object.assign({}, q, { cc: v }) : q) } } }, "midi_mapper"), 200), 60)));
      rowE.appendChild(field("系数", numberInput(rule.factor, 0.1, 2, debounce(v => savePatch({ tools: { midi_mapper: { rules: rules.map((q, j) => j === i ? Object.assign({}, q, { factor: v }) : q) } } }, "midi_mapper"), 200), 60)));
      rowE.appendChild(field("偏移", numberInput(rule.offset, -127, 127, debounce(v => savePatch({ tools: { midi_mapper: { rules: rules.map((q, j) => j === i ? Object.assign({}, q, { offset: v }) : q) } } }, "midi_mapper"), 200), 60)));
    } else if (rule.action === "note_filter") {
      rowE.appendChild(field("最低", numberInput(rule.note_min, 0, 127, debounce(v => savePatch({ tools: { midi_mapper: { rules: rules.map((q, j) => j === i ? Object.assign({}, q, { note_min: v }) : q) } } }, "midi_mapper"), 200), 60)));
      rowE.appendChild(field("最高", numberInput(rule.note_max, 0, 127, debounce(v => savePatch({ tools: { midi_mapper: { rules: rules.map((q, j) => j === i ? Object.assign({}, q, { note_max: v }) : q) } } }, "midi_mapper"), 200), 60)));
      rowE.appendChild(field("通过", selectInput({ "true": "通过命中", "false": "过滤命中" }, String(rule.pass), async v => savePatch({ tools: { midi_mapper: { rules: rules.map((q, j) => j === i ? Object.assign({}, q, { pass: v === "true" }) : q) } } }, "midi_mapper"))));
    }
    const del = el("button", "btn small danger", "删除");
    del.onclick = async () => {
      const rs = rules.filter((_, j) => j !== i);
      await savePatch({ tools: { midi_mapper: { rules: rs } } }, "midi_mapper");
    };
    rowE.appendChild(del);
    list.appendChild(rowE);
  });
  c.appendChild(list);
  const addBtn = el("button", "btn", "+ 添加规则");
  addBtn.onclick = () => savePatch({ tools: { midi_mapper: { rules: rules.concat([{ action: "channel", from: 1, to: 2 }]) } } }, "midi_mapper");
  c.appendChild(addBtn);
  c.appendChild(el("div", "small-note", "已路由消息数：<span id='mapper-count'>0</span>"));
  $page.appendChild(c);
}

/* ===== Clip 可视化编辑器（模态） ===== */
function renderClipModal() {
  const oldOv = document.getElementById("clip-modal");
  if (oldOv) oldOv.remove();
  if (!clipEdit) return;
  const ov = el("div", "modal-overlay");
  ov.id = "clip-modal";
  ov.addEventListener("click", e => { if (e.target === ov) { clipEdit = null; ov.remove(); } });
  const m = el("div", "modal card");
  m.appendChild(el("h3", null, "编辑 Clip：<span class='muted'>" + esc(clipEdit.name) + "</span>"));

  const attr = el("div", "row wrap");
  const nameInp = textInput(clipEdit.name, v => { clipEdit.name = v; }, 140);
  attr.appendChild(field("名称", nameInp));
  const hkInp = textInput(clipEdit.hotkey, v => { clipEdit.hotkey = v; }, 150);
  hkInp.placeholder = "<ctrl>+<alt>+1";
  attr.appendChild(field("热键", hkInp));
  const loopRow = el("div", "row");
  loopRow.appendChild(el("span", null, "循环"));
  loopRow.appendChild(toggleInput(clipEdit.loop, v => { clipEdit.loop = v; }));
  attr.appendChild(loopRow);
  m.appendChild(attr);

  const tbl = el("table", "tbl");
  tbl.innerHTML = "<tr><th>类型</th><th>音符/CC</th><th>力度</th><th>t(ms)</th><th>时长(ms)</th><th></th></tr>";
  clipEdit.events.forEach((ev, i) => {
    const tr = el("tr");
    const typeSel = selectInput(
      { note_on: "音符开", note_off: "音符关", control_change: "CC" },
      ev.type, v => { ev.type = v; renderClipModal(); });
    tr.appendChild(tdWith(typeSel));
    const isNote = ev.type === "note_on" || ev.type === "note_off";
    const isCc = ev.type === "control_change";
    let valInp;
    if (isNote) {
      valInp = numberInput(ev.note, 0, 127, v => { ev.note = v; }, 70);
    } else if (isCc) {
      valInp = numberInput(ev.control, 1, 127, v => { ev.control = v; }, 70);
    } else {
      valInp = numberInput(0, 0, 127, () => {}, 70);
    }
    tr.appendChild(tdWith(valInp));
    let velInp = el("span", "muted", "—");
    if (ev.type === "note_on") {
      velInp = numberInput(ev.velocity, 1, 127, v => { ev.velocity = v; }, 60);
    }
    tr.appendChild(tdWith(velInp));
    const tInp = numberInput(ev.t, 0, 60000, v => { ev.t = v; }, 70);
    tr.appendChild(tdWith(tInp));
    const dInp = numberInput(ev.duration, 0, 60000, v => { ev.duration = v; }, 70);
    tr.appendChild(tdWith(dInp));
    const del = el("button", "btn small danger", "删");
    del.onclick = () => { clipEdit.events.splice(i, 1); renderClipModal(); };
    tr.appendChild(tdWith(del));
    tbl.appendChild(tr);
  });
  m.appendChild(tbl);

  const addBtn = el("button", "btn small", "+ 添加事件");
  addBtn.onclick = () => {
    clipEdit.events.push({ type: "note_on", note: 60, velocity: 100, t: 0, duration: 120 });
    renderClipModal();
  };
  m.appendChild(addBtn);

  const ops = el("div", "row");
  ops.style.marginTop = "14px";
  const saveBtn = el("button", "btn primary", "保存");
  saveBtn.onclick = async () => {
    const idx = clipEdit.index;
    const data = {
      name: clipEdit.name || "Clip",
      hotkey: clipEdit.hotkey,
      loop: clipEdit.loop,
      channel: clipEdit.channel,
      events: clipEdit.events
    };
    clipEdit = null;
    renderClipModal();
    const clips = state.config.tools.hotkey_clip.clips.slice();
    clips[idx] = data;
    await savePatch({ tools: { hotkey_clip: { clips: clips } } }, "hotkey_clip");
    renderSeq();
    toast("Clip 已保存：" + data.name);
  };
  const cancelBtn = el("button", "btn", "取消");
  cancelBtn.onclick = () => { clipEdit = null; renderClipModal(); };
  ops.appendChild(saveBtn);
  ops.appendChild(cancelBtn);
  m.appendChild(ops);
  ov.appendChild(m);
  document.body.appendChild(ov);
}

/* ===== 设置页 ===== */
function renderSettings() {
  $page.appendChild(pageHead("设置", "预设 Profile / MIDI 通道 / 日志"));
  const grid = el("div", "grid cols-2");

  const c1 = card("预设 Profile", "多套配置一键切换");
  const pRow = el("div", "row wrap");
  const profOpts = {};
  state.app.profiles.forEach(p => { profOpts[p] = p; });
  pRow.appendChild(field("当前预设", selectInput(profOpts, state.app.current_profile, async v => { await api("profile_load", v); refreshApp(); })));
  const newBtn = el("button", "btn", "新建");
  newBtn.onclick = async () => {
    const name = prompt("预设名称：");
    if (name) { await api("profile_new", name); refreshApp(); }
  };
  pRow.appendChild(newBtn);
  c1.appendChild(pRow);
  const plist = el("div", "row wrap");
  state.app.profiles.forEach(name => {
    const chip = el("span", "chip" + (name === state.app.current_profile ? " ok" : ""), esc(name));
    if (name !== state.app.current_profile) {
      chip.style.cursor = "pointer";
      chip.onclick = async () => { await api("profile_load", name); refreshApp(); };
    }
    plist.appendChild(chip);
  });
  c1.appendChild(plist);
  grid.appendChild(c1);

  const c2 = card("MIDI", "通道与输出");
  const midiCfg = state.config.midi;
  const mRow = el("div", "row wrap");
  mRow.appendChild(field("全局通道", numberInput(midiCfg.channel, 1, 16, debounce(v => savePatch({ midi: { channel: v } }), 200), 70)));
  const portOpts = {};
  (state.app.ports.outputs || []).forEach(p => { portOpts[p] = p; });
  const portSel = selectInput(portOpts, state.app.ports.selected_output || "", async v => api("midi_select_output", v));
  mRow.appendChild(field("系统输出端口（备选）", portSel));
  c2.appendChild(mRow);
  grid.appendChild(c2);

  const c3 = card("运行日志");
  const box = el("div", "log-box");
  box.id = "log-box";
  (state.app.log || []).forEach(l => box.appendChild(el("div", null, esc(l))));
  c3.appendChild(box);
  grid.appendChild(c3);

  const c4 = card("关于");
  c4.appendChild(el("div", "muted", "Gamepad MIDI Studio v" + state.app.version + " · Python + pywebview · teVirtualMIDI 虚拟端口内核"));
  grid.appendChild(c4);

  $page.appendChild(grid);
}

/* ===== 实时状态更新 ===== */
function afterConfig() {
  render();
  updateLeds();
}

async function refreshApp() {
  state.app = await api("get_app_state");
  state.config = await api("get_config");
  updateLeds();
  render();
}

function updateLeds() {
  const gp = state.app.gamepad || {};
  const ledGp = document.getElementById("led-gamepad");
  if (ledGp) ledGp.className = "led " + (gp.connected ? "on" : "off");
  const vp = state.app.ports || {};
  const ledV = document.getElementById("led-virtual");
  if (ledV) ledV.className = "led " + (vp.virtual_running ? "on" : vp.virtual_available ? "warn" : "off");
  const lbl = document.getElementById("profile-label");
  if (lbl) lbl.textContent = "预设：" + (state.app.current_profile || "");
  const vLbl = document.getElementById("version-label");
  if (vLbl) vLbl.textContent = "v" + (state.app.version || "");
}

/* 后端推送片段 */
window.__pushFragment = function (f) {
  if (f.log) {
    const box = document.getElementById("log-box");
    if (box) {
      const d = el("div", null, esc(f.log));
      box.appendChild(d);
      while (box.children.length > 200) box.removeChild(box.firstChild);
      box.scrollTop = box.scrollHeight;
    }
    return;
  }
  if (f.gamepad) {
    state.app = state.app || {};
    state.app.gamepad = Object.assign({}, state.app.gamepad || {}, f.gamepad);
    drawGamepadViz(f.gamepad);
    updateLeds();
    return;
  }
  if (f.virtual) {
    state.app = state.app || {};
    state.app.ports = Object.assign({}, state.app.ports || {}, f.virtual);
    updateLeds();
    return;
  }
  if (f.sequencer) {
    const gridEl = document.getElementById("seq-grid");
    if (gridEl) {
      gridEl.querySelectorAll(".seq-cell.playing").forEach(c => c.classList.remove("playing"));
      if (f.sequencer.step >= 0) {
        const cell = document.getElementById("seq-cell-" + f.sequencer.step);
        if (cell) cell.classList.add("playing");
      }
      const btn = document.getElementById("seq-play-btn");
      if (btn) btn.textContent = f.sequencer.playing ? "播放中…" : "▶ 播放";
    }
    return;
  }
  if (f.learn) {
    state.learn = f.learn;
    const banner = document.getElementById("learn-banner");
    if (banner) banner.classList.toggle("hidden", !f.learn.active);
    return;
  }
  if (f.midi_activity) {
    const led = document.getElementById("led-midi");
    if (led) {
      led.className = "led blink";
      setTimeout(() => {
        const l2 = document.getElementById("led-midi");
        if (l2) l2.className = "led";
      }, 120);
    }
    return;
  }
};

window.__pushState = async function (s) {
  state.app = s;
  state.config = await api("get_config");
  updateLeds();
  render();
};

/* 手柄可视化 */
function drawGamepadViz(gp) {
  if (!gp || !gp.axes) return;
  const draw = (cvId, xIdx, yIdx, valId) => {
    const cv = document.getElementById(cvId);
    if (!cv) return;
    const ctx = cv.getContext("2d");
    ctx.clearRect(0, 0, 96, 96);
    ctx.strokeStyle = "rgba(255,255,255,.15)";
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(48, 4); ctx.lineTo(48, 92); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(4, 48); ctx.lineTo(92, 48); ctx.stroke();
    const x = (gp.axes[xIdx] || 0) * 36;
    const y = (gp.axes[yIdx] || 0) * 36;
    ctx.beginPath(); ctx.arc(48 + x, 48 + y, 8, 0, Math.PI * 2);
    ctx.fillStyle = "#6ee7ff";
    ctx.shadowColor = "#6ee7ff";
    ctx.shadowBlur = 10;
    ctx.fill();
    ctx.shadowBlur = 0;
    if (valId) {
      const val = document.getElementById(valId);
      if (val) val.textContent = (Math.round(x * 10) / 10) + ", " + (Math.round(y * 10) / 10);
    }
  };
  draw("lsL-cv", 0, 1, "lsL-val");
  draw("lsR-cv", 2, 3, "lsR-val");
  (gp.buttons || []).forEach((pressed, i) => {
    const cell = document.getElementById("bcell-" + i);
    if (cell) cell.classList.toggle("pressed", pressed);
  });
}

/* XY Pad 交互 */
function initXYPad() {
  const pad = document.getElementById("xy-pad");
  if (!pad) return;
  const marker = document.getElementById("xy-marker");
  const set = async (clientX, clientY) => {
    const r = pad.getBoundingClientRect();
    const x = Math.max(0, Math.min(1, (clientX - r.left) / r.width));
    const y = Math.max(0, Math.min(1, (clientY - r.top) / r.height));
    marker.style.left = (x * 100) + "%";
    marker.style.top = (y * 100) + "%";
    await api("tool_action", "screen_xy_pad", "set_xy", {
      x: Math.round(x * 127),
      y: Math.round(y * 127)
    });
  };
  pad.addEventListener("pointerdown", e => { pad.setPointerCapture(e.pointerId); set(e.clientX, e.clientY); });
  pad.addEventListener("pointermove", e => { if (e.buttons & 1) set(e.clientX, e.clientY); });
}

/* 工具状态轮询 */
function pollToolStates() {
  setInterval(async () => {
    if (!state.app) return;
    try {
      const st = await api("tool_state");
      const act = document.getElementById("mousexy-active");
      if (act) {
        act.textContent = (st.mouse_xy && st.mouse_xy.active) ? "激活中" : "未激活";
        act.className = "badge" + ((st.mouse_xy && st.mouse_xy.active) ? " ok" : "");
      }
      const wc = document.getElementById("wheel-cur");
      if (wc && st.wheel_bend) {
        wc.innerHTML = "<span class='dot'></span><span>当前值：" + st.wheel_bend.pitch + "</span>";
        wc.classList.toggle("on", st.wheel_bend.pitch !== 0);
      }
      const mc = document.getElementById("mapper-count");
      if (mc && st.midi_mapper) mc.textContent = st.midi_mapper.routed;
      document.querySelectorAll(".clip-item.playing").forEach(c => c.classList.remove("playing"));
      if (st.hotkey_clip && st.hotkey_clip.playing) {
        st.hotkey_clip.playing.forEach(name => {
          document.querySelectorAll(".clip-item").forEach(item => {
            const n = item.querySelector(".name");
            if (n && n.textContent === name) item.classList.add("playing");
          });
        });
      }
      const recBtn = document.getElementById("clip-rec-btn");
      if (recBtn && st.hotkey_clip) {
        recBtn.textContent = st.hotkey_clip.recording ? "■ 停止录制" : "● 开始录制表演";
        recBtn.classList.toggle("danger", !!st.hotkey_clip.recording);
      }
    } catch (e) { /* 忽略 */ }
  }, 300);
}

/* ---------- 启动 ---------- */
function whenReady() {
  return new Promise(resolve => {
    if (window.pywebview && window.pywebview.api) return resolve();
    window.addEventListener("pywebviewready", () => resolve(), { once: true });
    setTimeout(() => {
      if (window.pywebview && window.pywebview.api) resolve();
    }, 3000);
  });
}

async function boot() {
  await whenReady();
  document.querySelectorAll(".nav-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      state.page = btn.dataset.page;
      document.querySelectorAll(".nav-btn").forEach(b => b.classList.toggle("active", b === btn));
      render();
    });
  });

  // 录制按钮二次点击 = 停止录制
  document.addEventListener("click", async (e) => {
    const btn = document.getElementById("clip-rec-btn");
    if (btn && e.target === btn && btn.textContent.includes("停止")) {
      await api("tool_action", "hotkey_clip", "record_stop", {});
      await refreshApp();
    }
  });

  state.app = await api("get_app_state");
  state.config = await api("get_config");
  updateLeds();
  render();
  initXYPad();
  pollToolStates();
}

boot();
