// The guided tour: ten steps through the story a judge needs to see, with the
// visitor doing the clicking (run, approve, re-run) so the "aha" is theirs.
// A ring dims everything but the element being explained, the same idea as
// the video's overlay. Driven by window.__warrant, which index.html exposes.
(function () {
  var W = window.__warrant;
  var STEPS = [
    { view: "overview", at: "#ovRun", title: "Run the audit",
      text: "The Expense Auditor works for Finance and has 47 Q3 claims to check. Press Run audit. Nemotron plans the work, and every request for another department's data has to go through WARRANT first.",
      wait: "run", hint: "Press Run audit to continue. The agent's trace appears as it works." },
    { view: "runs", at: "#timeline li[data-kind='plan']", title: "The agent's own plan",
      text: "Nemotron 3 Super, on Nebius Token Factory, wrote this plan: which department to ask, and for what. Next, the agent asks WARRANT for each step." },
    { view: "runs", at: "#timeline li[data-kind='granted']", title: "Granted: a warrant",
      text: "Finance holds a grant to this data, so WARRANT issued a signed, single-use warrant. Nemotron only worked out which data the request touches. The grant table made the decision, with no model involved." },
    { view: "runs", at: "#timeline li[data-kind='refused']", title: "Refused, with the reason",
      text: "Salaries belong to People & Culture and are restricted, and Finance holds no grant to them. So the answer is no, and it names the missing grant and who owns the data." },
    { view: "runs", at: ".expo-run", title: "It still did its job",
      text: "The agent audited everything it was allowed to see: 3 claims flagged, £2,561 under query. The 6 allowance claims stay blocked, because they can't be checked without salaries." },
    { view: "runs", at: "#timeline li[data-kind='escalate']", title: "Then it asked the owner",
      text: "Instead of failing, the agent drafted a grant request to People & Culture, saying what it needs and why." },
    { view: "approvals", at: "#reqList .review", title: "A second agent reviews it",
      text: "The Steward Agent works for the data owner. It checks the request against the audit log and makes a recommendation. It cannot grant anything." },
    { view: "approvals", at: "#reqList button.ok", title: "You are the steward: approve it",
      text: "Only a person can grant access. Approve as People & Culture. The grant is written to the model, with your note on record.",
      wait: "approved", hint: "Press Approve to continue." },
    { view: "overview", at: "#ovRun", title: "Run it again",
      text: "Same agent, same claims. This time the request for salaries is granted.",
      wait: "run", hint: "Press Run audit again." },
    { view: "runs", at: "#findings .finding[data-claim='CLM-3606']", title: "The overpayment nobody could see",
      text: "CLM-3606: a £290 travel allowance against a £255 band cap. It was found only because the owner said yes. That is WARRANT: an agent crosses a department line only with a warrant, and replans when it is told no." }
  ];

  var ring, card, i = -1, base = 0, raf = 0, entered = 0;

  function el(tag, cls, text) {
    var e = document.createElement(tag); if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text; return e;
  }

  function build() {
    ring = el("div", "tour-ring"); ring.setAttribute("aria-hidden", "true");
    card = el("div", "tour-card"); card.setAttribute("role", "dialog");
    card.setAttribute("aria-live", "polite"); card.setAttribute("aria-label", "Guided tour");
    document.body.append(ring, card);
  }

  function done(step) {
    var s = W.state();
    if (step.wait === "run") return !s.running && s.runsDone > base;
    if (step.wait === "approved") return s.reqs.some(function (r) { return r.state === "approved"; });
    return false;
  }

  function render() {
    var s = STEPS[i]; card.textContent = "";
    var top = el("div", "tour-top");
    top.append(el("span", "tour-n", (i + 1) + " / " + STEPS.length));
    var x = el("button", "tour-x", "Skip tour"); x.type = "button"; x.onclick = stop;
    top.append(x); card.append(top);
    card.append(el("h3", null, s.title), el("p", null, s.text));
    var row = el("div", "tour-row");
    if (i > 0 && !STEPS[i - 1].wait) {
      var back = el("button", "btn", "Back"); back.type = "button";
      back.onclick = function () { go(i - 1); }; row.append(back);
    }
    if (s.wait) row.append(el("span", "tour-hint", s.hint));
    else {
      var next = el("button", "btn primary", i === STEPS.length - 1 ? "Finish" : "Next");
      next.type = "button"; next.onclick = function () { i === STEPS.length - 1 ? stop() : go(i + 1); };
      row.append(next);
    }
    card.append(row);
  }

  function go(n) {
    i = n; var s = STEPS[i];
    base = W.state().runsDone; entered = Date.now();
    if (W.current() !== s.view) W.show(s.view);
    render();
    var t = document.querySelector(s.at);
    if (t) setTimeout(function () { t.scrollIntoView({ block: "center", behavior: "smooth" }); }, 60);
  }

  // Follows the target every frame: the trace grows and the page scrolls while
  // a step is open, so a position measured once goes stale.
  function frame() {
    var s = STEPS[i], t = document.querySelector(s.at);
    var r = t && t.offsetParent !== null ? t.getBoundingClientRect() : null;
    var narrow = innerWidth < 720;
    if (r && r.width) {
      Object.assign(ring.style, { opacity: 1, left: r.left - 8 + "px", top: r.top - 8 + "px",
        width: r.width + 16 + "px", height: r.height + 16 + "px" });
    } else ring.style.opacity = 0;
    if (narrow || !r) {
      Object.assign(card.style, { left: "", top: "", right: "16px", bottom: "16px" });
    } else {
      var ch = card.offsetHeight, cw = card.offsetWidth;
      var y = r.bottom + 18 + ch < innerHeight ? r.bottom + 18 : Math.max(12, r.top - ch - 18);
      var x = Math.max(12, Math.min(r.left, innerWidth - cw - 12));
      Object.assign(card.style, { right: "", bottom: "", left: x + "px", top: y + "px" });
    }
    // a "wait" step advances itself once its condition holds; a short floor
    // stops a stale state from skipping it the instant it opens
    if (s.wait && Date.now() - entered > 600 && done(s)) {
      setTimeout(function () { go(i + 1); }, 700);
      entered = Infinity;
    }
    raf = requestAnimationFrame(frame);
  }

  function stop() {
    cancelAnimationFrame(raf); i = -1;
    ring.style.opacity = 0; card.hidden = true;
    document.body.classList.remove("touring");
  }

  W.startTour = async function () {
    if (!ring) build();
    await W.reset();
    card.hidden = false; document.body.classList.add("touring");
    go(0);
    cancelAnimationFrame(raf); raf = requestAnimationFrame(frame);
  };
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && i >= 0) stop(); });
})();
