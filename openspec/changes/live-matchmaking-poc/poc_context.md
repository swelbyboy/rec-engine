We are working on a candidate recommendation system, where given a job role we'll recommend the most appropriate candiates. I want you to asess the branch and create a plan, as I feel we've drifted from the desired intention. The plan will be implemented by Sonnet, not fable.

Initial context:

**Initial ai-ssessment:**

- Mind's regression is likely traceable to a specific change: a "gates-only redesign" made the 18 soft-matching signals (skill match, experience curve, stage-fit, etc.) dormant — candidates now get ordered by hard-cutoff pass + recency only, then handed to an LLM reranker. Score-based ranking was effectively switched off. Mind's own SCORING_CHANGELOG.md shows it used to benchmark scorer versions against real placements — that rigor didn't carry into the gates-only version.
- rec-engine is a genuinely strong candidate for "the PoC to leverage": a 5-stage pipeline (LLM extraction → embedding retrieval → 3-phase constraint engine → weighted/ML scoring → LLM-generated recruiter explanations), with a working FastAPI backend + React UI, and already using OpenSpec (/opsx:propose, /opsx:apply, etc.) as its workflow. Currently runs entirely on synthetic data (30 fake candidates, 3 fake jobs, a GBT model trained on synthetic labels).
- Live data path: Mind and rec-engine's future PoC would both hit the same place — Mothership's Supabase Postgres, app.* schema (via service-role key + PostgREST). Mind currently reads the older app.bullhorn_candidates table; there's a newer, richer app.candidates gold table (89 cols, hourly refresh) Mind hasn't adopted yet. There's no API layer — it's direct DB access.
- Mothership's fct_placement / fct_sendout tables give us ground truth (who actually got placed/sent out for a role) — that's a real lever for proving "uplift" objectively rather than just eyeballing it.

Initial PoC scope:

Scope variant	Rationale	Selected
LLM scoring with improved deterministic + semantic filtering using rec-engine's 3-phase constraint engine (exact canonical match → semantic/embedding fallback → no-match-is-compatible), criteria auto-extracted from JD + Bullhorn briefing, feeding Mind's existing coarse-LLM-extraction → fine-grained-LLM-rerank funnel	Aligned with current matchmaking approach. Could be adopted near-term	Selected
Weighted-linear model with contextual, JD-derived weights — rec-engine's 10-feature linear scorer, but weights inferred per-role from job data instead of hand-tuned (auto-generated rubric analog)	Unclear linear model will understand semantic nuance and provide uplift	Discarded
Trained ML model (logistic regression / GBT) — rec-engine's models/*.joblib, trained on labeled placement outcomes 	Larger undertaking, need labelled placement data 	Discarded
Embeddings-only similarity ranking — rank purely by JD↔candidate embedding cosine similarity, no explicit feature weighting or constraint gating	Coarse, lose explainability	Discarded

Current assessment:

We have a pool of candidates, roughly 18k. We should extract and structure data for each of these once, and then store or cache it. It can be updated periodically which is out of scope of PoC. 
At runtime, we should extract and strucutre data for the job role, e.g. location, working model (hybrid, remote, in office, office days), location, skills (java, react, javascript, microservices etc). These data structures should be quickly comparable, so we can easily and cheaply filter out candidates who are not relevant. This should also include job title, but be less strict. For example, for a full stack engineer should probably be returned for a product engineer role. We may need to layer in semantic reasoning to improve this. 
This should deliver us a subset pool of candidates which we can reason over. 

This is v1. Currently this is not working well at all. See example output below:Ankar AI

Product Engineer
This is a senior full-stack product engineer role at Ankar AI requiring 8+ years of experience with demonstrated expertise across Java, Python, React, and TypeScript. The role demands hands-on ownership of shipping production systems end-to-end, with strong systems design and stakeholder communication skills—critical for a company building AI/ML patent solutions.

100 considered
8 passed filter
92 eliminated
UK-based required: no
Sponsors visa: yes
Constraint flexibility judgment

Rigid
On-site role in London; 5 days per week
Rigid
Minimum 8+ years professional software engineering experience
Rigid
Must have built and shipped production systems end-to-end
Rigid
Experience owning projects independently with scoping, execution, rollout, and iteration
Rigid
Strong systems thinking: ability to design reliable, maintainable software and debug complex issues across the stack
Rigid
Ability to communicate clearly with technical and non-technical stakeholders
Rigid
Visa sponsorship available
Ranked candidates (8)

#1
Nuno Castilho
Good match
Nuno has 17 years of seniority with strong Java, React, and TypeScript expertise plus demonstrated full-stack capability and proven enterprise delivery leadership across large geo-located teams. However, he lacks Python (a required skill) and the role brief doesn't evidence systems design or explicit end-to-end project ownership examples, which are critical for a senior product-engineering role at an AI company.

#2
Lin Li
Good match
Lin brings 26 years of experience with strong Java, Python, and explicit systems design expertise, plus 12 years of hands-on AI/ML implementation in production systems—highly relevant for Ankar AI's patent solutions focus. However, missing React and TypeScript frontend skills and no clear evidence of end-to-end product ownership, making him weaker on the full-stack requirement.

#3
Maruf Rahman
Possible
Maruf has Java and React skills with full-stack and Spring Boot backend experience, meeting 4 of 12 required/preferred skills. At 9 years, he's approaching the 8+ threshold but lacks Python, systems design, and demonstrated end-to-end project ownership—these gaps are significant for a senior product engineer role requiring hands-on architectural leadership.

#4
Maxi Schell
Possible
Maxi is a strong full-stack engineer with 13+ years, React, TypeScript, and proven product ownership at Fanvue (built high-impact API). However, he lacks Java and Python—two of the four core required languages—and systems design is not evidenced. His heavy reliance on AI tools for coding due to hand nerve issues and cultural mismatch at current role warrant consideration of fit for intensive hands-on development.

#5
Amina Jusic
Possible
Amina brings 19 years with Python and full-stack development experience, plus strong fundamentals in OOP and TDD from Makers Academy. However, she is missing React (a required skill), Java, TypeScript, and systems design. Her background is heavily Ruby/Rails-focused; transitioning her to a Java/React/TypeScript/Python stack for a senior product role would require significant ramp-up.