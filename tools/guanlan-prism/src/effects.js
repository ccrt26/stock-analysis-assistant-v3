/*
 * PRISM optical layer — decorative, dependency-free, independently removable.
 * Does not read prices, reviews, scores or recommendation data.
 * One capped animation loop. Hidden pages stop it; reduced motion draws one frame.
 */
(function () {
  'use strict';
  const canvas = document.getElementById('prismField');
  const motionButton = document.getElementById('motionButton');
  if (!canvas || !motionButton) return;
  const ctx = canvas.getContext('2d');
  if (!ctx) { canvas.hidden = true; motionButton.hidden = true; return; }
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  const coarse = window.matchMedia('(pointer: coarse)');
  const storageKey = 'guanlan.prism.motion';
  let requested = true;
  try { requested = localStorage.getItem(storageKey) !== 'off'; } catch (_) { /* session only */ }
  let frameId = 0, lastFrame = 0, phase = 0, width = 570, height = 290;
  let pointerX = 0, pointerY = 0, hoverCard = null, resizeTimer = 0;
  let renderedFrames = 0;
  let lightTheme = document.body.classList.contains('light');
  const TAU = Math.PI * 2;
  const enabled = () => requested && !reduced.matches;
  const canRun = () => enabled() && !document.hidden && window.scrollY < 430;

  function project(x, y, z, t) {
    // A lightly undulating, inclined torus. Its position is not a financial plot.
    const tilt = .84 + Math.sin(t * .22) * .08;
    const yaw = -.24 + Math.cos(t * .18) * .055 + pointerX * .024;
    const roll = -.28 + Math.sin(t * .14) * .045;
    const yy = y * Math.cos(tilt) - z * Math.sin(tilt);
    const zz = y * Math.sin(tilt) + z * Math.cos(tilt);
    const xx = x * Math.cos(yaw) + zz * Math.sin(yaw);
    const depth = -x * Math.sin(yaw) + zz * Math.cos(yaw);
    const scale = Math.min(width / 385, height / 205) * 470 / (470 - depth);
    return {
      x: width * .55 + (xx * Math.cos(roll) - yy * Math.sin(roll)) * scale,
      y: height * .50 + (xx * Math.sin(roll) + yy * Math.cos(roll)) * scale + pointerY * 1.6,
      depth
    };
  }
  function render(t = phase) {
    ctx.clearRect(0, 0, width, height);
    const cx = width * .55, cy = height * .5;
    const haze = ctx.createRadialGradient(cx + 20, cy, 15, cx, cy, width * .37);
    haze.addColorStop(0, lightTheme ? 'rgba(83,114,214,.045)' : 'rgba(81,101,214,.075)');
    haze.addColorStop(.57, lightTheme ? 'rgba(76,163,195,.025)' : 'rgba(56,136,177,.04)');
    haze.addColorStop(1, 'rgba(55,83,190,0)');
    ctx.fillStyle = haze; ctx.fillRect(0, 0, width, height);
    ctx.globalCompositeOperation = lightTheme ? 'source-over' : 'lighter';
    const spectrum = ctx.createLinearGradient(width * .21,height * .82,width * .82,height * .16);
    spectrum.addColorStop(0,lightTheme ? '#298f80' : '#92fbd2');
    spectrum.addColorStop(.35,lightTheme ? '#488dad' : '#8ce3f0');
    spectrum.addColorStop(.68,lightTheme ? '#5e72b8' : '#8ba1ff');
    spectrum.addColorStop(1,lightTheme ? '#9174bd' : '#c3a2ff');
    const loops = width < 380 ? 38 : 58;
    const segments = 128;
    // Threaded contour loops form the optical volume. Every frame is deterministic.
    for (let k = 0; k < loops; k++) {
      const v = TAU * k / loops;
      ctx.beginPath();
      for (let i = 0; i <= segments; i++) {
        const u = TAU * i / segments;
        const minor = 22 + 2.6 * Math.sin(3 * u + t * .38);
        const major = 86 + 2 * Math.sin(2 * u - t * .26);
        const twist = v + .46 * Math.sin(2 * u + t * .19);
        const x = (major + minor * Math.cos(twist)) * Math.cos(u);
        const y = (major + minor * Math.cos(twist)) * Math.sin(u);
        const z = minor * Math.sin(twist) + 7 * Math.sin(2 * u - .6);
        const p = project(x, y, z, t);
        if (i === 0) ctx.moveTo(p.x, p.y); else ctx.lineTo(p.x, p.y);
      }
      const alpha = (lightTheme ? .14 : .20) + .13 * (.5 + .5 * Math.cos(v + .8));
      ctx.strokeStyle = spectrum; ctx.globalAlpha = alpha;
      ctx.lineWidth = k % 5 === 0 ? .82 : .48;
      ctx.stroke();
    }
    ctx.globalAlpha = 1;
    // Sparse transverse threads make refraction legible without using raster assets.
    for (let j = 0; j < 24; j++) {
      const u = j / 24 * TAU;
      ctx.beginPath();
      for (let i = 0; i <= 40; i++) {
        const v = i / 40 * TAU + .46 * Math.sin(2 * u + t * .19);
        const minor = 22 + 2.6 * Math.sin(3 * u + t * .38);
        const major = 86 + 2 * Math.sin(2 * u - t * .26);
        const p = project((major + minor * Math.cos(v)) * Math.cos(u), (major + minor * Math.cos(v)) * Math.sin(u), minor * Math.sin(v) + 7 * Math.sin(2 * u - .6), t);
        if (i === 0) ctx.moveTo(p.x, p.y); else ctx.lineTo(p.x, p.y);
      }
      ctx.strokeStyle = lightTheme ? 'rgba(89,125,181,.1)' : 'rgba(168,215,252,.13)';
      ctx.lineWidth = .45; ctx.stroke();
    }
    // A pair of soft optical glints; these are not observation nodes.
    for (let i = 0; i < 2; i++) {
      const u = 1.1 + i * 3.3 + t * .055;
      const p = project(109 * Math.cos(u), 109 * Math.sin(u), 7 * Math.sin(2 * u), t);
      const glow = ctx.createRadialGradient(p.x,p.y,0,p.x,p.y,12);
      glow.addColorStop(0,lightTheme ? 'rgba(48,133,155,.25)' : 'rgba(177,250,236,.68)');
      glow.addColorStop(.14,lightTheme ? 'rgba(67,151,187,.15)' : 'rgba(121,221,244,.2)');
      glow.addColorStop(1,'rgba(70,146,210,0)');
      ctx.fillStyle = glow; ctx.fillRect(p.x-12,p.y-12,24,24);
    }
    ctx.globalCompositeOperation = 'source-over';
    renderedFrames++;
  }
  function size() {
    const r = canvas.getBoundingClientRect();
    width = Math.max(1,r.width); height = Math.max(1,r.height);
    const ratio = Math.min(window.devicePixelRatio || 1, 1.75);
    canvas.width = Math.round(width * ratio); canvas.height = Math.round(height * ratio);
    ctx.setTransform(ratio,0,0,ratio,0,0); render();
  }
  function tick(stamp) {
    if (!canRun()) { frameId = 0; return; }
    if (!lastFrame || stamp - lastFrame >= 32) {
      if (lastFrame) phase += Math.min(stamp - lastFrame, 80) / 1000;
      lastFrame = stamp;
      render();
    }
    frameId = requestAnimationFrame(tick);
  }
  function sync() {
    if (frameId) cancelAnimationFrame(frameId);
    frameId = 0; lastFrame = 0;
    document.body.classList.toggle('motion-off', !enabled());
    motionButton.setAttribute('aria-pressed', String(enabled()));
    motionButton.setAttribute('aria-label', reduced.matches ? '系统已启用减少动态效果' : enabled() ? '关闭视觉动效' : '开启视觉动效');
    motionButton.title = reduced.matches ? '系统已启用减少动态效果' : enabled() ? '视觉动效已开启 · 点击关闭' : '视觉动效已关闭 · 点击开启';
    motionButton.disabled = reduced.matches;
    if (!enabled()) { pointerX = 0; pointerY = 0; }
    render();
    if (canRun()) frameId = requestAnimationFrame(tick);
  }
  function setEnabled(on) {
    requested = Boolean(on);
    try { localStorage.setItem(storageKey, requested ? 'on' : 'off'); } catch (_) { /* session only */ }
    sync();
  }
  motionButton.addEventListener('click', () => setEnabled(!requested));
  reduced.addEventListener('change', sync);
  document.addEventListener('visibilitychange', sync);
  window.addEventListener('scroll', () => {
    if (!canRun() && frameId) {cancelAnimationFrame(frameId);frameId=0;lastFrame=0;}
    else if (canRun() && !frameId) frameId = requestAnimationFrame(tick);
  }, {passive:true});
  window.addEventListener('resize', () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => {size();sync();},100); }, {passive:true});
  document.addEventListener('pointermove', e => {
    if (!enabled() || coarse.matches) return;
    pointerX = (e.clientX / window.innerWidth - .5) * 2;
    pointerY = (e.clientY / window.innerHeight - .5) * 2;
    const next = e.target.closest('.stat-card,.observation-card,.hero-panel');
    if (hoverCard && hoverCard !== next) {hoverCard.style.removeProperty('--mx');hoverCard.style.removeProperty('--my');}
    hoverCard = next;
    if (next) {const r=next.getBoundingClientRect();next.style.setProperty('--mx',`${e.clientX-r.left}px`);next.style.setProperty('--my',`${e.clientY-r.top}px`);}
  }, {passive:true});
  const observer = new MutationObserver(() => {
    const next = document.body.classList.contains('light');
    if (next !== lightTheme) { lightTheme = next; render(); }
  });
  observer.observe(document.body, {attributes:true,attributeFilter:['class']});
  // Drawing is stable on mount. The app dispatches the event after page navigation.
  document.addEventListener('guanlan:render', () => { hoverCard = null; sync(); });
  size();sync();
  // Test/capture hooks. No business-state mutations are exposed here.
  window.GuanlanEffects = Object.freeze({
    getState: () => ({enabled:enabled(),requested,reduced:reduced.matches,running:!!frameId,frames:renderedFrames}),
    setEnabled,
    renderAt: t => {phase = Number.isFinite(t) ? t : 0;render(phase);}
  });
})();
