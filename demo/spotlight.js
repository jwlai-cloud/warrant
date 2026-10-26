// Video-only overlay: a ring with a caption that moves to whatever the
// narration is talking about, and dims everything else. Injected into every
// page by scripts/capture_demo.py; the product never loads it.
//
//   __spot(["#ovRun"], "Run audit")       selectors: union of all matches
//   __spot([{x, y, w, h}], "...")         rect in 1920-wide design pixels
//   __spot(null)                          clear
(() => {
  const CSS = `
    #__ring{position:fixed;z-index:2147483646;pointer-events:none;border-radius:10px;opacity:0;
      box-shadow:0 0 0 4px #F2B33D,0 0 28px 6px rgba(242,179,61,.55),0 0 0 9999px rgba(8,10,14,.52);
      transition:left .55s cubic-bezier(.2,.8,.2,1),top .55s cubic-bezier(.2,.8,.2,1),
        width .55s cubic-bezier(.2,.8,.2,1),height .55s cubic-bezier(.2,.8,.2,1),opacity .35s}
    #__cap{position:fixed;z-index:2147483647;pointer-events:none;opacity:0;max-width:760px;
      background:#F2B33D;color:#14171F;font:700 21px/1.25 Archivo,"IBM Plex Sans",sans-serif;
      letter-spacing:.2px;padding:9px 16px;border-radius:6px;box-shadow:0 8px 24px rgba(0,0,0,.35);
      transition:opacity .3s,transform .3s;transform:translateY(6px)}
    #__cap.on{opacity:1;transform:none}`;
  const PAD = 10;

  function nodes() {
    let ring = document.getElementById("__ring");
    if (!ring) {
      const st = document.createElement("style");
      st.textContent = CSS;
      document.documentElement.appendChild(st);
      ring = document.createElement("div"); ring.id = "__ring";
      const cap = document.createElement("div"); cap.id = "__cap";
      document.documentElement.append(ring, cap);
    }
    return [ring, document.getElementById("__cap")];
  }

  function box(targets) {
    const k = innerWidth / 1920;
    const rs = targets.flatMap(t => typeof t === "string"
      ? [...document.querySelectorAll(t)].map(e => e.getBoundingClientRect()).filter(r => r.width)
      : [{left: t.x * k, top: t.y * k, right: (t.x + t.w) * k, bottom: (t.y + t.h) * k}]);
    if (!rs.length) return null;
    return {l: Math.min(...rs.map(r => r.left)) - PAD, t: Math.min(...rs.map(r => r.top)) - PAD,
            r: Math.max(...rs.map(r => r.right)) + PAD, b: Math.max(...rs.map(r => r.bottom)) + PAD};
  }

  window.__spot = (targets, label) => {
    const [ring, cap] = nodes();
    const b = targets && box(targets);
    if (!b) { ring.style.opacity = 0; cap.classList.remove("on"); return false; }
    Object.assign(ring.style, {left: b.l + "px", top: b.t + "px",
      width: (b.r - b.l) + "px", height: (b.b - b.t) + "px", opacity: 1});
    cap.classList.remove("on");
    if (!label) return true;
    cap.textContent = label;
    const h = cap.offsetHeight + 12;
    const top = b.t - h > 8 ? b.t - h : Math.min(b.b + 12, innerHeight - h);
    const left = Math.max(12, Math.min(b.l, innerWidth - cap.offsetWidth - 12));
    Object.assign(cap.style, {left: left + "px", top: top + "px"});
    setTimeout(() => cap.classList.add("on"), 250);
    return true;
  };

  // Scroll the first target into view if it is not already, resolving once the
  // scroll has finished: a ring measured mid-scroll lands in the wrong place.
  window.__reveal = (sel) => new Promise(done => {
    const e = document.querySelector(sel);
    if (!e) return done(false);
    const r = e.getBoundingClientRect();
    if (r.top >= 60 && r.bottom <= innerHeight - 20) return done(false);
    const finish = () => done(true);
    document.addEventListener("scrollend", finish, {once: true, capture: true});
    setTimeout(finish, 1500);
    e.scrollIntoView({block: "center", behavior: "smooth"});
  });
})();
