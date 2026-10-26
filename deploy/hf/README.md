---
title: WARRANT
emoji: 🪪
colorFrom: indigo
colorTo: gray
sdk: docker
app_port: 7860
pinned: true
short_description: Agents that can't cross a department line without a warrant
---

# WARRANT

A multi-agent system where agents can't reach across organisational boundaries
without a warrant, and replan when they're refused.

**Try it:** press **Run audit**. The Expense Auditor (Finance) plans a Q3 expense
audit with NVIDIA Nemotron, asks WARRANT for every piece of data another
department owns, and finds what it can. WARRANT refuses it salary data, so six
claims stay unchecked and one overpayment stays hidden. Open **Approvals**,
approve as People & Culture, run again, and the agent finds it.

- The authorization decision is deterministic: computed from who owns what, with
  no model in it.
- Nemotron plans the audit, writes every request, drafts the grant request and
  the summary.
- Inference runs on **Nebius Token Factory** (Nemotron 3 Nano 30B and Super 120B).
  This Space only hosts the console and the plane.

Built for the Nebius × NVIDIA Global AI Hackathon 2026 · Best Apps and Agents.

Source, architecture and decision records:
**https://github.com/jwlai-cloud/warrant**
