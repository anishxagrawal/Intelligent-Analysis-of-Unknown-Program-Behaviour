# Intelligent Analysis of Unknown Program Behaviour
## Project Report — Full and Final System

---

### Document information

| Field | Value |
|---|---|
| Project title | Intelligent Analysis of Unknown Program Behaviour |
| Document type | Full project report (final scope) |
| Version | 1.0 |
| Status | Design and research reference; results section is a template to be filled after implementation |

> **How to use this document.** This report describes the *complete* system, not the two-week first version. Sections 1 to 8 are ready to read and study now. Section 9 (Results and Discussion) is written as a fill-in template, because inventing results before running experiments would be dishonest and would fall apart under questioning. Section 11 lists every source. **Verify each reference yourself before submitting** — check the author names, venue and year on the publisher site or on the authors' pages. Citation details are easy to get slightly wrong, and a wrong citation in a report is worse than a missing one.

---

## 1. Abstract

When you receive a program and you do not know what it does, you have a problem. Reading its code takes an expert many hours, and modern programs actively make themselves hard to read. This project builds a system that answers the question automatically: it runs the unknown program in a sealed environment, watches everything the program does, turns those observations into structured data, decides whether the behaviour is dangerous, and then writes a plain-language report that explains the decision with evidence attached.

The system combines four things that are usually separate: static inspection of the file, dynamic observation of the running program, machine learning over behaviour, and a language model that explains findings in readable English. The important design rule is that the language model never decides the verdict. It only explains a verdict that deterministic components already made, and every sentence it writes must point at the specific recorded events that support it. This keeps the output trustworthy and checkable, which is the main weakness of most recent attempts to attach language models to security tools.

---

## 2. Problem Statement

Security teams receive unknown executable files constantly — email attachments, downloads, files pulled off a suspect machine, samples shared by partners. Each one needs an answer to a simple question: **is this safe to run, and if not, what does it do?**

Answering that question today has three bad options.

**Option one: manual reverse engineering.** An analyst opens the file in a disassembler and reads it. This gives the deepest answer and is completely unscalable. It takes hours to days per sample, needs rare expertise, and modern packing and obfuscation are specifically designed to make it slower.

**Option two: signature scanning.** An antivirus engine checks the file against a list of known-bad patterns. This is instant and useless against anything new. A one-byte change to a known sample produces a new file that the signature misses.

**Option three: an existing sandbox.** Run the file in a virtual machine and record what happens. This works and is the right basic idea. But existing sandboxes have practical problems that this project targets:

- They produce **enormous raw output** — tens of thousands of events per run — and leave the human to interpret it. The bottleneck moves from analysis to reading.
- They frequently produce a result of "no suspicious behaviour observed," which the tool and the user then quietly treat as "safe." Very often it actually means the malware detected the sandbox and did nothing on purpose. **This confusion is a serious source of false negatives**, and it happens most on the samples that matter most, because sophisticated attackers are the ones who bother with evasion.
- Their machine-learning components are often evaluated in ways that make the numbers look far better than real-world performance.
- Where language models have been added recently, they are usually asked to *decide*, not just explain, which makes the output unverifiable.

**The problem this project solves:** build an automated system that analyses an unknown program end to end, produces a verdict that is explainable and auditable, states honestly when it could not observe anything, and presents its findings in language a non-expert can act on.

---

## 3. Introduction

### 3.1 Background in plain terms

A program is a set of instructions. You cannot tell what those instructions do by looking at the file, any more than you can tell what a sealed machine does by looking at the box. There are two ways to find out.

**Static analysis** means examining the file without running it. You can read its header, see which system functions it plans to call, extract readable text from it, and measure how random its contents look. High randomness usually means the real content is compressed or encrypted, which is what packers do. Static analysis is fast, completely safe, and works even on a file that refuses to run. Its weakness is that a packed file hides almost everything until it unpacks itself in memory.

**Dynamic analysis** means actually running the program and watching it. This defeats packing, because the program must unpack itself in order to work. Its weakness is that you only see what happens during that run, in that environment, on that day. If the program needs a command-line argument you did not give it, or waits for a date that has not arrived, or checks whether it is inside a virtual machine, you see nothing.

Neither approach is sufficient alone. The system uses both.

### 3.2 Why this is hard

Three difficulties make this an interesting engineering problem rather than a plumbing exercise.

**Volume.** Watching every system call a program makes produces a flood of data. A single minute of execution can generate hundreds of thousands of events. Most are completely ordinary. Finding the handful that matter is a data problem before it is a security problem.

**Adversarial behaviour.** This is the key difference from most machine learning applications. If you build a system to recognise cats, cats do not read your paper and change their appearance. Malware authors do. They test their creations against public sandboxes and modify them until they pass. Any assumption you make becomes something to attack. This means techniques that work well in a paper can decay quickly in deployment.

**Interpretation.** Almost every individual action malware takes is also something legitimate software does. Installers write to system directories. Backup tools read many files quickly. Update services contact servers. Nothing is suspicious in isolation. Malicious meaning lives in the *combination and sequence* of actions, which is why the system reasons over behaviour graphs and sequences rather than over individual events.

### 3.3 What the system produces

For each submitted file, the system outputs a report containing:

