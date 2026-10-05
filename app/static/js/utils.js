/* Утилиты — доступны глобально как window.RM.utils */
"use strict";

const RM = window.RM = window.RM || {};

RM.utils = (function () {
  const $ = (id) => document.getElementById(id);

  function escHtml(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function setStatus(el, text, kind = "info") {
    el.textContent = text;
    el.className = "status show " + kind;
  }
  function clearStatus(el) {
    el.className = "status";
    el.textContent = "";
  }

  function formatTime(mins) {
    if (!mins || isNaN(mins)) return "";
    if (mins < 60) return mins + " мин";
    const h = Math.floor(mins / 60);
    const m = mins % 60;
    return m ? `${h} ч ${m} мин` : `${h} ч`;
  }

  function toISO(d) {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}`;
  }
  function getMonday(d) {
    const x = new Date(d);
    const day = x.getDay();
    const diff = day === 0 ? -6 : 1 - day;
    x.setDate(x.getDate() + diff);
    x.setHours(0, 0, 0, 0);
    return x;
  }
  function addDays(date, n) {
    const d = new Date(date);
    d.setDate(d.getDate() + n);
    return d;
  }
  const MONTHS_SHORT = ["янв","фев","мар","апр","мая","июн","июл","авг","сен","окт","ноя","дек"];
  const WEEKDAYS_SHORT = ["Пн","Вт","Ср","Чт","Пт","Сб","Вс"];

  function weekTitle(monday) {
    const sunday = addDays(monday, 6);
    const m1 = MONTHS_SHORT[monday.getMonth()];
    const m2 = MONTHS_SHORT[sunday.getMonth()];
    const y1 = monday.getFullYear();
    const y2 = sunday.getFullYear();
    if (y1 !== y2) return `${monday.getDate()} ${m1} ${y1} — ${sunday.getDate()} ${m2} ${y2}`;
    if (m1 !== m2) return `${monday.getDate()} ${m1} — ${sunday.getDate()} ${m2} ${y1}`;
    return `${monday.getDate()}–${sunday.getDate()} ${m1} ${y1}`;
  }
  function isToday(iso) { return iso === toISO(new Date()); }

  function scaleAmount(amount, mult) {
    if (!amount || mult === 1) return amount ?? "";
    const m = String(amount).match(/^(\d+(?:[.,]\d+)?)(.*)$/);
    if (!m) return amount;
    const num = parseFloat(m[1].replace(",", ".")) * mult;
    if (isNaN(num)) return amount;
    const formatted = Number.isInteger(num)
      ? String(num)
      : num.toFixed(2).replace(/\.?0+$/, "");
    return formatted + (m[2] || "");
  }

  return {
    $, escHtml, setStatus, clearStatus, formatTime,
    toISO, getMonday, addDays, weekTitle, isToday,
    MONTHS_SHORT, WEEKDAYS_SHORT,
    scaleAmount,
  };
})();

// Удобные сокращения на верхнем уровне
const $ = RM.utils.$;