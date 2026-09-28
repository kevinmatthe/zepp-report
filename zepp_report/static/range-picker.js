import flatpickr from "flatpickr";
import { Mandarin } from "flatpickr/dist/l10n/zh.js";
import "flatpickr/dist/flatpickr.css";
import { $, state, today, addDays, persist, validDate } from "./state.js";
import { shiftRange } from "./frontend-utils.js";
function rangePicker(change) {
  let draft = [], preset = null;
  const picker = flatpickr($("range-calendar"), { mode: "range", inline: true, locale: Mandarin, dateFormat: "Y-m-d", ariaDateFormat: "Y年m月d日", disableMobile: true, showMonths: innerWidth >= 768 ? 2 : 1, maxDate: today(state.timezone), onChange: (dates) => {
    preset = null;
    document.querySelectorAll("[data-preset]").forEach(b=>b.setAttribute("aria-pressed","false"));
    draft = dates.map((d) => flatpickr.formatDate(d, "Y-m-d"));
    sync();
  } });
  const sync = () => {
    $("range-from").value = draft[0] || "";
    $("range-to").value = draft[1] || draft[0] || "";
  };
  const set = (a, b) => {
    draft = [a, b];
    picker.setDate(draft);
    sync();
  };
  $("range-open").onclick = () => {
    preset=null;document.querySelectorAll("[data-preset]").forEach(b=>b.setAttribute("aria-pressed","false"));
    picker.set("maxDate", today(state.timezone));
    picker.set("showMonths", innerWidth >= 768 ? 2 : 1);
    $("include-today").checked = state.to === today(state.timezone);
    set(state.from, state.to);
    $("jump-year").value = state.to.slice(0, 4);
    $("jump-month").value = +state.to.slice(5, 7) - 1;
    $("range-error").textContent = "";
    $("range-dialog").showModal();
  };
  $("range-cancel").onclick = () => $("range-dialog").close();
  const selectPreset = (p) => {
    preset = p;
    document.querySelectorAll("[data-preset]").forEach(b=>b.setAttribute("aria-pressed",String(b.dataset.preset===p)));
    const actual = today(state.timezone), t = $("include-today").checked ? actual : addDays(actual, -1), y = +actual.slice(0, 4), m = actual.slice(0, 7);
    let a = t, z = t;
    if (/^\d+$/.test(p)) a = addDays(t, 1 - Number(p));
    if (p === "week" || p === "lastweek") {
      const weekday = ((/* @__PURE__ */ new Date(actual + "T12:00:00Z")).getUTCDay() + 6) % 7;
      a = addDays(actual, -weekday);
      if (p === "lastweek") {
        z = addDays(a, -1);
        a = addDays(a, -7);
      } else if (a > z) a = z;
    }
    if (p === "month") a = m + "-01";
    if (p === "year") a = y + "-01-01";
    if (p === "lastmonth") {
      z = addDays(m + "-01", -1);
      a = z.slice(0, 7) + "-01";
    }
    if (p === "lastyear") {
      a = y - 1 + "-01-01";
      z = y - 1 + "-12-31";
    }
    if (a > z) a = z;
    set(a, z);
  };
  document.querySelectorAll("[data-preset]").forEach((b) => b.onclick = () => selectPreset(b.dataset.preset));
  $("include-today").onchange = () => {
    if (preset) selectPreset(preset);
    else set(draft[0], $("include-today").checked ? today(state.timezone) : addDays(today(state.timezone), -1));
  };
  $("jump-calendar").onclick = () => {
    const year = +$("jump-year").value, month = +$("jump-month").value;
    if (year >= 1970 && year <= 2100) picker.jumpToDate(new Date(year, month, 1));
  };
  $("range-apply").onclick = () => {
    const a = $("range-from").value, b = $("range-to").value;
    if (!validDate(a) || !validDate(b) || a > b || b > today(state.timezone) || Date.parse(b) - Date.parse(a) > 365 * 864e5) {
      $("range-error").textContent = "请选择真实日期，范围不超过 366 天，且不晚于今天。";
      return;
    }
    Object.assign(state, { from: a, to: b, day: b });
    persist();
    $("range-dialog").close();
    change();
  };
  for (const [id, n] of [["range-prev", -1], ["range-next", 1]]) $(id).onclick = () => {
    const [a, b] = shiftRange(state.from, state.to, n);
    if (b > today(state.timezone)) return;
    Object.assign(state, { from: a, to: b, day: b });
    persist();
    change();
  };
}
export {
  rangePicker
};
