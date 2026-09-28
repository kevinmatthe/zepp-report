import { api, action } from "./api.js";
import { $, state, addDays, today, escape, number, notice, persist } from "./state.js";
let view = "year", anchor = "", selected = [], days = [], sequence = 0, taskOffset = 0, taskSequence = 0, previewMode = "sync";
const labels = { done: "已完成", partial: "部分完成", running: "执行中", pending: "等待中", failed: "失败", unrequested: "未检查", future: "未来日期", empty: "已检查暂无数据" };
const kinds = { band: "心率 / 睡眠 / 活动", stress: "压力", training: "训练", trimp: "TRIMP", sport: "运动负荷", vo2: "VO₂ Max", workouts: "完整运动", spo2:"血氧" };
function bounds() {
  anchor = anchor || state.to;
  let a = anchor, b = anchor;
  if (view === "year") {
    a = anchor.slice(0, 4) + "-01-01";
    b = anchor.slice(0, 4) + "-12-31";
  }
  if (view === "month") {
    a = anchor.slice(0, 7) + "-01";
    const d = /* @__PURE__ */ new Date(a + "T12:00:00Z");
    d.setUTCMonth(d.getUTCMonth() + 1);
    b = addDays(d.toISOString().slice(0, 10), -1);
  }
  if (view === "week") {
    const n = ((/* @__PURE__ */ new Date(anchor + "T12:00:00Z")).getUTCDay() + 6) % 7;
    a = addDays(anchor, -n);
    b = addDays(a, 6);
  }
  return [a, b];
}
function selectedRange() {
  const [a, b] = selected.length ? selected : bounds();
  return [a, b > today(state.timezone) ? today(state.timezone) : b];
}
async function loadTasks() {
  if (!$("task-records").open) return;
  const seq = ++taskSequence, [from, to] = selectedRange();
  if (from > to) {
    $("task-rows").innerHTML = '<tr><td colspan="6">未来日期暂无任务</td></tr>';
    return;
  }
  const p = new URLSearchParams({ from_date: from, to_date: to, offset: taskOffset, limit: 20 });
  if ($("coverage-kind").value) p.set("kind", $("coverage-kind").value);
  if ($("task-status").value) p.set("status", $("task-status").value);
  const data = await api("/api/tasks?" + p);
  if (seq !== taskSequence || !state.active) return;
  const time = (t) => t ? new Intl.DateTimeFormat("zh-CN", { timeZone: state.timezone, month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(t * 1e3)) : "—";
  $("task-rows").innerHTML = (data.tasks || []).map((t) => `<tr><td>${escape(t.day)}</td><td>${escape(kinds[t.kind] || t.kind)}</td><td>${escape(labels[t.status] || t.status)}</td><td>${number(t.attempts)}</td><td>${escape(time(t.updated_at))}</td><td>${escape(t.error || "—")}</td></tr>`).join("") || '<tr><td colspan="6">所选条件暂无任务</td></tr>';
  $("task-page").textContent = `${from} — ${to} · ${data.total || 0} 项 · 第 ${Math.floor(taskOffset / 20) + 1} 页`;
  $("task-prev").disabled = taskOffset === 0;
  $("task-next").disabled = taskOffset + 20 >= (data.total || 0);
}
function details(d) {
  $("coverage-detail").innerHTML = `<h3>${escape(d.date)} · ${escape(labels[d.status] || d.status)}</h3><p>已检查 ${d.counts?.done || 0} / ${d.expected || 0} 项 · 已归档 ${d.archived || 0} 项 · 有测量 ${d.observed || 0} 项</p><p class="muted small">VM 待投递 ${d.pending_exports || 0}（投递不等于已读回核对） · 修订冲突 ${d.conflicts || 0}${d.archived && d.counts?.pending ? " · 已归档，等待刷新" : ""}</p><div class="task-list">${(d.tasks || []).map((t) => `<div><span>${escape(kinds[t.kind] || t.kind)}</span><span>${escape(labels[t.status] || t.status)}${t.archived ? " · 已归档" : ""}${t.status === "done" && !t.has_data ? " · 暂无数据" : ""}</span>${t.error ? `<p class="error">${escape(t.error)}</p>` : ""}</div>`).join("")}</div><p class="small">已选范围：${escape(selected[0] || d.date)} — ${escape(selected[1] || d.date)}</p>`;
}
async function loadCoverage() {
  const seq = ++sequence, [a, b] = bounds(), p = new URLSearchParams({ from_date: a, to_date: b });
  if ($("coverage-kind").value) p.set("kind", $("coverage-kind").value);
  const data = await api("/api/coverage?" + p);
  if (seq !== sequence || !state.active) return;
  days = data.days || [];
  const totals = data.totals || days.filter((d) => d.date <= (data.today || today(state.timezone))).reduce((out, d) => {
    for (const [k, v] of Object.entries(d.counts || {})) out[k] = (out[k] || 0) + v;
    return out;
  }, {});
  const expected = Object.values(totals).reduce((a2, b2) => a2 + b2, 0), done = totals.done || 0;
  $("coverage-totals").innerHTML = `<div><strong>${number(expected ? done / expected * 100 : 0, 1)}%</strong> 已检查 ${number(done)} / ${number(expected)} 项</div><progress value="${done}" max="${expected || 1}" aria-label="当前日历任务完成率"></progress><p class="small muted">${Object.entries(totals).map(([k, v]) => `${labels[k] || k} ${number(v)}`).join(" · ")} · 未来日期不计入分母</p>`;
  const map = new Map(days.map((d) => [d.date, d])), items = [];
  for (let d = a; d <= b; d = addDays(d, 1)) items.push(map.get(d) || { date: d, status: d > (data.today || today(state.timezone)) ? "future" : "unrequested", counts: {}, tasks: [] });
  $("calendar-title").textContent = view === "year" ? a.slice(0, 4) + " 年" : view === "month" ? a.slice(0, 7) : a + " — " + b;
  const focus = document.activeElement?.dataset?.date;
  $("coverage-grid").className = "coverage-grid " + view;
  const cells = items.map((d) => {
    const future = d.date > (data.today || today(state.timezone)), running = !data.auth_required && (d.counts?.running > 0 || d.status === "running"), failed = d.counts?.failed > 0 || d.status === "failed";
    return `<button data-date="${d.date}" class="day-cell ${escape(d.status)} ${d.archived ? "archived" : ""} ${running ? "is-running" : ""} ${failed ? "has-failure" : ""} ${selected.length && d.date >= selected[0] && d.date <= (selected[1] || selected[0]) ? "selected" : ""}" ${future ? "disabled" : ""} aria-label="${d.date} ${escape(labels[d.status] || d.status)}，${d.counts?.done || 0}/${d.expected || 0} 项完成" title="${d.date} · ${escape(labels[d.status] || d.status)}"><span>${view === "year" ? d.date.endsWith("-01") ? Number(d.date.slice(5, 7)) + "月" : "" : d.date.slice(8)}</span>${view === "month" ? `<small>${d.counts?.done || 0}/${d.expected || 0}</small>` : ""}${d.empty ? "○" : ""}${failed ? "<b>!</b>" : ""}</button>`;
  }).join("");
  const weekday = ((/* @__PURE__ */ new Date(a + "T12:00:00Z")).getUTCDay() + 6) % 7;
  const weekdays = ["一", "二", "三", "四", "五", "六", "日"];
  $("coverage-weekdays").hidden = view !== "year";
  $("coverage-weekdays").innerHTML = weekdays.map((w) => "<span>" + w + "</span>").join("");
  $("coverage-grid").innerHTML = (view === "month" ? weekdays.map((w) => '<span class="weekday">周' + w + "</span>").join("") : "") + (["year", "month"].includes(view) ? '<span aria-hidden="true"></span>'.repeat(weekday) : "") + cells;
  if (view === "week") {
    const activeKinds = $("coverage-kind").value ? [$("coverage-kind").value] : Object.keys(kinds);
    $("coverage-grid").innerHTML = '<span class="weekday">采集接口</span>' + items.map((d) => '<span class="weekday">' + d.date.slice(5) + "</span>").join("") + activeKinds.map((kind) => '<span class="week-kind">' + kinds[kind] + "</span>" + items.map((d) => {
      const task = d.tasks?.find((t) => t.kind === kind), status = task?.status || "unrequested", future = d.date > (data.today || today(state.timezone));
      return `<button data-date="${d.date}" class="day-cell ${status} ${status === "running" && !data.auth_required ? "is-running" : ""}" ${future ? "disabled" : ""} aria-label="${d.date} ${kinds[kind]} ${labels[status]}">${status === "done" ? "✓" : status === "failed" ? "!" : status === "running" ? "↻" : status === "pending" ? "·" : "—"}</button>`;
    }).join("")).join("");
  }
  if (view === "day" && items[0]) {
    selected = [items[0].date, items[0].date];
    details(items[0]);
  }
  document.querySelectorAll("#coverage-grid button").forEach((b2) => b2.onclick = (e) => {
    const d = items.find((x) => x.date === b2.dataset.date);
    anchor = d.date;
    if (e.shiftKey && selected.length) selected = [selected[0], d.date].sort();
    else selected = [d.date, d.date];
    document.querySelectorAll("#coverage-grid button").forEach((c) => c.classList.toggle("selected", c.dataset.date >= selected[0] && c.dataset.date <= selected[1]));
    details(d);
    taskOffset = 0;
    action(null, loadTasks);
    if (!d.tasks?.length) {
      const q = new URLSearchParams({ from_date: d.date, to_date: d.date });
      if ($("coverage-kind").value) q.set("kind", $("coverage-kind").value);
      api("/api/coverage?" + q).then((r) => {
        if (selected.includes(d.date) && r.days?.[0]) details(r.days[0]);
      }).catch((e2) => notice(e2.message, true));
    }
  });
  if (selected.length && view !== "day") {
    const current = items.find((d) => d.date === anchor);
    if (current?.tasks?.length) details(current);
    else if (current) {
      const q = new URLSearchParams({ from_date: anchor, to_date: anchor });
      if ($("coverage-kind").value) q.set("kind", $("coverage-kind").value);
      const detail = await api("/api/coverage?" + q);
      if (seq === sequence && detail.days?.[0]) details(detail.days[0]);
    }
  }
  await loadTasks();
  if (focus) document.querySelector(`#coverage-grid [data-date="${focus}"]`)?.focus({ preventScroll: true });
  document.querySelectorAll("[data-view]").forEach((b2) => b2.setAttribute("aria-pressed", String(b2.dataset.view === view)));
}
function setupCoverage() {
  $("task-records").ontoggle = () => action(null, loadTasks);
  $("task-status").onchange = () => {
    taskOffset = 0;
    action(null, loadTasks);
  };
  $("task-prev").onclick = () => {
    taskOffset = Math.max(0, taskOffset - 20);
    action(null, loadTasks);
  };
  $("task-next").onclick = () => {
    taskOffset += 20;
    action(null, loadTasks);
  };
  $("selection-trends").onclick = () => {
    if (!selected.length) {
      notice("先选择日期或用 Shift + 点击选择范围");
      return;
    }
    Object.assign(state, { from: selected[0], to: selected[1], day: selected[1], nav: "trends" });
    persist();
    window.dispatchEvent(new Event("selection-trends"));
  };
  document.querySelectorAll("[data-view]").forEach((b) => b.onclick = () => {
    view = b.dataset.view;
    action(b, loadCoverage);
  });
  $("coverage-kind").onchange = () => action(null, loadCoverage);
  for (const [id, n] of [["calendar-prev", -1], ["calendar-next", 1]]) $(id).onclick = () => {
    anchor = anchor || state.to;
    if (view === "year") anchor = +anchor.slice(0, 4) + n + "-01-01";
    else if (view === "month") {
      const d = /* @__PURE__ */ new Date(anchor.slice(0, 7) + "-01T12:00:00Z");
      d.setUTCMonth(d.getUTCMonth() + n);
      anchor = d.toISOString().slice(0, 10);
    } else anchor = addDays(anchor, n * (view === "week" ? 7 : 1));
    action($(id), loadCoverage);
  };
  const openPreview = (mode) => {
    previewMode = mode;
    const f = $("backfill-form");
    const [a, b] = selectedRange();
    f.elements.from_date.value = a;
    f.elements.to_date.value = b;
    f.elements.force.disabled = mode === "retry";
    $("confirm-sync").textContent = mode === "retry" ? "确认重试失败任务" : "确认加入队列";
    f.elements.force.checked = false;
    $("backfill-preview").textContent = "";
    $("confirm-sync").disabled = true;
    $("backfill-dialog").showModal();
  };
  $("backfill-open").onclick = () => openPreview("sync");
  $("retry-failed").onclick = () => openPreview("retry");
  const payload = () => {
    const f = $("backfill-form"), p = { from_date: f.elements.from_date.value, to_date: f.elements.to_date.value, force: f.elements.force.checked };
    if (!p.from_date || !p.to_date || p.from_date > p.to_date || p.to_date > today(state.timezone)) throw Error("请选择有效日期范围，不能包含未来日期。");
    if ($("coverage-kind").value) p.kinds = [$("coverage-kind").value];
    return p;
  };
  let approved = null;
  $("backfill-form").oninput = () => {
    approved = null;
    $("confirm-sync").disabled = true;
  };
  $("preview-sync").onclick = (e) => action(e.currentTarget, async () => {
    const p = payload(), result = await api("/api/sync/preview", "POST", p);
    approved = JSON.stringify(p);
    $("backfill-preview").textContent = `${p.from_date} — ${p.to_date}：将执行 ${previewMode === "retry" ? result.failed || 0 : result.queued ?? result.unrequested ?? 0} 项；已完成 ${result.done || 0}，等待 ${result.pending || 0}，运行 ${result.running || 0}，失败 ${result.failed || 0}。`;
    $("confirm-sync").disabled = false;
  });
  $("backfill-form").onsubmit = (e) => {
    e.preventDefault();
    action(e.submitter, async () => {
      const p = payload();
      if (JSON.stringify(p) !== approved) throw Error("日期已变更，请重新预览。");
      const r = await api(previewMode === "retry" ? "/api/retry" : "/api/sync", "POST", previewMode === "retry" ? Object.fromEntries(Object.entries(p).filter(([k]) => k !== "force")) : p);
      $("backfill-dialog").close();
      notice(`已加入持久队列：${r.queued || 0} 项`);
      await loadCoverage();
    });
  };
}
export {
  loadCoverage,
  setupCoverage
};
