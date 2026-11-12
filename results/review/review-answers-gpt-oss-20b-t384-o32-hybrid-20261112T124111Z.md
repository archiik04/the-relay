# Hand review: answers-gpt-oss-20b-t384-o32-hybrid-20261112T124111Z.jsonl

Fill in **supported?** (yes/no) for every claim, and **agree with grade?** for every answer.
A claim is supported only if its quote directly states it (P1).

## Q01 (body_fact): grade `correct`
**Q:** What is the purpose of the Inner Monologue approach in Moshi, and how does it combine text and speech generation?

**Reference answer:** It improves the factuality and linguistic quality of the generated speech by having Moshi predict time-aligned text tokens before the audio tokens.

**Status:** answered · grader: all key facts, gold page cited

**Reply:**

> The Inner Monologue approach is designed to improve the linguistic quality of Moshi’s generated speech by providing a scaffolding that models the textual representation of its own speech. [moshi pp.15-16] It combines text and speech generation by first producing a sequence of text tokens that serve as a prefix to the generation of semantic and acoustic tokens, thereby enabling a hierarchical, multi‑stream architecture. [moshi pp.15-16] This hierarchical generation allows Moshi to generate arbitrary voices and conditions while remaining compatible with real‑time streaming inference. [moshi p.5]

| # | Claim | Quote (verbatim, checked) | Source | Supported? |
|---|---|---|---|---|
| 1 | The Inner Monologue approach is designed to improve the linguistic quality of Moshi’s generated speech by providing a scaffolding that models the textual representation of its own speech. | we observe that having Moshi also model the textual representation of its own speech is providing a scaffolding that increases the linguistic quality of its generation. | [moshi pp.15-16] | |
| 2 | It combines text and speech generation by first producing a sequence of text tokens that serve as a prefix to the generation of semantic and acoustic tokens, thereby enabling a hierarchical, multi‑stream architecture. | We insert W as the first sub‑sequence in V , such that it acts as a prefix to the generation of semantic tokens. | [moshi pp.15-16] | |
| 3 | This hierarchical generation allows Moshi to generate arbitrary voices and conditions while remaining compatible with real‑time streaming inference. | the integration of acoustic tokens into the same generative model enables generating arbitrary voices and conditions, rather than a single speaker. | [moshi p.5] | |

**Agree with grade?** 

---

## Q02 (body_fact): grade `wrong`
**Q:** How does Moshi's multi-stream architecture handle simultaneous user input and generated speech without explicitly modelling speaker turns?

**Reference answer:** It models the user's audio and Moshi's own audio jointly as two autoregressive token streams, which removes the concept of a speaker turn and lets it learn overlap and interruptions.

**Status:** answered · grader: missing key facts: ['token streams', 'speaker turn', 'interruptions']

**Reply:**

> Moshi’s multi‑stream architecture allows the model to speak and listen simultaneously, handling overlapping speech turns without explicit speaker‑turn boundaries. [moshi pp.14-15] During inference, Moshi can speak and listen at all times, and even speak while the user is silent, producing natural silence in the audio stream and PAD tokens in the text stream. [moshi p.17]

| # | Claim | Quote (verbatim, checked) | Source | Supported? |
|---|---|---|---|---|
| 1 | Moshi’s multi‑stream architecture allows the model to speak and listen simultaneously, handling overlapping speech turns without explicit speaker‑turn boundaries. | This design allows for our model to handle overlapping speech turns. | [moshi pp.14-15] | |
| 2 | During inference, Moshi can speak and listen at all times, and even speak while the user is silent, producing natural silence in the audio stream and PAD tokens in the text stream. | Moshi can speak and listen at all time, and do both at once if needed. | [moshi p.17] | |

**Agree with grade?** 

---

## Q03 (body_fact): grade `wrong`
**Q:** How does Mimi encode audio, and what technique do the authors use to incorporate semantic information into its acoustic representation?

**Reference answer:** Mimi turns audio into discrete tokens with residual vector quantization, and distils semantic information into the first level of those acoustic tokens.

