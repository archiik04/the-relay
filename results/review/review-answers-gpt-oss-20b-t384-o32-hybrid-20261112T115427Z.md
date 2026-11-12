# Hand review: answers-gpt-oss-20b-t384-o32-hybrid-20261112T115427Z.jsonl

Fill in **supported?** (yes/no) for every claim, and **agree with grade?** for every answer.
A claim is supported only if its quote directly states it (P1).

## Q01 (body_fact): grade `correct`
**Q:** What is the purpose of the Inner Monologue approach in Moshi, and how does it combine text and speech generation?

**Reference answer:** It improves the factuality and linguistic quality of the generated speech by having Moshi predict time-aligned text tokens before the audio tokens.

**Status:** answered · grader: all key facts, gold page cited

**Reply:**

> The Inner Monologue approach in Moshi is designed to improve the linguistic quality of generated speech by modeling the textual representation of the system’s own speech as a prefix to the audio tokens. It combines text and speech generation by first predicting a sequence of text tokens, then using those tokens as a prefix for generating semantic and acoustic tokens in a hierarchical, per‑frame manner, enabling real‑time, streaming inference.
> 
> Sources: [moshi pp.15-16] [moshi p.5]

| # | Claim | Quote (verbatim, checked) | Source | Supported? |
|---|---|---|---|---|
| 1 | Inner Monologue is designed to improve the linguistic quality of generated speech by modeling the textual representation of the system’s own speech as a prefix to the audio tokens | we observe that having Moshi also model the textual representation of its own speech is providing a scaffolding that increases the linguistic quality of its generation. | [moshi pp.15-16] | |
| 2 | It combines text and speech generation by first predicting a sequence of text tokens, then using those tokens as a prefix for generating semantic and acoustic tokens in a hierarchical, per‑frame manner | Inner Monologue decomposes speech into a chain of text, semantic and acoustic tokens, and predicts this structured sequence in a hierarchical manner. | [moshi p.5] | |

**Agree with grade?** 

---

## Q02 (body_fact): grade `wrong`
**Q:** How does Moshi's multi-stream architecture handle simultaneous user input and generated speech without explicitly modelling speaker turns?

**Reference answer:** It models the user's audio and Moshi's own audio jointly as two autoregressive token streams, which removes the concept of a speaker turn and lets it learn overlap and interruptions.

**Status:** answered · grader: missing key facts: ['token streams', 'speaker turn', 'interruptions']

**Reply:**

> Moshi’s multi‑stream design lets the model process the user’s audio and its own generated audio in parallel, without needing explicit speaker‑turn boundaries. The Depth Transformer predicts tokens for both streams simultaneously, and the model can output silence for its own stream while the user speaks, or vice versa, allowing overlapping speech. This is achieved by treating the user and Moshi streams as separate audio inputs that are jointly modeled, so the system can speak and listen at the same time without explicit turn markers.
> 
> Sources: [moshi pp.14-15] [moshi p.17]

| # | Claim | Quote (verbatim, checked) | Source | Supported? |
|---|---|---|---|---|
| 1 | Moshi’s multi‑stream design lets the model process the user’s audio and its own generated audio in parallel, without needing explicit speaker‑turn boundaries. | Our framework can be extended to modeling a two‑speaker conversation: given two streams of audios | [moshi pp.14-15] | |
| 2 | The Depth Transformer predicts tokens for both streams simultaneously, and the model can output silence for its own stream while the user speaks, or vice versa, allowing overlapping speech. | Interestingly, there is no explicit boundaries for the change of turns between the user and Moshi: Moshi can speak and listen at all time, and do both at once if needed. | [moshi p.17] | |

**Agree with grade?** 

---

## Q03 (body_fact): grade `wrong`
**Q:** How does Mimi encode audio, and what technique do the authors use to incorporate semantic information into its acoustic representation?

**Reference answer:** Mimi turns audio into discrete tokens with residual vector quantization, and distils semantic information into the first level of those acoustic tokens.