- A verdict (malicious / suspicious / clean / not determined) with a confidence value
- A risk score
- A timeline of what the program did, in order
- A behaviour graph showing processes, files, registry keys and network destinations, and how they connect
- A mapping to MITRE ATT&CK techniques, where each technique is linked to the specific events that justify it
- Indicators of compromise: hashes, IP addresses, domains, file paths, registry keys
- A plain-language explanation of the reasoning
- A run-outcome state saying honestly what happened during execution
- A provenance stamp recording which sandbox image, rule set, model version and configuration produced the result

---

## 4. Objectives

### 4.1 Primary objectives

1. **Build a working automated pipeline** that takes an unknown binary and returns a structured verdict report without human intervention.

2. **Combine static and dynamic evidence** in one feature set, so that packed files still produce useful signal and non-running files still produce some answer.

3. **Make every verdict explainable.** Each conclusion must be traceable to specific recorded events. No claim appears in a report without evidence behind it.

4. **Report absence of evidence honestly.** Distinguish between "we ran it and it did nothing harmful," "it crashed," "it timed out," "it produced no activity at all," and "we believe it detected the sandbox." These must never collapse into one category.

5. **Map behaviour to MITRE ATT&CK** so findings connect to a shared industry vocabulary rather than to project-specific labels.

6. **Use a language model safely** — for explanation only, constrained to a strict output format, required to cite event identifiers, and never permitted to set the verdict field.

7. **Evaluate honestly**, using a time-aware split and reporting false-positive rate as a headline metric, not just accuracy.

### 4.2 Secondary objectives

8. Handle basic evasion: detect and skip long sleeps, simulate user activity, mask obvious virtual-machine artifacts, and re-run under different configurations when the first run produces nothing.

9. Provide behavioural similarity search so a new sample can be compared against everything analysed before.

10. Keep the analysis platform itself secure — the system stores and executes live malware, so containment, access control and safe handling are part of the design, not an add-on.

11. Support a review loop where analyst corrections build a labelled dataset, with retraining as a deliberate reviewed step rather than an automatic loop.

### 4.3 Measurable success criteria

| Objective | How it is measured |
|---|---|
| Pipeline works | Percentage of submitted samples reaching a terminal state without operator help |
| Detection quality | Precision, recall, F1, and false-positive rate on a held-out, time-separated test set |
| Explainability | Percentage of report claims that carry at least one linked event identifier (target: 100%) |
| Honest reporting | Run-outcome states are distinct in the database and in every dashboard count |
| Throughput | Samples analysed per hour on the available hardware |
| Robustness | Percentage of runs where evasion is detected and re-detonation is triggered |

---

## 5. Literature Survey

This section groups prior work by topic. For each group it states what was learned and what it means for this project.

### 5.1 Automated dynamic analysis and sandboxes

The idea of running malware in an instrumented environment and recording behaviour goes back to the mid-2000s. **CWSandbox** [1] was one of the first systems to automate the whole loop — execute the sample, hook Windows API calls, and produce a structured behaviour report instead of a raw log. It established the basic shape that most later systems follow.

**Bayer et al.** [2] took this further by showing that behaviour reports could be turned into a form suitable for clustering, allowing large collections of samples to be grouped into families automatically. Their contribution matters here because it demonstrates that behaviour can be *represented* as data — a vector or a graph — and not just read as text. This is the foundation of the behaviour-representation stage in this project.

Two surveys map the whole field. **Egele et al.** [3] is the standard reference on dynamic analysis techniques and tools, covering how monitoring is implemented and what each approach costs. **Or-Meir et al.** [4] updates that picture for the modern era, including the shift toward machine learning and the growth of evasion.

On the practical side, **Cuckoo Sandbox** [5] became the widely used open-source implementation, and **CAPEv2** [6] is its actively maintained successor with added unpacking and configuration extraction. Reading their architecture is worthwhile because they already solved many engineering problems this project will meet.

**What this means for the project:** the overall pipeline shape is well established and does not need reinventing. The contribution has to be in interpretation, honesty of reporting, and explanation quality — not in the basic idea of "run it and watch."

### 5.2 How to watch the program

There is a fundamental split in how monitoring is implemented, and it is the single most important technical decision in this kind of system.

**In-guest monitoring** places an agent inside the analysis machine, hooking API calls or subscribing to operating system event streams. It is easier to build and gives rich, semantically meaningful data. Its weakness is that the malware and the monitor share a machine, so the malware can see the monitor and can potentially tamper with it.

**Out-of-guest monitoring**, also called virtual machine introspection, observes the analysis machine from the hypervisor below it. **Garfinkel and Rosenblum** [7] introduced the concept. **Ether** [8] applied hardware virtualization extensions to malware analysis specifically, achieving monitoring the sample could not easily detect. **DRAKVUF** [9] extended this into a practical, agentless system, and is the reference implementation to study today. **Jiang et al.** [10] addressed the core difficulty of this approach: from below, you see raw memory and CPU state, not meaningful concepts like "a process started." Reconstructing high-level meaning from low-level state is called the *semantic gap*, and closing it is real work.

For practical Windows monitoring without building a hypervisor, **Sysmon** [11] and **Event Tracing for Windows** [12] provide detailed, documented event streams and are the realistic starting point.

**What this means for the project:** the design must name its choice explicitly. In-guest monitoring via ETW and Sysmon is the correct starting point for feasibility. The event schema should be defined in *behavioural* terms — "process created," "registry value set" — rather than in terms of specific hooks, so a later move to introspection changes the producer without changing anything downstream.