**Status:** answered · grader: missing key facts: ['residual vector quantization', 'first level']

**Reply:**

> Mimi encodes audio by passing a single‑channel waveform through a SeaNet autoencoder that cascades residual convolutional blocks with dilated and strided convolutions, ELU non‑linearities, and weight normalization to produce a latent representation. [moshi pp.9-10] The authors incorporate semantic information by distilling non‑causal embeddings from WavLM into a single vector quantizer that produces semantic tokens, which are then combined with separate acoustic tokens for reconstruction. [moshi pp.9-10]

| # | Claim | Quote (verbatim, checked) | Source | Supported? |
|---|---|---|---|---|
| 1 | Mimi encodes audio by passing a single‑channel waveform through a SeaNet autoencoder that cascades residual convolutional blocks with dilated and strided convolutions, ELU non‑linearities, and weight normalization to produce a latent representation. | The encoder projects a single-channel waveform x ∈ ℝL to a latent representation enc(x) ∈ ℝS×D by cascading residual convolutional blocks that interleave dilated (van den Oord et al., 2016) and strided convolutions along with ELU (Clevert et al., 2016) non-linearities and Weight Normaliza- | [moshi pp.9-10] | |
| 2 | The authors incorporate semantic information by distilling non‑causal embeddings from WavLM into a single vector quantizer that produces semantic tokens, which are then combined with separate acoustic tokens for reconstruction. | During training (blue part, top), we distill noncausal embeddings from WavLM (Chen et al., 2022) into a single vector quantizer which produces semantic tokens, and is combined with separate acoustic tokens for reconstruction. | [moshi pp.9-10] | |

**Agree with grade?** 

---

## Q04 (number_table): grade `wrong`
**Q:** According to the model hyperparameters table, how many layers and attention heads does the Moshi Depth Transformer use during training?

**Reference answer:** 16 attention heads and 6 layers (Table 1).

**Status:** answered · grader: missing key facts: ['16', '6']

**Reply:**

> The Moshi Depth Transformer uses six layers and sixteen attention heads during training. [moshi pp.13-14]

| # | Claim | Quote (verbatim, checked) | Source | Supported? |
|---|---|---|---|---|
| 1 | The Moshi Depth Transformer uses six layers and sixteen attention heads during training. | the Depth Transformer used for Moshi has 6 layers, a dimension of 1024, and 16 attention heads. | [moshi pp.13-14] | |

**Agree with grade?** 

---

## Q05 (body_fact): grade `correct`
**Q:** What are the three criteria the authors use to compare self-attention with recurrent and convolutional layers?

**Reference answer:** Total computational complexity per layer, the amount of computation that can be parallelized (minimum number of sequential operations), and the path length between long-range dependencies.

**Status:** answered · grader: all key facts, gold page cited

**Reply:**

> The authors compare self‑attention with recurrent and convolutional layers using three criteria: total computational complexity per layer, the amount of computation that can be parallelized (minimum number of sequential operations), and the path length between long‑range dependencies in the network. [attention p.6]

| # | Claim | Quote (verbatim, checked) | Source | Supported? |
|---|---|---|---|---|
| 1 | The authors compare self‑attention with recurrent and convolutional layers using three criteria: total computational complexity per layer, the amount of computation that can be parallelized (minimum number of sequential operations), and the path length between long‑range dependencies in the network. | One is the total computational complexity per layer. Another is the amount of computation that can be parallelized, as measured by the minimum number of sequential operations required. The third is the path length between long-range dependencies in the network. | [attention p.6] | |

**Agree with grade?** 

---

## Q06 (body_fact): grade `wrong`
**Q:** Why do the authors use multiple attention heads instead of a single attention head?

**Reference answer:** Multiple heads let the model jointly attend to information from different representation subspaces at different positions; with a single head, averaging inhibits this.

**Status:** answered · grader: missing key facts: ['averaging']

**Reply:**

