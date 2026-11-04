"use strict";
(function (RM) {
  const canvas = document.getElementById("snow-canvas");
  if (!canvas) {
    RM.snow = { setup() {}, setEffect() {}, setActive() {} };
    return;
  }
  const ctx = canvas.getContext("2d");
  if (!ctx) {
    RM.snow = { setup() {}, setEffect() {}, setActive() {} };
    return;
  }

  const reduceQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
  const darkQuery = window.matchMedia("(prefers-color-scheme: dark)");

  let setupDone = false;
  let enabled = false;
  let active = false;
  let running = false;
  let raf = null;
  let last = 0;
  let width = 0;
  let height = 0;
  let dpr = 1;
  let particles = [];
  let reducedMotion = reduceQuery.matches;
  let dark = darkQuery.matches;

  function rand(min, max) {
    return min + Math.random() * (max - min);
  }

  function effectFromUser() {
    const value = (RM.state && RM.state.user && RM.state.user.visual_effect) || "none";
    return value === "snow" ? "snow" : "none";
  }

  function makeParticle() {
    const big = Math.random() < 0.22;
    return {
      x: rand(0, width || window.innerWidth),
      y: rand(-window.innerHeight, window.innerHeight),
      r: big ? rand(3.4, 5.2) : rand(2.0, 3.3),
      vy: rand(18, 58),
      vx: rand(-9, 9),
      phase: rand(0, Math.PI * 2),
      sway: rand(0.35, 1.15),
      swayAmp: rand(4, 15),
      rot: rand(0, Math.PI * 2),
      spin: rand(-0.55, 0.55),
      alpha: rand(0.35, 0.85),
    };
  }

  function resize() {
    const w = window.innerWidth;
    const h = window.innerHeight;
    if (!w || !h) return;
    width = w;
    height = h;
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.floor(w * dpr);
    canvas.height = Math.floor(h * dpr);
    canvas.style.width = w + "px";
    canvas.style.height = h + "px";
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const target = Math.min(140, Math.max(28, Math.round((w * h) / 14000)));
    if (particles.length !== target) {
      particles = Array.from({ length: target }, makeParticle);
    }
  }

  function drawParticle(p) {
    const rgb = dark ? "255,255,255" : "96,152,232";
    const large = p.r >= 3.35;
    ctx.strokeStyle = `rgba(${rgb},${p.alpha})`;
    ctx.lineWidth = large ? Math.max(0.8, p.r * 0.18) : 0.75;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    const arm = large ? 1.25 : 1.45;

    for (let i = 0; i < 6; i += 1) {
      const angle = p.rot + (i * Math.PI) / 3;
      const dx = Math.cos(angle);
      const dy = Math.sin(angle);
      ctx.beginPath();
      ctx.moveTo(p.x - dx * p.r * arm, p.y - dy * p.r * arm);
      ctx.lineTo(p.x + dx * p.r * arm, p.y + dy * p.r * arm);
      ctx.stroke();

      if (large) {
        const bx = p.x + dx * p.r * 0.65;
        const by = p.y + dy * p.r * 0.65;
        for (const sign of [-1, 1]) {
          const branch = angle + (sign * Math.PI) / 3;
          ctx.beginPath();
          ctx.moveTo(bx, by);
          ctx.lineTo(
            bx + Math.cos(branch) * p.r * 0.55,
            by + Math.sin(branch) * p.r * 0.55
          );
          ctx.stroke();
        }
      }
    }
  }

  function frame(timestamp) {
    if (!running) return;
    const dt = Math.min(0.05, (timestamp - (last || timestamp)) / 1000);
    last = timestamp;
    ctx.clearRect(0, 0, width, height);
    for (const p of particles) {
      p.phase += p.sway * dt;
      p.x += (p.vx + Math.sin(p.phase) * p.swayAmp) * dt;
      p.y += p.vy * dt;
      p.rot += p.spin * dt;

      if (p.y > height + p.r * 2) {
        p.y = -p.r * 2;
        p.x = rand(0, width);
      }
      if (p.x < -20) p.x = width + 20;
      else if (p.x > width + 20) p.x = -20;

      drawParticle(p);
    }
    raf = window.requestAnimationFrame(frame);
  }

  function start() {
    if (running || !enabled || !active || reducedMotion) return;
    if (width !== window.innerWidth || height !== window.innerHeight) resize();
    if (!width || !height) return;
    running = true;
    last = 0;
    raf = window.requestAnimationFrame(frame);
  }

  function stop() {
    running = false;
    if (raf) window.cancelAnimationFrame(raf);
    raf = null;
    if (ctx && width && height) ctx.clearRect(0, 0, width, height);
  }

  function sync() {
    document.body.classList.toggle("snow-enabled", enabled);
    if (enabled && active && !reducedMotion) start();
    else stop();
  }

  function setup() {
    if (setupDone) return;
    setupDone = true;
    enabled = effectFromUser() === "snow";
    active = !!document.querySelector("#panel-recipes.active");
    resize();
    window.addEventListener("resize", resize, { passive: true });
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "hidden") stop();
      else sync();
    });

    const onReduce = (event) => {
      reducedMotion = !!event.matches;
      sync();
    };
    const onDark = (event) => {
      dark = !!event.matches;
    };
    if (reduceQuery.addEventListener) reduceQuery.addEventListener("change", onReduce);
    else reduceQuery.addListener(onReduce);
    if (darkQuery.addEventListener) darkQuery.addEventListener("change", onDark);
    else darkQuery.addListener(onDark);

    sync();
  }

  function setEffect(value) {
    enabled = value === "snow";
    sync();
  }

  function setActive(value) {
    active = !!value;
    sync();
  }

  RM.snow = { setup, setEffect, setActive };
})(window.RM);
