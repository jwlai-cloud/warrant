# Demo video — shot list and narration

**Hard limit: under 3:00** (Devpost rule: "less than three (3) minutes").
Target **2:50**. Narration is ~375 words, which reads at a natural pace in
about 2:35–2:45 — leave the margin, do not fill it.

Footage is captured by `scripts/capture_demo.py`: it drives the real console
against live Nemotron and cuts the dead waiting time out automatically, so
every frame is a real call. You record **narration only**, over the finished
footage.

| # | Time | On screen | Narration | Technique |
|---|---|---|---|---|
| 1 | 0:00–0:15 | Overview: four checks, KPIs at zero | "Companies are giving AI agents real jobs. This one audits expenses for Finance. But the evidence it needs — contracts, rosters, salaries — belongs to other departments. So who decides what an agent is allowed to see? That's WARRANT." | hold, slow zoom toward the checks table |
| 2 | 0:15–0:30 | Overview checks table: *Needs* / *Owned by* columns | "Forty-seven Q3 claims. Four checks. Only one can be done with Finance's own data. The other three need data owned by Operations and by People & Culture — including salaries, which are restricted." | highlight the *Owned by* column |
| 3 | 0:30–0:45 | Press **Run audit** → plan appears | "I press Run. Nemotron reads the claims and plans the audit itself — and in its own words, it splits the requests so it never mixes data it may see with data it may not." | zoom into Nemotron's quoted rationale |
| 4 | 0:45–1:00 | Two GRANTED rows | "Every request goes to WARRANT. The roster: granted. Supplier contracts: granted. And no model makes those decisions — they come from the grant table: who owns the data, and who has been given access." | highlight "decided by the grant table, no model" |
| 5 | 1:00–1:10 | REFUSED row with the steward reason | "Salaries: refused. And the refusal says why — Finance holds no grant to employee compensation, and People & Culture is the steward." | red highlight box on the reason |
| 6 | 1:10–1:25 | Findings column filling, £2,561 | "The agent doesn't stop. It finds three real problems: a duplicate invoice, a supplier billing above contract, and a flight on a day the employee never travelled. Two thousand five hundred pounds under query." | zoom on the findings column |
| 7 | 1:25–1:35 | ESCALATE row, Nemotron's grant request | "Six claims it couldn't check — so Nemotron drafts a grant request, addressed to the one person who can approve it." | hold on the quoted request |
| 8 | 1:35–1:55 | Approvals → request card → **Approve** → Grant Matrix cell fills | "Now the human part. The steward sees who is asking, for what, and exactly what's blocked — and approves. The grant is written into the model." | cursor to Approve; flash on the new matrix cell |
| 9 | 1:55–2:15 | **Run again** → CLM-3606 appears, £2,851 | "Run it again. This time the salary check runs — and finds a fourth problem: a two-hundred-and-ninety-pound allowance over the band cap. The refusal hadn't just left work undone. It was hiding an overpayment." | zoom on CLM-3606 |
| 10 | 2:15–2:35 | Blueprint: architecture figure, the crossed-out edge | "Under the hood: the agent plans with NVIDIA Nemotron on Nebius Token Factory. WARRANT's decision engine has no model in it at all — so every decision is reproducible and auditable. And it's exposed over MCP, so any agent can ask." | Ken Burns across the diagram to the "no edge" mark |
| 11 | 2:35–2:48 | Proof card | "We red-teamed it ourselves: an adversarial review, forty findings fixed, eighty-one tests — and our own eval caught a prompt injection, which we measured and instrumented instead of hiding." | text card, hold to read |
| 12 | 2:48–2:58 | Close card: tagline + links | "Okta knows who the agent is. LeanIX knows who owns the data. WARRANT is the join — with agents that replan when they're told no." | links on screen ≥ 4s |

## Proof card (shot 11) — exact text

```
Deterministic authorization — no model in the decision
Nemotron 3 Nano 30B + Super 120B on Nebius Token Factory
Adversarial review: 40 findings confirmed and fixed
81 tests · classifier eval with recall reported first
A prompt injection found by our own eval — measured, instrumented, documented (ADR-0009)
```

## Close card (shot 12)

```
WARRANT
Agents that can't cross a department line without a warrant —
and replan when they're refused.

Live demo   <Hugging Face URL>
Code        github.com/jwlai-cloud/warrant
```

## Numbers that must match everywhere

Video, README, Devpost write-up and the running demo must state the same
figures. Before submitting, grep for each.

| Figure | Value |
|---|---|
| Claims | 47, £11,179.80 |
| Before approval | 38 verified · 3 flagged · 6 blocked · £2,561.00 under query |
| After approval | 43 verified · 4 flagged · 0 blocked · £2,851.00 under query |
| The hidden one | CLM-3606, £290 allowance vs £255 band cap |
| Tests | 81 |
| Review | 40 confirmed findings, all fixed |

## Recording narration

- Quiet room, phone or laptop mic held ~20cm away, record each row as its own
  take — re-recording one line is easier than one long take.
- Read at a natural pace. If a line runs long, cut words rather than speeding up.
- Watch the final once **with sound off**: the on-screen text alone should tell
  the story.