**Status:** answered · grader: missing key facts: ['residual vector quantization', 'first level']

**Reply:**

> Mimi encodes audio by passing a single‑channel waveform through a SeaNet autoencoder that cascades residual convolutional blocks with dilated and strided convolutions, ELU activations and weight‑normalised layers, producing a latent representation that is then discretised by a split residual vector quantiser. To embed semantic information, the authors distil non‑causal embeddings from WavLM into a semantic token stream that is combined with the acoustic tokens, enabling a causal, streaming representation that still carries linguistic content.
> 
> Sources: [moshi pp.9-10] [moshi p.9]

| # | Claim | Quote (verbatim, checked) | Source | Supported? |
|---|---|---|---|---|
| 1 | Mimi encodes audio by passing a single‑channel waveform through a SeaNet autoencoder that cascades residual convolutional blocks with dilated and strided convolutions, ELU activations and weight‑normalised layers, producing a latent representation that is then discretised by a split residual vector quantiser. | The encoder projects a single‑channel waveform x ∈ ℝL to a latent representation enc(x) ∈ ℝS×D by cascading residual convolutional blocks that interleave dilated (van den Oord et al., 2016) and strided convolutions along with ELU (Clevert et al., 2016) non‑linearities and Weight Normaliza- | [moshi pp.9-10] | |
| 2 | To embed semantic information, the authors distil non‑causal embeddings from WavLM into a semantic token stream that is combined with the acoustic tokens. | Mimi uses distillation to transfer non‑causal, high‑level semantic information into the tokens produced by a causal model, allowing for streaming encoding and decoding of semantic‑acoustic tokens. | [moshi p.9] | |

**Agree with grade?** 

---

## Q04 (number_table): grade `correct`
**Q:** According to the model hyperparameters table, how many layers and attention heads does the Moshi Depth Transformer use during training?

**Reference answer:** 16 attention heads and 6 layers (Table 1).

**Status:** answered · grader: all key facts, gold page cited

**Reply:**

> The Moshi Depth Transformer used during training has 6 layers and 16 attention heads.
> 
> Sources: [moshi pp.13-14]

| # | Claim | Quote (verbatim, checked) | Source | Supported? |
|---|---|---|---|---|
| 1 | The Moshi Depth Transformer has 6 layers and 16 attention heads | the Depth Transformer used for Moshi has 6 layers, a dimension of 1024, and 16 attention heads | [moshi pp.13-14] | |

**Agree with grade?** 

---

## Q05 (body_fact): grade `correct`
**Q:** What are the three criteria the authors use to compare self-attention with recurrent and convolutional layers?

**Reference answer:** Total computational complexity per layer, the amount of computation that can be parallelized (minimum number of sequential operations), and the path length between long-range dependencies.

**Status:** answered · grader: all key facts, gold page cited

**Reply:**

> The authors compare self‑attention with recurrent and convolutional layers using three criteria: (1) total computational complexity per layer, (2) the amount of computation that can be parallelized, measured by the minimum number of sequential operations, and (3) the path length between long‑range dependencies in the network.
> 
> Sources: [attention p.6]

| # | Claim | Quote (verbatim, checked) | Source | Supported? |
|---|---|---|---|---|
| 1 | total computational complexity per layer | One is the total computational complexity per layer. | [attention p.6] | |
| 2 | amount of computation that can be parallelized, measured by the minimum number of sequential operations | Another is the amount of computation that can be parallelized, as measured by the minimum number of sequential operations required. | [attention p.6] | |
| 3 | path length between long‑range dependencies in the network | The third is the path length between long-range dependencies in the network. | [attention p.6] | |

**Agree with grade?** 

---

## Q06 (body_fact): grade `correct`
**Q:** Why do the authors use multiple attention heads instead of a single attention head?

**Reference answer:** Multiple heads let the model jointly attend to information from different representation subspaces at different positions; with a single head, averaging inhibits this.

**Status:** answered · grader: all key facts, gold page cited

**Reply:**

