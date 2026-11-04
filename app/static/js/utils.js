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

  // Безопасный мини-markdown: экранируем всё, затем **bold**, *italic*.
  function renderInlineMarkdown(text) {
    return escHtml(text)
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[^*])\*([^*\n]+?)\*(?!\*)/g, "$1<em>$2</em>")
      .replace(/\n/g, "<br>");
  }

  // Блочный вариант: абзацы + маркированные/нумерованные списки.
  function renderMarkdown(text) {
    const lines = String(text ?? "").split(/\r?\n/);
    const out = [];
    let list = null;
    for (const line of lines) {
      const t = line.trim();
      const ul = t.match(/^[-*]\s+(.*)$/);
      const ol = t.match(/^\d+[.)]\s+(.*)$/);
      if (ul || ol) {
        const want = ul ? "ul" : "ol";
        if (list !== want) {
          if (list) out.push(`</${list}>`);
          out.push(`<${want}>`);
          list = want;
        }
        out.push(`<li>${renderInlineMarkdown((ul || ol)[1])}</li>`);
      } else {
        if (list) { out.push(`</${list}>`); list = null; }
        if (t) out.push(`<p>${renderInlineMarkdown(t)}</p>`);
      }
    }
    if (list) out.push(`</${list}>`);
    return out.join("");
  }

  function mediaUrl(url) {
    if (!url) return "";
    const raw = String(url).trim();
    if (!raw) return "";
    if (/^(https?:)?\/\//i.test(raw) || raw.startsWith("data:") || raw.startsWith("blob:")) {
      return raw;
    }
    if (raw.startsWith("/") && RM.api && RM.api.api) {
      return RM.api.api(raw);
    }
    return raw;
  }

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
    mediaUrl, scaleAmount, renderMarkdown, renderInlineMarkdown,
  };
})();

// Удобные сокращения на верхнем уровне
const $ = RM.utils.$;