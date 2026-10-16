# Customer-context note

*A short brief on who this is for and why it is built the way it is — the kind of
note a forward-deployed engineer writes after the first discovery calls.*

## The customer

A **mid-size Romanian personal-lines insurer** writing **Home/Property** and **Life –
Credit Protection Insurance (CPI)** (cover attached to a bank loan that repays the
loan on the borrower's death, disability, temporary incapacity, or involuntary
unemployment).

## The team and the pain

The **claims-intake (FNOL) desk** — a **small, non-technical ops team** (3–8 people).
They receive **~200–400 loss notifications a day** in whatever format the customer or
lender sends: free-text emails, web-form text, PDF loss notices, and **photos of
handwritten forms**, in Romanian and English.

Today each notification is read by a human who:
1. figures out the line of business and type of loss,
2. keys the details into the claims system,
3. decides which adjuster queue it goes to, and whether anything looks off
   (large loss, injury, possible fraud, a death soon after the policy started), and
4. sends an acknowledgment.

This is **~6–10 minutes per claim**, it is repetitive, and it is error-prone —
mis-keyed policy numbers, a high-severity claim put in the wrong queue, or a
contestable death not flagged for investigation are costly mistakes.

## What we built, and the one principle that governs it

A tool that turns the job from **typing into reviewing**: the AI reads the
notification and proposes a structured claim (fields, line of business, type,
severity, suggested flags); deterministic code applies the insurer's own rules
(routing, severity floors, fraud/contestability flags, policy verification); and the
handler **reviews and approves** on a screen that shows the original document beside
the proposal. Target: **~2 minutes per claim.**

> **The model proposes, code checks, the human decides.** The AI never books a claim,
> sets a reserve, or decides eligibility. For Life/CPI especially, contestability or
> fraud is only ever a *flag for a person* — never an automated decision.

This matters because the expensive failure is not "the AI missed something" (the human
catches that in review) — it is **the AI quietly auto-approving something wrong**. So the
system is tuned to prefer "needs a look" (amber) over a risky "ready" (green); in testing,
**every case it marked ready was correct (green precision = 1.00).**

## Why it is built to be maintained by the business, not by engineering

The single most important design choice is that **the ops lead owns the workflow**, not
the vendor. Insurance operations change constantly: a new peril, a reorganised adjuster
queue, a changed large-loss threshold, a seasonal catastrophe surge, a new fraud pattern.
If every such change needs an engineering ticket, the tool rots.

So the taxonomy, routing rules, templates, thresholds and **flags** live in a **config the
team edits in the app**, with a **preview** that shows exactly which past cases a change
would re-route *before* it goes live, plus **version history and one-click rollback**.

Flags are worth a note, because they are where the team gained the most control. A flag
can be triggered three ways: by **keywords**, by a fixed **built-in condition** (an exact
computation — amount over a threshold, a death inside the contestability window), or by a
**natural-language rule the model judges** ("flag anything that reads like possible arson").
That last kind lets a non-technical owner **add a new flag by describing it in words** — no
keyword lists, no code. Crucially, the model only *decides whether the flag applies*; the
**effect** (which queue, what severity, that a human must review) stays deterministic config.
So the business gets flexibility where it helps (spotting fuzzy, semantic signals) while the
consequences remain auditable. Engineering owns only the safety-critical control flow and the
menu of built-in conditions.

## Trust and rollout

- **Start in "review everything" mode** (lower the auto-ready threshold) so the team
  builds trust while the override-rate metric shows how often they change the AI.
- **The baseline is free and always available** (a non-AI mock provider), so the app,
  tests and evaluation run with no API key — useful for demos and for a cost-free fallback.
- **Observability from day one:** per-document latency/cost and the human **override rate**
  tell the business when to trust more, retune the config, or change models.

## What is deliberately out of scope for this prototype

Real integration with the core claims platform (simulated here), authentication,
multi-level approvals, payments, multi-tenancy, and production-grade prompt-injection
defense. These are the obvious next steps for a pilot, not blockers for proving the value.