> The authors use multiple attention heads so that the model can jointly attend to information from different representation subspaces at different positions; a single attention head would average these signals and inhibit such diversity.
> 
> Sources: [attention pp.4-5]

| # | Claim | Quote (verbatim, checked) | Source | Supported? |
|---|---|---|---|---|
| 1 | Multi-head attention allows the model to jointly attend to information from different representation subspaces at different positions. With a single attention head, averaging inhibits this. | Multi-head attention allows the model to jointly attend to information from different representation subspaces at different positions. With a single attention head, averaging inhibits this. | [attention pp.4-5] | |

**Agree with grade?** 

---

## Q07 (body_fact): grade `correct`
**Q:** How does the Transformer represent token positions despite having neither recurrence nor convolution?

**Reference answer:** It adds positional encodings (same dimension as the embeddings) to the input embeddings at the bottom of the encoder and decoder stacks, using sine and cosine functions of different frequencies, which the authors hypothesise helps the model attend by relative positions.

**Status:** answered · grader: all key facts, gold page cited

**Reply:**

> The Transformer injects positional information by adding positional encodings to the input embeddings, since it has no recurrence or convolution to provide order. The encodings are sinusoidal functions of position and dimension, summed with the token embeddings. This allows the model to learn relative positions and even extrapolate to longer sequences.
> 
> Sources: [attention p.6]

| # | Claim | Quote (verbatim, checked) | Source | Supported? |
|---|---|---|---|---|
| 1 | The Transformer injects positional information by adding positional encodings to the input embeddings | we add "positional encodings" to the input embeddings at the bottoms of the encoder and decoder stacks. | [attention p.6] | |
| 2 | The encodings are sinusoidal functions of position and dimension | we use sine and cosine functions of different frequencies: PE(pos,2i) = sin(pos/100002i/dmodel) PE(pos,2i+1) = cos(pos/100002i/dmodel) | [attention p.6] | |

**Agree with grade?** 

---

## Q08 (body_fact): grade `correct`
**Q:** What are the three main processing stages in the H-Net architecture, and what happens to the representation between them?

**Reference answer:** A small encoder processes the raw data; the result is downsampled and passed through a main network operating on compressed chunks; it is then upsampled and passed through a decoder operating at the original resolution. Outer stages capture fine-grained patterns, inner stages coarser ones.

**Status:** answered · grader: all key facts, gold page cited

**Reply:**

> The H‑Net architecture consists of three main processing stages: an encoder network, a main network, and a decoder network. Between the encoder and the main network the input sequence is progressively compressed, producing a shorter representation that the main network processes. After the main network, the representation is expanded back to its original length by the decoder network.
> 
> Sources: [hnet pp.4-5] [hnet pp.5-6]

| # | Claim | Quote (verbatim, checked) | Source | Supported? |
|---|---|---|---|---|
| 1 | The H‑Net architecture consists of an encoder network, a main network, and a decoder network. | H-Net employs a hierarchical architecture comprising three primary components – encoder networks (E), main network (M), and decoder networks (D) – | [hnet pp.4-5] | |
| 2 | Between the encoder and the main network the input sequence is progressively compressed, producing a shorter representation that the main network processes. | After 𝑆 stages of compression, the main network receives sequences where 𝐿𝑆 ≪ 𝐿0, enabling much larger networks within the same computational budget. | [hnet pp.5-6] | |

**Agree with grade?** 

---

## Q09 (body_fact): grade `wrong`
**Q:** How does H-Net's routing module estimate whether a boundary should be placed between two adjacent representations?

**Reference answer:** It projects adjacent encoder outputs into a query and a key, scales the cosine similarity between the current query and the previous key into a boundary probability, and sets a boundary when the probability is at least 0.5. The first position has probability 1.0 by definition.

**Status:** answered · grader: missing key facts: ['0.5', '1.0']

**Reply:**

> H‑Net’s routing module estimates a boundary by computing the cosine similarity between adjacent encoder outputs and converting that similarity into a boundary probability. When the similarity is low—indicating a semantic shift—the probability rises, signalling a boundary should be placed.
> 
> Sources: [hnet p.6]

