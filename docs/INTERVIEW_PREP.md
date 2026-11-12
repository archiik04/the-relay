# Interview prep (evolving)

Rule for this file: every answer must be something Archi can say **without
reading it**. If an answer here is only memorised, it doesn't count. Rewrite it
in your own words until it's yours.

## Core story (one breath)
Overload is arithmetic. A burst asks for more model calls than the provider
allows. Every system then gives up one of four things: fast, good, cheap, or
nobody turned away. We keep answers verified, keep quota spending low, and turn
people away **early and honestly** instead of letting them time out slowly.

## Concepts you must own
| Concept | Plain version | Why it's in this project |
|---|---|---|
| Load shedding | Saying "busy, retry in Xs" right away instead of queueing forever | During overload, people are turned away either way: fast or slow |
| Goodput | Useful verified answers, not raw requests handled | Our headline metric, per unit of daily quota |
| Bounded queue | A queue with a maximum length | An unbounded queue turns every request into a late one |
| FIFO vs EDF | Serve in arrival order vs serve the nearest deadline first | EDF fails in a cascade under overload (it serves the requests about to miss anyway) |
| TPM vs RPM | Tokens per minute vs requests per minute | With RAG prompts, TPM probably binds first. Verify in M3. |
| Reasoning tokens | Hidden "thinking" the model produces before visible text | Uses TPM and delays the first token on gpt-oss |
| Coordinated omission | A load tester that waits for replies sends less when the system is slow, which hides the problem | Why we use open-loop arrivals |
| Version pinning | Proving which exact PDF version we read | The brief names versions; our check uses arXiv's own page-1 stamp |

## Likely questions and the core of a good answer
- **"Why not stream tokens as they're generated?"** Text the user has already seen can't be taken back. We set a rule in advance: buffer if the median gap between first and last token is ≤ 250 ms, and the M3 measurement decides. (D1)
- **"Isn't rejecting users bad?"** The alternative isn't serving them. It's making them wait, then timing them out. (D4)
- **"Why FIFO and not deadline-first?"** EDF fails in a cascade under overload. We drop expired requests when they leave the queue instead. (D5)
- **"How do you know you have version 7?"** arXiv prints a version stamp in the margin of page 1. We match it *exactly* (a plain substring check would let a v10 stamp pass a v1 check, and our first version had exactly that bug). The check itself is tested on made-up stamps from other versions, to prove it can fail.
- **"Why gpt-oss-20b?"** Same documented limits as 120b, Production status, cheaper. The A/B test decides whether quality justifies 120b.

- **"Why section-aware chunks instead of fixed windows?"** (Archi's argument, in their words) A chunk that mixes two sections can be retrieved for keywords from both. The model then merges claims that the paper keeps apart and cites the wrong section. Boundaries should preserve meaning, not just satisfy a token limit.
- **"How did you know your extraction was right?"** We didn't trust counts. We read random samples, and every problem found by eye (missing spaces, figures read as tables, table numbers deleted) became a test.
- **"Where does your retriever get fooled?"** Real examples from these PDFs: (1) table rows are merged, so numbers pair with the wrong model (Attention Table 2); (2) "10^19" extracts as "1019"; (3) references and synthetic dialogues match keywords but aren't evidence, so we excluded them; (4) tables carry the section of the page they sit on, not the section that discusses them.

## Misconceptions caught so far (keep these honest)
- "Groq" (inference provider) ≠ "Grok" (xAI's chatbot).
- One account = one API key. You pick the **model** in each request.
- 200–250 ms works as a limit on *extra wait from buffering*, not as a target for the whole answer. Under the TPM limit, a burst means waits of minutes.
- With deadlines in place, starvation can't happen.
- A test that can never fail proves nothing. Test the *checker* with inputs it must reject, not only the happy path.
- The stamp is printed by arXiv for the version it serves, so "a wrong version with the right stamp" isn't the risk. The risk is a **checker too loose** to tell versions apart.
- "Never weaken answers" contradicts the brief, which asks who gets a weaker answer. The rule is: weaker but correct, and labelled.
