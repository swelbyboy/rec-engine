Here are the core concepts, in plain terms, roughly in the
order they appear in the pipeline:

---

1. Embeddings  


The most fundamental concept in the whole system. Instead  
 of asking "does this string equal that string?", you  
 convert text into a list of ~1500 numbers (a vector) that  
 captures meaning. Two pieces of text that mean similar  
 things produce vectors that point in a similar direction in
that high-dimensional space — even if the words are
completely different.

This is how "distributed systems" matches "distributed
systems design", and why "Python" wouldn't match "Ruby"
even though both are programming languages.

Everything interesting in this system runs on embeddings.

---

2. Cosine similarity

Once you have two vectors, you need a number for "how
similar are these?" Cosine similarity measures the angle
between two vectors. Score of 1.0 = pointing in exactly the
same direction (identical meaning). Score of 0.0 =
perpendicular (unrelated). Score of -1.0 = opposite
meaning.

The threshold of 0.75 used in skill matching means: "I'll
only count this as a match if the two skills are at least
this similar in meaning-space."

---

3. Vector retrieval (semantic search)

With 30 candidates today — but imagine 30,000. You can't
run expensive constraint checks and scoring on all of them.
So the first stage embeds the job description and finds
the top-K most semantically similar candidates using cosine
similarity against pre-computed candidate embeddings. This
is the same mechanism behind every modern search engine
and "find similar" feature.

The candidate embeddings are pre-computed and cached. The
JD embedding happens once per query. Then it's just matrix
maths — fast.

---

4. Feature engineering

The 10-dimensional feature vector (required_skills_overlap,
experience_delta, seniority_match, etc.) is classic ML
feature engineering: taking raw, messy inputs and
converting them into clean numerical signals a model can
work with.

Each feature is a deliberate design decision — what signals
actually predict fit? experience_delta uses an asymmetric
function: below minimum = 0 (a hard floor), above minimum =
linear improvement. That asymmetry is a modelling choice
baked into the feature.

This is what a data scientist would spend most of their
time on in a real system.

---

5. Weighted linear model

The simplest possible supervised model: weighted sum of
features. score = 0.38 × skills + 0.10 × preferred_skills +
...

Every candidate gets the same formula. The weights express
what matters for this role type. It's interpretable (you
can explain every score exactly), fast, and easy to debug.
The downside — and why the data scientist would push back —
is that the weights were chosen by hand, not learned from
data.

---

6. LLM as a structured extractor

This is a specific and important use pattern. You're not
using Claude to have a conversation or generate text —
you're using it as a zero-shot information extraction
engine. Pass in a JD or CV, get back a structured JSON
object with typed fields, values, operators, and confidence
scores. The alternative would be hundreds of regex
patterns and NLP rules. The LLM handles ambiguity, implicit
signals, and varied phrasing automatically.

The quality of everything downstream depends entirely on
this step. Garbage in, garbage out.

---

7. The pipeline pattern

The overall architecture — Retrieve → Filter → Score →
Explain — is a standard pattern in production ML systems,
called a retrieval-augmented ranking pipeline. Each stage
progressively reduces the candidate set using increasingly
expensive operations:

- Retrieval: fast vector maths, keeps top-50
- Constraint filtering: rule-based, eliminates hard
  mismatches
- Scoring: linear model over 10 features
- Explanation: LLM call (the most expensive — only runs on
  top-10)

This staged approach is why it's fast enough to be
interactive.

---

What to emphasise in the demo

The most visually compelling concepts, in order:

1. Semantic skill matching — show that "distributed
   systems" matches "distributed systems design" without exact
   string equality. This surprises people.
2. The pipeline stages streaming live — the step-by-step
   progress is the clearest way to show this is a real ML
   pipeline, not a database query.
3. The feature breakdown bars — expanding a candidate card
   to show the 10 dimensions is the most tangible
   demonstration that this is a scoring model, not a keyword
   filter.
4. Extraction auditability — showing the JobDetailsPanel
   with [canonical_key requires 3 ⚠] inline demonstrates that
   the system is inspectable, which is what separates a demo
   from a toy.

✻ Cooked for 59s