| # | Claim | Quote (verbatim, checked) | Source | Supported? |
|---|---|---|---|---|
| 1 | The routing module estimates a boundary by computing the cosine similarity between adjacent encoder outputs and converting that similarity into a boundary probability. | The routing module implements this intuition through cosine similarity between adjacent encoder outputs. Given encoder outputs ˆ𝑋, it calculates boundary probabilities 𝑝𝑡 and boundary indicators 𝑏𝑡 as follows: | [hnet p.6] | |

**Agree with grade?** 

---

## Q10 (appendix): grade `wrong`
**Q:** In the appendix's comparison of downsampling methods, which downsampling strategy do the authors use in the H-Net chunking layer, and what is the basic selection rule?

**Reference answer:** Direct selection of boundary-marked vectors: vectors whose boundary indicator is 1 are kept and the rest are discarded. Appendix E.1 compares it with max/mean pooling and cross-attention.

**Status:** answered · grader: missing key facts: ['mean pooling', 'cross-attention']

**Reply:**

> The authors use the default Downsample operation in the H‑Net chunking layer. The basic selection rule keeps only the vectors whose boundary flag 𝑏𝑡 equals 1 and discards those with 𝑏𝑡 equal to 0.
> 
> Sources: [hnet p.36]

| # | Claim | Quote (verbatim, checked) | Source | Supported? |
|---|---|---|---|---|
| 1 | The authors use the default Downsample operation of H‑Net in the chunking layer | the default Downsample operation of H-Net (see Section 2.2.1) | [hnet p.36] | |

**Agree with grade?** 

---

## Q11 (multi_part): grade `correct`
**Q:** How does H-Net preserve autoregressive causality during both training and inference, and what state does its routing module need to retain during inference?

**Reference answer:** In training it uses causal masking in all sequence-mixing layers; boundary probabilities depend only on the current and previous representations, and the smoothing module's recursive form depends only on past compressed representations. At inference the routing module keeps the key value of the most recently processed token.

**Status:** answered · grader: all key facts, gold page cited

**Reply:**

> H‑Net preserves autoregressive causality by using causal masking during training and by designing its dynamic chunking (DC) modules with recursive formulations that depend only on past tokens. During inference, the routing module must retain the key‑value pair of the most recent token processed.
> 
> Sources: [hnet pp.9-10] [hnet p.10]

| # | Claim | Quote (verbatim, checked) | Source | Supported? |
|---|---|---|---|---|
| 1 | H‑Net preserves autoregressive properties essential for language modeling | Every component of H-Net (i.e., encoder-, decoder-, main- networks, and the dynamic chunking mechanism) is carefully designed to preserve autoregressive properties essential for language modeling. | [hnet pp.9-10] | |
| 2 | DC maintains causality by computing boundary probabilities based only on current and previous representations | DC maintains causality by computing boundary probabilities based only on current and previous representations. | [hnet pp.9-10] | |
| 3 | The routing module state consists of the key value of the most recent token processed | In order to compute 𝑝𝑡, we need 𝑘𝑡−1 (see equation (4)), so our state consists of the key value of the most recent token processed. | [hnet p.10] | |

**Agree with grade?** 

---

## Q12 (multi_part): grade `wrong`
**Q:** How do the two papers handle sequence structure differently: how does the Transformer represent token order, and how does H-Net determine the boundaries of its chunks?

**Reference answer:** The Transformer adds fixed sinusoidal positional encodings to its input embeddings. H-Net learns content- and context-dependent chunk boundaries from data, with a routing module that uses the cosine similarity of adjacent representations.

**Status:** answered · grader: missing key facts: ['cosine similarity', 'context-dependent']

**Reply:**

> The Transformer encodes token order by adding sinusoidal positional encodings to the input embeddings, giving each position a unique vector that the model can use to infer relative positions. H‑Net, on the other hand, learns to segment the raw input into chunks by predicting token boundaries, achieving high boundary‑prediction accuracy without relying on explicit tokenization.
> 
> Sources: [attention p.6] [hnet p.39]