> The authors use multiple attention heads so that the model can jointly attend to information from different representation subspaces at different positions, whereas a single attention head would average these signals and inhibit such diversity. [attention pp.4-5]

| # | Claim | Quote (verbatim, checked) | Source | Supported? |
|---|---|---|---|---|
| 1 | The authors use multiple attention heads so that the model can jointly attend to information from different representation subspaces at different positions, whereas a single attention head would average these signals and inhibit such diversity. | Multi-head attention allows the model to jointly attend to information from different representation subspaces at different positions. With a single attention head, averaging inhibits this. | [attention pp.4-5] | |

**Agree with grade?** 

---

## Q07 (body_fact): grade `wrong`
**Q:** How does the Transformer represent token positions despite having neither recurrence nor convolution?

**Reference answer:** It adds positional encodings (same dimension as the embeddings) to the input embeddings at the bottom of the encoder and decoder stacks, using sine and cosine functions of different frequencies, which the authors hypothesise helps the model attend by relative positions.

**Status:** answered · grader: missing key facts: ['sine | sinusoid | sinusoidal', 'relative positions']

**Reply:**

> The Transformer represents token positions by adding positional encodings to the input embeddings. [attention p.6]

| # | Claim | Quote (verbatim, checked) | Source | Supported? |
|---|---|---|---|---|
| 1 | The Transformer represents token positions by adding positional encodings to the input embeddings. | we add "positional encodings" to the input embeddings at the bottoms of the encoder and decoder stacks. | [attention p.6] | |

**Agree with grade?** 

---

## Q08 (body_fact): grade `correct`
**Q:** What are the three main processing stages in the H-Net architecture, and what happens to the representation between them?

**Reference answer:** A small encoder processes the raw data; the result is downsampled and passed through a main network operating on compressed chunks; it is then upsampled and passed through a decoder operating at the original resolution. Outer stages capture fine-grained patterns, inner stages coarser ones.

**Status:** answered · grader: all key facts, gold page cited

**Reply:**

> The three main processing stages in the H‑Net architecture are the encoder network, the main network, and the decoder network. [hnet pp.4-5] Between the encoder and the main network the input sequence is progressively compressed, producing a shorter representation that the main network processes. [hnet pp.5-6] After the main network, the representation is decompressed by the decoder network to restore the original sequence length for final output. [hnet pp.4-5]

| # | Claim | Quote (verbatim, checked) | Source | Supported? |
|---|---|---|---|---|
| 1 | The three main processing stages in the H‑Net architecture are the encoder network, the main network, and the decoder network. | H-Net employs a hierarchical architecture comprising three primary components – encoder networks (E), main network (M), and decoder networks (D) – where each component is implemented with a stack of sequence mixing layers | [hnet pp.4-5] | |
| 2 | Between the encoder and the main network the input sequence is progressively compressed, producing a shorter representation that the main network processes. | After 𝑆 stages of compression, the main network receives sequences where 𝐿𝑆 ≪ 𝐿0, enabling much larger networks within the same computational budget | [hnet pp.5-6] | |
| 3 | After the main network, the representation is decompressed by the decoder network to restore the original sequence length for final output. | H-Net employs a hierarchical architecture comprising three primary components – encoder networks (E), main network (M), and decoder networks (D) – where each component is implemented with a stack of sequence mixing layers | [hnet pp.4-5] | |

**Agree with grade?** 

---

## Q09 (body_fact): grade `wrong`
**Q:** How does H-Net's routing module estimate whether a boundary should be placed between two adjacent representations?

**Reference answer:** It projects adjacent encoder outputs into a query and a key, scales the cosine similarity between the current query and the previous key into a boundary probability, and sets a boundary when the probability is at least 0.5. The first position has probability 1.0 by definition.

**Status:** answered · grader: missing key facts: ['0.5', '1.0']

**Reply:**

> H‑Net’s routing module estimates a boundary by computing the cosine similarity between adjacent encoder outputs and converting that similarity into a boundary probability. [hnet p.6]

