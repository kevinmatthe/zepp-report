const iso = (date) => date.toISOString().slice(0, 10);
const add = (day, n) => {
  const d = /* @__PURE__ */ new Date(day + "T12:00:00Z");
  d.setUTCDate(d.getUTCDate() + n);
  return iso(d);
};
function shiftRange(from, to, direction) {
  if (from.endsWith("-01-01") && to === from.slice(0, 4) + "-12-31") {
    const year = Number(from.slice(0, 4)) + direction;
    return [year + "-01-01", year + "-12-31"];
  }
  const next = /* @__PURE__ */ new Date(from.slice(0, 7) + "-01T12:00:00Z");
  next.setUTCMonth(next.getUTCMonth() + 1);
  if (from.endsWith("-01") && to === add(iso(next), -1)) {
    const start = /* @__PURE__ */ new Date(from + "T12:00:00Z");
    start.setUTCMonth(start.getUTCMonth() + direction);
    const end = new Date(start);
    end.setUTCMonth(end.getUTCMonth() + 1);
    return [iso(start), add(iso(end), -1)];
  }
  const length = Math.round((Date.parse(to) - Date.parse(from)) / 864e5) + 1;
  return [add(from, length * direction), add(to, length * direction)];
}
const clampDay = (day, from, to) => day < from ? from : day > to ? to : day;
function createDayCache(fetchDay, limit = 12) {
  const values = /* @__PURE__ */ new Map(), pending = /* @__PURE__ */ new Map();
  let generation = 0;
  return {
    get(day) {
      if (values.has(day)) return Promise.resolve(values.get(day));
      if (pending.has(day)) return pending.get(day);
      const current = generation;
      const promise = fetchDay(day).then((value) => {
        if (current === generation) {
          values.set(day, value);
          if (values.size > limit) values.delete(values.keys().next().value);
        }
        return value;
      }).finally(() => {
        if (current === generation && pending.get(day) === promise) pending.delete(day);
      });
      pending.set(day, promise);
      return promise;
    },
    clear() {
      generation++;
      values.clear();
      pending.clear();
    }
  };
}
export {
  clampDay,
  createDayCache,
  shiftRange
};