### 5.3 Evasion — malware that behaves differently when watched

This is the area that most affects whether the system's results can be trusted.

**Chen et al.** [13] documented the anti-virtualization and anti-debugging behaviours present in real malware collections, establishing that this is common practice, not an exotic edge case. **Balzarotti et al.** [14] introduced the idea of detecting "split personalities" by comparing a sample's behaviour in different environments — if it behaves differently on real hardware than in a virtual machine, it is environment-sensitive. **Lindorfer et al.** [15] built on this with a system for detecting environment-sensitive malware systematically.

**BareCloud** [16] took the strongest position: analyse on bare metal, with no virtualization at all, and compare against virtualized runs to identify evasive samples. **MalGene** [17] went further and automatically extracted the *signature* of the evasion — identifying which specific system call sequence the malware used to work out it was being watched.

**What this means for the project:** a run producing no activity is not evidence of safety. It is an unresolved result. This literature directly justifies the **Run Outcome State** component in the architecture, which is one of the project's clearest design contributions. It also justifies re-detonation under varied configurations.

### 5.4 Static analysis and packing

**Lyda and Hamrock** [18] established entropy analysis as a practical way to spot encrypted or packed regions in a binary — compressed and encrypted data looks statistically random, ordinary code does not. This simple measure remains one of the most useful cheap signals available.

**Ucci et al.** [19] survey machine learning applied to static analysis specifically, covering which features have been used and how well they work. Practical tooling comes from **pefile** and **LIEF** [20] for parsing executable structure, and **YARA** [21] for pattern-based rules, which is the industry standard way to express "this file contains these markers."

**What this means for the project:** static analysis is cheap, safe, and always available. It should run first, and its output should choose the detonation strategy — a packed file needs different handling than an unpacked one.

### 5.5 Machine learning over behaviour

**Rieck et al.** [22] is the key early work on automatic analysis of malware behaviour using machine learning, showing that behaviour reports could be embedded into a vector space and classified. **Kolbitsch et al.** [23] took a different and instructive approach: extract behaviour graphs from known malware and match them efficiently at the endpoint, showing that graph structure carries detection value.

For static machine learning, **EMBER** [24] provided the first large open dataset of labelled PE features with a reproducible baseline, and became a standard benchmark. **MalConv** [25] demonstrated that a neural network could classify a binary from raw bytes with no feature engineering at all — an important result about what deep learning can extract, though expensive and hard to interpret. **SOREL-20M** [27] scaled the dataset problem up dramatically. The **Microsoft Malware Classification Challenge** dataset [28] remains widely used for family classification work. **Gibert et al.** [26] survey the whole machine learning area and are a good orientation read.

**What this means for the project:** feature engineering over behaviour, plus a conventional classifier, is a well-supported approach and does not need deep learning to be defensible. Behaviour graphs and call sequences are both established representations.

### 5.6 How machine learning in security goes wrong

This group of papers is the most important in the whole survey, and it is the one most student projects skip.

**Sommer and Paxson** [29] is the foundational critique. They explain why machine learning for intrusion detection is much harder than it looks: the cost of a false positive is very high, "normal" behaviour has enormous natural variety, and the adversary adapts. Their central point is that high accuracy in a paper often does not survive contact with deployment.

**TESSERACT** [30] identified specific experimental biases that inflate reported results. The most important is *temporal bias*: if you split your data randomly, your model gets trained on samples from the future and tested on the past, which cannot happen in reality and makes results far too optimistic. They also identify spatial bias — using an unrealistic ratio of malicious to benign samples in testing.

**Transcend** [31] and **Transcending Transcend** [33] address concept drift — models decay as malware evolves — and propose ways to detect when a model's predictions have stopped being reliable.

**Arp et al.** [32] consolidate all of this into a practical checklist of common mistakes in security machine learning: sampling bias, label inaccuracy, data snooping, spurious correlations, inappropriate baselines, inappropriate metrics, and lab-only evaluation.

**What this means for the project:** the evaluation methodology must use a **time-based split**, report **false-positive rate** prominently, use a realistic class balance, and state its limitations openly. This alone will make the project stronger than most work at this level, and it is the section an informed reviewer will probe first.

### 5.7 Structured threat knowledge