| # | Claim | Quote (verbatim, checked) | Source | Supported? |
|---|---|---|---|---|
| 1 | H‑Net’s routing module estimates a boundary by computing the cosine similarity between adjacent encoder outputs and converting that similarity into a boundary probability. | the routing module implements this intuition through cosine similarity between adjacent encoder outputs. Given encoder outputs ˆX, it calculates boundary probabilities pt and boundary indicators bt as follows: | [hnet p.6] | |

**Agree with grade?** 

---

## Q10 (appendix): grade `wrong`
**Q:** In the appendix's comparison of downsampling methods, which downsampling strategy do the authors use in the H-Net chunking layer, and what is the basic selection rule?

**Reference answer:** Direct selection of boundary-marked vectors: vectors whose boundary indicator is 1 are kept and the rest are discarded. Appendix E.1 compares it with max/mean pooling and cross-attention.

**Status:** answered · grader: missing key facts: ['boundary', 'mean pooling', 'cross-attention']

**Reply:**

> The authors use the default Downsample operation of H‑Net in the chunking layer. [hnet p.36]

| # | Claim | Quote (verbatim, checked) | Source | Supported? |
|---|---|---|---|---|
| 1 | The authors use the default Downsample operation of H‑Net in the chunking layer. | the default Downsample operation of H‑Net (see Section 2.2.1) | [hnet p.36] | |

**Agree with grade?** 

---

## Q11 (multi_part): grade `correct`
**Q:** How does H-Net preserve autoregressive causality during both training and inference, and what state does its routing module need to retain during inference?

**Reference answer:** In training it uses causal masking in all sequence-mixing layers; boundary probabilities depend only on the current and previous representations, and the smoothing module's recursive form depends only on past compressed representations. At inference the routing module keeps the key value of the most recently processed token.

**Status:** answered · grader: all key facts, gold page cited

**Reply:**

> H‑Net preserves autoregressive causality by using standard causal masking during training and by designing its dynamic chunking, routing, and smoothing modules with recursive formulations that depend only on past tokens, ensuring no future information leaks. [hnet pp.9-10] During inference, the routing module must retain the key and value of the most recent token processed to compute the boundary probability for the next token. [hnet p.10]

| # | Claim | Quote (verbatim, checked) | Source | Supported? |
|---|---|---|---|---|
| 1 | H‑Net preserves autoregressive causality by using standard causal masking during training and by designing its dynamic chunking, routing, and smoothing modules with recursive formulations that depend only on past tokens, ensuring no future information leaks. | During training, H‑Net employs standard causal masking across all sequence mixing layers. DC maintains causality by computing boundary probabilities based only on current and previous representations. Specifically, the boundary probability 𝑝𝑡 depends on 𝑞𝑡 and 𝑘𝑡 from the current and previous positions (equation (4)), ensuring no information leakage from future tokens. The smoothing module similarly maintains causality through its recursive formulation (equation (5)), where each output depends only on past compressed representations. | [hnet pp.9-10] | |
| 2 | During inference, the routing module must retain the key and value of the most recent token processed to compute the boundary probability for the next token. | (a) Routing Module: In order to compute 𝑝𝑡, we need 𝑘𝑡−1 (see equation (4)), so our state consists of the key value of the most recent token processed. | [hnet p.10] | |

**Agree with grade?** 

---

## Q12 (multi_part): grade `wrong`
**Q:** How do the two papers handle sequence structure differently: how does the Transformer represent token order, and how does H-Net determine the boundaries of its chunks?

**Reference answer:** The Transformer adds fixed sinusoidal positional encodings to its input embeddings. H-Net learns content- and context-dependent chunk boundaries from data, with a routing module that uses the cosine similarity of adjacent representations.

**Status:** answered · grader: missing key facts: ['cosine similarity', 'context-dependent']

**Reply:**

> The Transformer represents token order by adding sinusoidal positional encodings to the input embeddings, allowing the model to learn relative positions through linear combinations of sine and cosine functions. [attention p.6] H‑Net determines chunk boundaries by learning them end‑to‑end, achieving boundary prediction accuracy above 99.5% and discovering semantically coherent units without explicit supervision. [hnet p.39]

