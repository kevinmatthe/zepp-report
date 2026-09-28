const $ = (id) => document.getElementById(id);
const escape = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const number = (v, d = 0) => v == null || !Number.isFinite(Number(v)) ? "—" : Number(v).toLocaleString("zh-CN", { maximumFractionDigits: d });
const addDays = (s, n) => {
  const d = /* @__PURE__ */ new Date(s + "T12:00:00Z");
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
};
const today = (timezone = "Asia/Shanghai") => new Intl.DateTimeFormat("sv-SE", { timeZone: timezone }).format(/* @__PURE__ */ new Date());
const state = { timezone: "Asia/Shanghai", from: "", to: "", nav: "trends", compare: "previous", grain: "day", day: "", active: false };
function restore() {
  const p = new URLSearchParams(location.search), t = addDays(today(state.timezone), -1);
  state.from = /^\d{4}-\d{2}-\d{2}$/.test(p.get("from")) ? p.get("from") : addDays(t, -29);
  state.to = /^\d{4}-\d{2}-\d{2}$/.test(p.get("to")) ? p.get("to") : t;
  if (!validDate(state.from) || !validDate(state.to) || state.from > state.to || state.to > today(state.timezone) || Date.parse(state.to) - Date.parse(state.from) > 365 * 864e5) {
    state.from = addDays(t, -29);
    state.to = t;
  }
  state.nav = p.get("view") === "sync" ? "sync" : "trends";
  state.compare = ["none", "previous", "year"].includes(p.get("compare")) ? p.get("compare") : "previous";
  state.day = validDate(p.get("day")) && p.get("day") >= state.from && p.get("day") <= state.to ? p.get("day") : state.to;
  state.grain = ["day", "week", "month"].includes(p.get("grain")) ? p.get("grain") : "day";
}
function persist() {
  const p = new URLSearchParams({ from: state.from, to: state.to, view: state.nav, compare: state.compare, day: state.day, grain: state.grain });
  history.pushState({}, "", `?${p}`);
}
const query = () => new URLSearchParams({ from_date: state.from, to_date: state.to });
function notice(message, bad = false) {
  $("notice").textContent = message;
  $("notice").hidden = false;
  $("notice").classList.toggle("bad", bad);
  clearTimeout(notice.timer);
  notice.timer = setTimeout(() => $("notice").hidden = true, 6e3);
}
const validDate = (s) => /^\d{4}-\d{2}-\d{2}$/.test(s) && Number.isFinite(Date.parse(s)) && (/* @__PURE__ */ new Date(s + "T12:00:00Z")).toISOString().slice(0, 10) === s;
export {
  $,
  addDays,
  escape,
  notice,
  number,
  persist,
  query,
  restore,
  state,
  today,
  validDate
};
