# Hand review by Archi: run 4 (answers-gpt-oss-20b-t384-o32-hybrid-20261112T124111Z.jsonl)

Rule applied (P1): a claim is supported only if its quote directly states it.
Labels below are Archi's, transcribed from the completed review sheet; reasons summarised in Archi's words.

| Q | Grader (g2) | Claims supported (yes/no) | Archi's verdict | Archi's reason |
|---|---|---|---|---|
| Q01 | correct | yes, no, no | **wrong** | Claim 2 adds acoustic tokens + multi-stream beyond its quote; claim 3 adds "follows from hierarchical generation" and real-time streaming beyond its quote |
| Q02 | wrong | no, no | wrong | Both claims overstate their quotes (two token streams; silence/PAD details) |
| Q03 | wrong | no, yes | wrong | Claim 1's quote does not name SeaNet; RVQ and first level omitted |
| Q04 | wrong | yes | **correct** | Quote states 6 layers and 16 heads; grader missed number words ("six", "sixteen") |
| Q05 | correct | yes | correct | Quote states all three criteria |
| Q06 | wrong | yes | **correct** | Reply says a single head would average and inhibit; grader missed "average" vs "averaging" |
| Q07 | wrong | yes | wrong | Supported but incomplete: no sine/cosine, no relative positions |
| Q08 | correct | yes, yes, no | **wrong** | Claim 3's quote only names the components; does not say the decoder restores the length |
| Q09 | wrong | yes | wrong | Supported but omits 0.5 and 1.0 |
| Q10 | wrong | no | wrong | Quote only names "the default Downsample operation" |
| Q11 | correct | yes, no | **wrong** | Claim 2 says "key and value"; the quote says the key value (the key vector) |
| Q12 | wrong | no, no | wrong | Attention quote lacks the sinusoidal detail; H-Net quote is about boundary accuracy, not cosine similarity / context |
| Q13–Q17 | refused_correctly | (no claims) | refused_correctly | Correct refusals |
| Q18 | wrong | (no claims) | wrong | Generic refusal; should say the Transformer uses no recurrence or convolution (status should be premise_false) |

Corrections confirmed by Archi (the sheet's "Agree with grade?" box had disagreed with the written conclusion):
- Q08: Agree = **No**, final judgment **wrong**: claim 3 says the decoder restores the original sequence length, but its quotation doesn't establish that.
- Q11: Agree = **No**, final judgment **wrong**: the answer says the routing module retains both key and value, while the evidence specifies the most recent token's key.
- Q18: Agree = **Yes**, final judgment **wrong**: the grader correctly marked it wrong; the response refuses generically instead of correcting the false premise.

## Summary (computed from the table above)
- **Claims: 20 in total, 10 supported by their own quote → unsupported-claim rate 50.0% (10/20).**
- Answered replies whose every claim is supported: 5 of 12 (Q04, Q05, Q06, Q07, Q09).
- **Grader vs Archi: agree on 13 of 18 (72.2%).**
  - 2 false negatives (grader `wrong`, Archi `correct`): Q04 (number words), Q06 ("average" vs "averaging").
  - 3 false positives (grader `correct`, Archi `wrong`): Q01, Q08, Q11. The key facts are present, but a claim goes beyond its quote. The grader cannot see this.
- Correct answers: grader 4/18 (22.2%); Archi 3/18 (16.7%). Refusals: both 5/6 correct; Q18 wrong in both.