| # | Claim | Quote (verbatim, checked) | Source | Supported? |
|---|---|---|---|---|
| 1 | The Transformer represents token order by adding sinusoidal positional encodings to the input embeddings, allowing the model to learn relative positions through linear combinations of sine and cosine functions. | Since our model contains no recurrence and no convolution, in order for the model to make use of the order of the sequence, we must inject some information about the relative or absolute position of the tokens in the sequence. To this end, we add "positional encodings" to the input embeddings at the bottoms of the encoder and decoder stacks. | [attention p.6] | |
| 2 | H‑Net determines chunk boundaries by learning them end‑to‑end, achieving boundary prediction accuracy above 99.5% and discovering semantically coherent units without explicit supervision. | Remark. One might ask if our distilled model has simply learned to tokenize on spaces (since spaces are always the start of a new token). It has not. Simply tokenizing on spaces would yield a sub‑95% boundary prediction accuracy; however, our distilled model gets boundary prediction accuracy above 99.5%. | [hnet p.39] | |

**Agree with grade?** 

---

## Q13 (unanswerable_near_miss): grade `refused_correctly`
**Q:** What exact accuracy does Moshi achieve on a benchmark for recognizing emotions such as happiness, sadness, and anger from speech?

**Reference answer:** Refuse. Moshi discusses keeping non-linguistic information such as emotion (pp.1, 2, 6) but reports no emotion-recognition benchmark or accuracy.

**Status:** not_in_papers · grader: refused (not_in_papers)

**Reply:**

> The three papers don't say this, so I won't guess.

**Agree with grade?** 

---

## Q14 (unanswerable_near_miss): grade `refused_correctly`
**Q:** How many gigabytes of GPU memory does the Transformer require to train on the WMT 2014 English-to-German dataset?

**Reference answer:** Refuse. The paper gives the hardware (8 NVIDIA P100 GPUs) and training time, but no memory requirement in gigabytes.

**Status:** not_in_papers · grader: refused (not_in_papers)

**Reply:**

> The three papers don't say this, so I won't guess.

**Agree with grade?** 

---

## Q15 (unanswerable_near_miss): grade `refused_correctly`
**Q:** What is the measured end-to-end speech-generation latency of H-Net when generating spoken dialogue in real time?

**Reference answer:** Refuse. H-Net is evaluated on text, code, Chinese and DNA; it reports no speech-generation or real-time dialogue latency.

**Status:** not_in_papers · grader: refused (not_in_papers)

**Reply:**

> The three papers don't say this, so I won't guess.

**Agree with grade?** 

---

## Q16 (unanswerable_near_miss): grade `refused_correctly`
**Q:** What video frame rate does Moshi use when processing live video alongside speech during a conversation?

**Reference answer:** Refuse. Moshi has no video input. Its only 'frame rate' is the 12.5 Hz audio codec frame rate, which is not a video frame rate.

**Status:** not_in_papers · grader: refused (not_in_papers)

**Reply:**

> The three papers don't say this, so I won't guess.

**Agree with grade?** 

---

## Q17 (unanswerable_off_topic): grade `refused_correctly`
**Q:** What is the time complexity of Dijkstra's shortest-path algorithm when implemented using an adjacency list and a binary heap?

**Reference answer:** Refuse: none of the three papers covers this.

**Status:** not_in_papers · grader: refused (not_in_papers)

**Reply:**

> The three papers don't say this, so I won't guess.

**Agree with grade?** 

---

## Q18 (false_premise): grade `wrong`
**Q:** Which convolutional layers does the Transformer use to extract local features before applying self-attention?

**Reference answer:** The premise is false: the Transformer is based solely on attention mechanisms and dispenses with recurrence and convolutions entirely, so there are no convolutional feature-extraction layers to name.

**Status:** not_in_papers · grader: refused without challenging the premise

**Reply:**

> The three papers don't say this, so I won't guess.

**Agree with grade?** 

---