**MITRE ATT&CK** [34][35] is a public knowledge base of attacker techniques organised into tactics (the attacker's goal) and techniques (how they achieve it). It has become the shared vocabulary of the industry. Mapping observed behaviour onto ATT&CK converts a project-specific finding into something any security professional immediately understands.

**What this means for the project:** ATT&CK mapping is high value for relatively low effort. The important discipline is that each mapped technique must carry the evidence that justified it — unjustified mappings are a common and easily spotted weakness.

### 5.8 Language models in security tooling

This is the newest area and the least settled.

**Greshake et al.** [36] demonstrated indirect prompt injection: when a language model processes content from an untrusted source, that content can carry instructions which the model may follow. **Perez and Ribeiro** [37] showed related direct attacks. The **OWASP Top 10 for LLM Applications** [38] organises these risks into a practical checklist. **Ji et al.** [39] survey hallucination — the tendency of language models to produce fluent, confident, false statements.

**What this means for the project — and this is critical.** In this system, the language model reads telemetry produced by malware. File names, registry values, command lines and network payloads are all **attacker-controlled text**. A sample can deliberately contain text crafted to manipulate the report generator. The design consequences are direct:

- Telemetry is treated as data, never as instruction
- The model receives a strict output schema and cannot write free-form fields that affect the verdict
- Every claim must cite event identifiers, so a hallucinated indicator has nowhere to hide
- The verdict field is written by the deterministic engine and is read-only to the model

### 5.9 Network behaviour and simulated internet

Malware that cannot reach its command-and-control server usually does very little. But giving live malware real internet access is dangerous and often unethical. The standard resolution is a simulated internet: **INetSim** [40] and **FakeNet-NG** [41] answer DNS, HTTP and TLS requests with fake but plausible responses, so the sample believes it has connected and reveals its protocol and beaconing pattern.

**What this means for the project:** "no internet" and "useful network telemetry" cannot both be true. Simulated internet is the correct design and replaces the naive fully-blocked configuration.

### 5.10 Datasets

For behavioural data, the **Avast-CTU public CAPE dataset** [42] provides real sandbox reports with family labels, and **API call sequence datasets** [43] provide a simpler starting representation. **CIC-MalMem-2022** [44] targets memory-based detection of obfuscated malware. Live sample sources such as **MalwareBazaar** and **VirusShare** [45] provide raw binaries, and require serious handling precautions.

**What this means for the project:** using an existing labelled dataset for model training, while generating your own telemetry for demonstration, is a sound and common strategy. Always check the licence and citation requirements of any dataset used.

---

## 6. Research Gaps Identified

From the survey, the following gaps stand out.

**Gap 1 — Silence is misread as safety.** Sandboxes routinely report "no malicious behaviour observed." Downstream tools and humans treat this as clean. The evasion literature [13][14][15][16][17] shows this is frequently wrong, and wrong specifically on advanced samples. Very few systems model this distinction explicitly in their data model.

**Gap 2 — Output volume exceeds human capacity.** Sandboxes produce complete records and leave interpretation to the analyst. The work moves rather than disappears.

**Gap 3 — Explanations are not verifiable.** Where systems do summarise, the summary is usually not linked back to the specific evidence, so a reader cannot check it without redoing the analysis.

**Gap 4 — Evaluation is optimistic.** Despite clear guidance [29][30][32], random splits, unrealistic class balance, and accuracy-only reporting remain common, producing numbers that do not reflect deployment.

**Gap 5 — Language models are given too much authority.** Recent tools let a language model produce the verdict. Given hallucination [39] and prompt injection [36][37], and given that the input is attacker-controlled, this is unsafe.

**Gap 6 — Static and dynamic evidence stay separate.** Many systems use one or the other. Combining them is well understood in principle but less common in integrated open implementations.

**Gap 7 — Results are not reproducible.** Reports rarely record which rule version, model version and sandbox image produced them, so a changed verdict cannot be explained later.

---

## 7. Gaps This Project Addresses

### 7.1 Addressed

**Gap 1 — Explicit run-outcome states.** The data model records five distinct terminal states: completed, timed out, crashed on launch, no activity observed, and sandbox evasion suspected. These remain distinct in the database, in every query, and in every dashboard count. Silence is reported as an unresolved result, never as a clean verdict. *This is the project's clearest contribution.*

**Gap 2 — Layered reduction.** Raw events are normalised, deduplicated and enriched, then reduced to features and a behaviour graph, then to a verdict, then to a short readable explanation. Each layer is inspectable, so the analyst can start from the summary and drill down as far as needed.

**Gap 3 — Evidence-linked claims.** Every indicator, every ATT&CK technique mapping and every sentence of the generated explanation carries the identifiers of the events that support it. Nothing appears in a report that cannot be traced to recorded data.

**Gap 4 — Honest evaluation.** Time-based train/test split, realistic class balance, false-positive rate reported as a headline metric, and a written limitations section.

**Gap 5 — Constrained language model role.** The model explains; it never adjudicates. Telemetry is treated as untrusted data. Output is schema-constrained and citation-enforced.

**Gap 6 — Combined feature set.** Static features from pre-execution triage and dynamic features from execution are merged into one feature vector before classification, so packed files and non-running files both still produce signal.

**Gap 7 — Provenance stamping.** Every report records sandbox image version, rule pack version, model version and detonation configuration.

### 7.2 Explicitly not addressed

Stating this clearly is a strength, not a weakness. A reviewer trusts a report more when its boundaries are declared.

- **Bare-metal analysis.** Out of scope; virtualization is used, which advanced samples can potentially detect.
- **Complete evasion resistance.** Basic countermeasures only. This is an open research problem and cannot be "solved."
- **Automatic unpacking of arbitrary packers.** Detection of packing, yes; general unpacking, no.
- **Adversarial robustness of the classifier.** Attacks that deliberately craft inputs to fool the model are not defended against.
- **Non-Windows platforms.** The design allows for them; the implementation targets Windows PE files.
- **Real-time endpoint protection.** This is an analysis system, not a live protection agent.

---

## 8. Methodology

### 8.1 System overview

The system is a pipeline of eight stages, with two supporting stores and a set of platform-wide guardrails.

```
Input  ->  Static Triage  ->  Orchestrator  ->  Analysis Environment
       ->  Data Collection  ->  Analysis Engine  ->  AI Reasoning  ->  Output
```

### 8.2 Stage 1 — Input and submission

Accepts a file through a web interface or API. Supported types are declared explicitly, because each needs different handling: executables run directly, libraries need a host process and an export chosen, scripts need an interpreter, documents need a macro-enabled host application.

The file is stored encrypted, never executed by the storage layer, and never served inline to a browser. A job record is created with a unique identifier and queued. Access requires authentication and is rate-limited and logged.

### 8.3 Stage 2 — Static triage

Runs before execution. It is fast, costs no virtual machine time, and is the only signal available when a sample refuses to run.

- **Identification:** SHA-256 for exact matching, import hash for compiler-and-library fingerprinting, fuzzy hashes for near-match detection
- **Structure:** parse the executable header, list sections, measure entropy per section, examine the overlay and compile timestamp
- **Content:** extract imported functions, readable strings, embedded resources, and candidate indicators such as URLs and IP addresses
- **Packing:** detect packers and obfuscators from signatures and entropy patterns; the result selects the detonation strategy
- **Reputation:** verify code signature, check against a known-good allowlist, look up hashes in threat intelligence feeds

Output: a static feature vector, an early risk signal, and a recommended detonation profile.

### 8.4 Stage 3 — Detonation orchestrator

Manages execution. A scheduler assigns queued jobs to available workers with concurrency and retry limits. Before every run, the analysis machine is restored to a known-clean snapshot, so no run can contaminate the next. A detonation profile derived from stage 2 sets arguments, privilege level, timeout, library export selection and user-interaction script. After the run, the machine is destroyed while artifacts and telemetry are retained.

### 8.5 Stage 4 — Analysis environment

An isolated virtual machine, with the sensors running **inside** the boundary observing the sample.

Five sensors:

| Sensor | Records |
|---|---|
| Process | process tree, code injection, child processes |
| System call | API sequences, arguments, return values |
| Network | DNS queries, HTTP requests, TLS metadata, beacon timing |
| File system | writes, drops, deletes, mass-encryption patterns |
| Registry | persistence keys, service creation, scheduled tasks |

Two supporting components:

**Simulated internet.** Fake DNS, HTTP and TLS responders convince the sample its command server is reachable, so its protocol and beaconing become visible without real network access.

**Evasion handling.** Sleep-call patching so long delays do not consume the timeout; stalling-loop detection; simulated user activity such as mouse movement and typing; masking of obvious virtual-machine artifacts; and re-detonation under alternative configurations when a run produces nothing.

### 8.6 Stage 5 — Data collection and normalisation

Raw sensor output is parsed into a single event schema shared by all sensors. Events are deduplicated, given consistent timestamps, and enriched with context such as threat-intelligence matches. High-volume streams are sampled to keep the system stable.

Normalised events go through a queue into a durable telemetry store. The queue decouples the rate of detonation from the rate of analysis. Because raw normalised events are retained, a new rule pack can be replayed over every historical run without touching a virtual machine again.

**The event schema is the most important interface in the system.** It is defined at the behavioural level, so a future change of monitoring technology replaces the producer without disturbing anything downstream.

### 8.7 Stage 6 — Analysis engine

**Feature extraction** combines static features from stage 2 with dynamic features: process tree shape, API call frequencies, file operation patterns, network features, and behaviour sequences.

**Behaviour representation** builds three views — a behaviour graph with processes, files, keys and hosts as nodes and their interactions as edges; a sequence model of ordered API calls; and a vector embedding written to the vector index for similarity search.

**Detection and classification** uses four layers, each covering a different failure mode:

| Layer | Catches |
|---|---|
| Rule-based checks | known-bad patterns |
| Machine learning models | known families |
| Anomaly detection | novel behaviour |
| Similarity search | variants of known samples |

**Threat interpretation** maps behaviour to MITRE ATT&CK techniques with evidence links, and computes a risk score and confidence value.

**Run outcome state** is recorded explicitly, as described in section 7.1.

### 8.8 Stage 7 — AI reasoning and report generation

**Evidence aggregation** collects the indicators that drove the verdict, each paired with the exact supporting event identifiers.

**Language model reasoning** summarises behaviour, explains reasoning and suggests next steps, under strict constraints:
- Telemetry is attacker-controlled text and is passed as data, never as instruction
- Output must conform to a fixed schema
- Every claim must cite event identifiers
- The verdict field is read-only

**Report generation** produces the final document with verdict, confidence, indicators, timeline, behaviour graph, ATT&CK mapping, recommendations and a provenance stamp.

### 8.9 Stage 8 — Output and interaction

A dashboard presents the verdict, timeline, behaviour graph and evidence, rendering sample-derived content inertly. Reports export as PDF, JSON or CSV, version-stamped. Similarity search answers "what else behaved like this?" An analyst verdict control lets a human confirm or correct the automated result, feeding a curated labelled dataset. Retraining from that dataset is a deliberate, reviewed step — never an automatic loop, which would allow a poisoned label to reshape the model unnoticed.

### 8.10 Data stores

| Store | Contents |
|---|---|
| File storage | samples, memory dumps, dropped artifacts — encrypted at rest, exported only in password-protected archives |
| Telemetry database | normalised events, logs, artifact index — replayable against new rules |
| Metadata database | jobs, queue state, run outcomes, report index, provenance stamps |
| Vector index | behaviour embeddings for similarity search and variant clustering |

### 8.11 Experimental methodology

**Datasets.** A labelled behavioural dataset for training and evaluation [42][43], with static features drawn from an established PE dataset [24] where useful. Benign samples come from clean system binaries and legitimate installers. Custom benign programs that imitate malicious behaviour patterns are written for controlled end-to-end demonstration with known ground truth.

**Splitting.** Strictly time-based following TESSERACT [30]: train on samples observed before a chosen date, test on samples after it. Random splits are not used, because they let the model learn from the future.

**Class balance.** The test set uses a realistic proportion of malicious to benign samples rather than an even split.

**Baselines.** Compare against a rules-only configuration and a static-features-only classifier, so the contribution of behavioural features is measurable rather than assumed.

**Metrics.** Precision, recall, F1, false-positive rate, ROC-AUC, and confusion matrix. False-positive rate is treated as the headline number, because an analyst-facing tool with a high false-positive rate gets switched off regardless of its recall.

**Reproducibility.** Fixed random seeds, recorded library versions, and provenance stamps on every result.

---

## 9. Results and Discussion

> **This section is a template.** Fill it in after running the experiments. Every table below has the structure needed; the numbers are for you to measure. Do not estimate or borrow figures — a reviewer who asks "how did you get that?" will expose it instantly, and honest modest numbers with a good discussion are worth far more than impressive ones you cannot defend.

### 9.1 Experimental setup (to fill)

Record: hardware specification, hypervisor and version, guest operating system image, number of samples by class, dataset sources and versions, split dates, library versions, sandbox timeout, and total analysis time.

### 9.2 Pipeline performance

| Measure | Value |
|---|---|
| Samples submitted | |
| Reached a terminal state | |
| Mean analysis time per sample | |
| Samples analysed per hour | |
| Mean events recorded per run | |
| Events after deduplication | |

### 9.3 Run outcome distribution

This table is a direct output of the project's main contribution — showing that "no activity" is a real and measurable category rather than a rounding error.

| Outcome | Count | Percentage |
|---|---|---|
| Completed | | |
| Timed out | | |
| Crashed on launch | | |
| No activity observed | | |
| Sandbox evasion suspected | | |

Discuss: what fraction of samples produced no usable behaviour, and what a conventional sandbox would have reported for them.

### 9.4 Detection performance

| Configuration | Precision | Recall | F1 | FPR | ROC-AUC |
|---|---|---|---|---|---|
| Rules only (baseline) | | | | | |
| Static features only | | | | | |
| Dynamic features only | | | | | |
| Combined static + dynamic | | | | | |

Include the confusion matrix for the best configuration. Discuss which feature groups contributed most, and examine the false positives individually — legitimate installers and system utilities are the usual culprits, and saying so demonstrates understanding.

### 9.5 Effect of time-based splitting

| Split method | F1 | FPR |
|---|---|---|
| Random split | | |
| Time-based split | | |

The gap between these two rows is one of the most valuable results in the whole project. It quantifies the optimism bias that TESSERACT [30] describes, using your own data. Discuss the size of the drop and what it implies about published results that use random splits.

### 9.6 ATT&CK mapping coverage

| Measure | Value |
|---|---|
| Distinct techniques observed | |
| Mean techniques per malicious sample | |
| Mappings carrying evidence links | (target: 100%) |
| Most frequent techniques | |

### 9.7 Evasion handling

| Measure | Value |
|---|---|
| Runs where stalling was detected | |
| Runs triggering re-detonation | |
| Re-detonations producing new behaviour | |
| Samples flagged as evasion-suspected | |

### 9.8 Report quality

| Measure | Value |
|---|---|
| Claims carrying event citations | (target: 100%) |
| Reports with schema violations | (target: 0) |
| Mean report generation time | |
| Injection attempts detected in telemetry | |

Discuss any case where a sample's own strings appeared to target the report generator. Even one such example is a strong, memorable finding.

### 9.9 Discussion points to develop

- Which behavioural signals proved most useful, and were they the ones you expected?
- Where did the system fail, and why?
- How much did the language model actually add over a structured template report?
- How did the false-positive rate behave, and which benign software caused problems?
- What did the time-based split reveal about how quickly the model would decay in deployment?

### 9.10 Threats to validity

- Dataset labels come from external sources and may contain errors
- The sample set may not represent current threats
- Virtualization is detectable, so evasive samples are under-represented in the behavioural data
- The simulated internet is not the real internet; samples requiring a live server behave differently
- Results reflect one hardware and software configuration
- Benign samples were collected in a specific way that may not represent real-world software diversity

---

## 10. Conclusion

This project builds a complete pipeline for analysing unknown programs: static inspection, orchestrated detonation in an isolated instrumented environment, normalisation of the resulting telemetry, layered detection combining rules, machine learning, anomaly detection and similarity search, mapping to MITRE ATT&CK, and finally a readable evidence-linked report.

The design choices that matter most are not the individual components, which are well established, but three architectural commitments:

**Silence is reported honestly.** The system distinguishes "we watched it do nothing harmful" from "we could not observe it." This addresses a real and consequential weakness in existing tools, and it is cheap to build if designed in from the start and painful to retrofit later.

**Every claim carries evidence.** Nothing appears in a report that cannot be traced to specific recorded events. This makes the output checkable by a human, which is what makes it usable in practice.

**The language model explains but never decides.** Given that the model's input is text controlled by an adversary, and given what is known about hallucination and prompt injection, keeping the verdict in deterministic hands is not conservatism — it is the only defensible design.

The evaluation methodology is deliberately conservative: time-based splits, realistic class balance, and false-positive rate as a headline metric. This will produce less impressive numbers than a random split would, and those numbers will be worth considerably more.

### 10.1 Future work

- Hypervisor-level introspection to replace in-guest monitoring, removing the sample's ability to see the monitor
- Bare-metal analysis for cross-checking evasive samples
- Automatic extraction of evasion signatures, following MalGene [17]
- Extension to Linux ELF binaries and to script-based and document-based threats
- Adversarial robustness testing of the classifier
- Automated configuration extraction from identified malware families
- Drift monitoring with automated alerting when model reliability degrades

---

## 11. References

> **Verify every entry before submission.** Check author spelling, venue, and year against the publisher's page or the authors' own listing. Reference errors are easy to make and easy for a reviewer to spot.

### Dynamic analysis and sandboxes

[1] C. Willems, T. Holz, F. Freiling. "Toward Automated Dynamic Malware Analysis Using CWSandbox." *IEEE Security & Privacy*, 2007.

[2] U. Bayer, P. M. Comparetti, C. Hlauschek, C. Kruegel, E. Kirda. "Scalable, Behavior-Based Malware Clustering." *NDSS*, 2009.

[3] M. Egele, T. Scholte, E. Kirda, C. Kruegel. "A Survey on Automated Dynamic Malware-Analysis Techniques and Tools." *ACM Computing Surveys*, 2012.

[4] O. Or-Meir, N. Nissim, Y. Elovici, L. Rokach. "Dynamic Malware Analysis in the Modern Era — A State of the Art Survey." *ACM Computing Surveys*, 2019.

[5] Cuckoo Sandbox — official documentation. https://cuckoosandbox.org

[6] CAPEv2 Sandbox — project repository. https://github.com/kevoreilly/CAPEv2

### Monitoring and virtual machine introspection

[7] T. Garfinkel, M. Rosenblum. "A Virtual Machine Introspection Based Architecture for Intrusion Detection." *NDSS*, 2003.

[8] A. Dinaburg, P. Royal, M. Sharif, W. Lee. "Ether: Malware Analysis via Hardware Virtualization Extensions." *ACM CCS*, 2008.

[9] T. K. Lengyel, S. Maresca, B. D. Payne, G. D. Webster, S. Vogl, A. Kiayias. "Scalability, Fidelity and Stealth in the DRAKVUF Dynamic Malware Analysis System." *ACSAC*, 2014.

[10] X. Jiang, X. Wang, D. Xu. "Stealthy Malware Detection Through VMM-Based Out-of-the-Box Semantic View Reconstruction." *ACM CCS*, 2007.

[11] Microsoft. "Sysmon" — Windows Sysinternals documentation.

[12] Microsoft. "Event Tracing for Windows (ETW)" — Windows developer documentation.

### Evasion

[13] X. Chen, J. Andersen, Z. M. Mao, M. Bailey, J. Nazario. "Towards an Understanding of Anti-Virtualization and Anti-Debugging Behavior in Modern Malware." *DSN*, 2008.

[14] D. Balzarotti, M. Cova, C. Karlberger, E. Kirda, C. Kruegel, G. Vigna. "Efficient Detection of Split Personalities in Malware." *NDSS*, 2010.

[15] M. Lindorfer, C. Kolbitsch, P. M. Comparetti. "Detecting Environment-Sensitive Malware." *RAID*, 2011.

[16] D. Kirat, G. Vigna, C. Kruegel. "BareCloud: Bare-metal Analysis-based Evasive Malware Detection." *USENIX Security*, 2014.

[17] D. Kirat, G. Vigna. "MalGene: Automatic Extraction of Malware Analysis Evasion Signature." *ACM CCS*, 2015.

### Static analysis

[18] R. Lyda, J. Hamrock. "Using Entropy Analysis to Find Encrypted and Packed Malware." *IEEE Security & Privacy*, 2007.

[19] D. Ucci, L. Aniello, R. Baldoni. "Survey of Machine Learning Techniques for Malware Analysis." *Computers & Security*, 2019.

[20] pefile (Python PE parser) and LIEF (Library to Instrument Executable Formats) — project documentation.

[21] YARA — "The pattern matching swiss knife for malware researchers." Official documentation.

### Machine learning for malware

[22] K. Rieck, P. Trinius, C. Willems, T. Holz. "Automatic Analysis of Malware Behavior Using Machine Learning." *Journal of Computer Security*, 2011.

[23] C. Kolbitsch, P. M. Comparetti, C. Kruegel, E. Kirda, X. Zhou, X. Wang. "Effective and Efficient Malware Detection at the End Host." *USENIX Security*, 2009.

[24] H. S. Anderson, P. Roth. "EMBER: An Open Dataset for Training Static PE Malware Machine Learning Models." *arXiv preprint*, 2018.

[25] E. Raff, J. Barker, J. Sylvester, R. Brandon, B. Catanzaro, C. Nicholas. "Malware Detection by Eating a Whole EXE." *AAAI Workshops*, 2018.

[26] D. Gibert, C. Mateu, J. Planes. "The Rise of Machine Learning for Detection and Classification of Malware." *Journal of Network and Computer Applications*, 2020.

[27] R. Harang, E. M. Rudd. "SOREL-20M: A Large Scale Benchmark Dataset for Malicious PE Detection." *arXiv preprint*, 2020.

[28] R. Ronen, M. Radu, C. Feuerstein, E. Yom-Tov, M. Ahmadi. "Microsoft Malware Classification Challenge." *arXiv preprint*, 2018.

### Evaluation methodology

[29] R. Sommer, V. Paxson. "Outside the Closed World: On Using Machine Learning for Network Intrusion Detection." *IEEE Symposium on Security and Privacy*, 2010.

[30] F. Pendlebury, F. Pierazzi, R. Jordaney, J. Kinder, L. Cavallaro. "TESSERACT: Eliminating Experimental Bias in Malware Classification across Space and Time." *USENIX Security*, 2019.

[31] R. Jordaney, K. Sharad, S. K. Dash, Z. Wang, D. Papini, I. Nouretdinov, L. Cavallaro. "Transcend: Detecting Concept Drift in Malware Classification Models." *USENIX Security*, 2017.

[32] D. Arp, E. Quiring, F. Pendlebury, A. Warnecke, F. Pierazzi, C. Wressnegger, L. Cavallaro, K. Rieck. "Dos and Don'ts of Machine Learning in Computer Security." *USENIX Security*, 2022.

[33] F. Barbero, F. Pendlebury, F. Pierazzi, L. Cavallaro. "Transcending Transcend: Revisiting Malware Classification in the Presence of Concept Drift." *IEEE Symposium on Security and Privacy*, 2022.

### Threat knowledge

[34] B. E. Strom, A. Applebaum, D. P. Miller, K. C. Nickels, A. G. Pennington, C. B. Thomas. "MITRE ATT&CK: Design and Philosophy." *MITRE Technical Report*, 2018 (revised 2020).

[35] MITRE. "ATT&CK Enterprise Matrix." https://attack.mitre.org

### Language models and their risks

[36] K. Greshake, S. Abdelnabi, S. Mishra, C. Endres, T. Holz, M. Fritz. "Not What You've Signed Up For: Compromising Real-World LLM-Integrated Applications with Indirect Prompt Injection." *ACM AISec Workshop*, 2023.

[37] F. Perez, I. Ribeiro. "Ignore Previous Prompt: Attack Techniques For Language Models." *NeurIPS ML Safety Workshop*, 2022.

[38] OWASP. "OWASP Top 10 for Large Language Model Applications."

[39] Z. Ji, N. Lee, R. Frieske, et al. "Survey of Hallucination in Natural Language Generation." *ACM Computing Surveys*, 2023.

### Network simulation

[40] INetSim — Internet Services Simulation Suite. https://www.inetsim.org

[41] FakeNet-NG — Mandiant FLARE team. https://github.com/mandiant/flare-fakenet-ng

### Datasets

[42] B. Bosansky, D. Kouba, O. Manhal, T. Sick, V. Lisy, J. Kroustek, P. Somol. "Avast-CTU Public CAPE Dataset." *arXiv preprint*, 2022.

[43] A. Oliveira. "Malware Analysis Datasets: API Call Sequences." *IEEE DataPort*, 2019.

[44] T. Carrier, P. Victor, A. Tekeoglu, A. H. Lashkari. "Detecting Obfuscated Malware using Memory Feature Engineering" (CIC-MalMem-2022). *ICISSP*, 2022.

[45] MalwareBazaar (abuse.ch) and VirusShare — malware sample repositories.

### Books and engineering references

[46] M. Sikorski, A. Honig. *Practical Malware Analysis.* No Starch Press, 2012.

[47] M. Yosifovich, A. Ionescu, M. E. Russinovich, D. A. Solomon. *Windows Internals, Part 1*, 7th edition. Microsoft Press, 2017.

[48] J. Saxe, H. Sanders. *Malware Data Science.* No Starch Press, 2018.

[49] M. H. Ligh, S. Adair, B. Hartstein, M. Richard. *Malware Analyst's Cookbook and DVD.* Wiley, 2010.

[50] D. Andriesse. *Practical Binary Analysis.* No Starch Press, 2019.

[51] M. Kleppmann. *Designing Data-Intensive Applications.* O'Reilly Media, 2017.

---

## Appendix A — Glossary

| Term | Meaning |
|---|---|
| Static analysis | Examining a file without running it |
| Dynamic analysis | Running a program and observing its behaviour |
| Sandbox | An isolated environment where untrusted programs can run safely |
| Detonation | Deliberately executing a suspected malicious sample to observe it |
| Packer | A tool that compresses or encrypts a program so its contents are hidden until it runs |
| Entropy | A measure of randomness; high entropy suggests compression or encryption |
| API call | A request from a program to the operating system to perform an action |
| System call | The lowest-level form of such a request |
| Behaviour graph | A graph of processes, files, keys and hosts, and the actions connecting them |
| IOC | Indicator of Compromise — an observable such as a hash, IP address or file path |
| MITRE ATT&CK | A public catalogue of attacker tactics and techniques |
| Virtual machine introspection | Observing a virtual machine from the hypervisor below it |
| Semantic gap | The difficulty of reconstructing high-level meaning from low-level machine state |
| Concept drift | The decay of a model's accuracy as the real world changes around it |
| False positive | Flagging something harmless as malicious |
| Prompt injection | Text in a model's input that manipulates the model's behaviour |
| Provenance stamp | A record of which versions of software, rules and models produced a result |