| # | Claim | Quote (verbatim, checked) | Source | Supported? |
|---|---|---|---|---|
| 1 | The Transformer encodes token order by adding sinusoidal positional encodings to the input embeddings | we add "positional encodings" to the input embeddings at the bottoms of the encoder and decoder stacks. The positional encodings have the same dimension dmodel as the embeddings, so that the two can be summed. | [attention p.6] | |
| 2 | H‑Net learns to segment the raw input into chunks by predicting token boundaries | the H-Net does use the main network, it is not able to exactly match the behavior of the original tokenized model. Instead, it is finding slightly different representations of tokens to use in the main stage. | [hnet p.39] | |

**Agree with grade?** 

---

## Q13 (unanswerable_near_miss): grade `refused_correctly`
**Q:** What exact accuracy does Moshi achieve on a benchmark for recognizing emotions such as happiness, sadness, and anger from speech?

**Reference answer:** Refuse. Moshi discusses keeping non-linguistic information such as emotion (pp.1, 2, 6) but reports no emotion-recognition benchmark or accuracy.

**Status:** not_in_papers · grader: refused (not_in_papers)

**Reply:**

> The papers do not report an accuracy for Moshi on a benchmark for recognizing emotions such as happiness, sadness, and anger from speech.

**Agree with grade?** 

---

## Q14 (unanswerable_near_miss): grade `refused_correctly`
**Q:** How many gigabytes of GPU memory does the Transformer require to train on the WMT 2014 English-to-German dataset?

**Reference answer:** Refuse. The paper gives the hardware (8 NVIDIA P100 GPUs) and training time, but no memory requirement in gigabytes.

**Status:** not_in_papers · grader: refused (not_in_papers)

**Reply:**

> The papers do not specify the amount of GPU memory required to train the Transformer on the WMT 2014 English-to-German dataset.

**Agree with grade?** 

---

## Q15 (unanswerable_near_miss): grade `refused_correctly`
**Q:** What is the measured end-to-end speech-generation latency of H-Net when generating spoken dialogue in real time?

**Reference answer:** Refuse. H-Net is evaluated on text, code, Chinese and DNA; it reports no speech-generation or real-time dialogue latency.

**Status:** not_in_papers · grader: refused (not_in_papers)

**Reply:**

> The papers do not provide a measured end‑to‑end speech‑generation latency for H‑Net when generating spoken dialogue in real time.

**Agree with grade?** 

---

## Q16 (unanswerable_near_miss): grade `refused_correctly`
**Q:** What video frame rate does Moshi use when processing live video alongside speech during a conversation?

**Reference answer:** Refuse. Moshi has no video input. Its only 'frame rate' is the 12.5 Hz audio codec frame rate, which is not a video frame rate.

**Status:** not_in_papers · grader: refused (not_in_papers)

**Reply:**

> The papers do not specify the video frame rate Moshi uses when processing live video alongside speech during a conversation.

**Agree with grade?** 

---

## Q17 (unanswerable_off_topic): grade `refused_correctly`
**Q:** What is the time complexity of Dijkstra's shortest-path algorithm when implemented using an adjacency list and a binary heap?

**Reference answer:** Refuse: none of the three papers covers this.

**Status:** not_in_papers · grader: refused (not_in_papers)

**Reply:**

> The papers do not discuss Dijkstra's algorithm or its time complexity.

**Agree with grade?** 

---

## Q18 (false_premise): grade `wrong`
**Q:** Which convolutional layers does the Transformer use to extract local features before applying self-attention?

**Reference answer:** The premise is false: the Transformer is based solely on attention mechanisms and dispenses with recurrence and convolutions entirely, so there are no convolutional feature-extraction layers to name.

**Status:** not_in_papers · grader: refused without challenging the premise

**Reply:**

> The papers do not state that the Transformer uses any convolutional layers to extract local features before applying self-attention.

**Agree with grade?** 

---
