# Prerequisites and Study Guide
## What to learn for each of the 8 stages

---

### How this document is organised

The system has **8 stages**. This guide gives one section per stage: what you must already know, what you need to learn, which tools to use, what to read, a practice exercise, and a checklist that tells you when you are ready to start building.

> **A note on wording.** Earlier I used "phase" for the *build order* (v1, then expansions) and "stage" for the *parts of the architecture*. This document is organised by the **8 architecture stages**, because that is what you actually need to study. Section 10 at the end maps these stages onto the build order, so you know which ones to study first.

**Before anything else, read Section 0.** It covers the foundations that every stage assumes. Skipping it will cost you more time than it saves.

---

## Section 0 — Foundations (study this first)

You need these before any stage makes sense. Roughly 2 to 3 weeks if you are starting fresh, much less if you already program comfortably.

### 0.1 Programming

- **Python**: functions, classes, type hints, virtual environments, `pip`, reading library documentation
- **Working with structured data**: JSON, dictionaries, `dataclasses` or `pydantic`
- **Basic SQL**: create tables, insert, select, join, index
- **Git**: branches, meaningful commits, writing a README

### 0.2 Operating system concepts

Everything in this project is about watching what a program asks the operating system to do. If these ideas are vague, nothing downstream will make sense.

- What a **process** is, and what a process tree means
- What a **thread** is
- What **virtual memory** is, at a conceptual level
- What a **system call** is, and why it is the boundary between a program and the operating system
- What the **Windows Registry** is and why it matters for persistence
- What a **file handle** is
- What **privilege levels** mean (user mode versus kernel mode)

**Read:** *Windows Internals, Part 1* [47], chapters 1 to 3. Do not attempt to read the whole book. Read those chapters and return to others when a specific stage needs them.

### 0.3 Security basics

- The **CIA triad** (confidentiality, integrity, availability)
- What malware categories mean: trojan, ransomware, worm, dropper, loader, backdoor, rootkit
- What **command and control** (C2) means
- What **persistence** means and why attackers need it
- The idea of **indicators of compromise**

**Read:** *Practical Malware Analysis* [46], chapters 1 to 3.

### 0.4 Machine learning basics

- Supervised versus unsupervised learning
- Training, validation and test sets, and why they must be separate
- Overfitting
- Precision, recall, F1, confusion matrix — and specifically **why accuracy is a misleading metric on imbalanced data**
- One tree-based model in practice: random forest or gradient boosting

### 0.5 Safety rules — read before touching any real sample

These are not optional and they are not bureaucratic.

1. **Never run an unknown sample on your main machine or your normal network.** Reimaging a laptop is a bad afternoon; infecting a home network is worse.
2. Use a **dedicated virtual machine with no shared folders**, host-only or fully isolated networking, and snapshot before every run.
3. **Do not connect a malware VM to your home Wi-Fi.**
4. Store samples in **password-protected archives** so no scanner or preview tool executes them accidentally.
5. Prefer **public datasets** and **your own harmless test programs** over live malware wherever possible. You can build and demonstrate almost this entire system without a single real malicious sample.
6. Check the licence and terms of any dataset before you use it, and cite it as required.

---

## Stage 1 — Input and Submission

**What it does:** accepts a file, stores it safely, creates a job record, puts it in a queue.

### Prerequisites
- Python web framework basics (FastAPI recommended — modern, typed, automatic API documentation)
- HTTP fundamentals: methods, status codes, multipart file upload
- Relational database basics and an ORM (SQLAlchemy)
- Authentication concepts: API keys, tokens, why endpoints need authorisation
- Encryption at rest, at a practical level

### Concepts to learn
- **Job state machines** — how a task moves through states and why an explicit state enum is safer than a boolean flag
- **Idempotency** — submitting the same file twice should not create two conflicting jobs
- **Content type validation** — never trust the file extension a user supplies
- **Safe file serving** — why a file must never be served with a content type that lets a browser execute it

### Tools
FastAPI, SQLAlchemy, SQLite (start here) or PostgreSQL, Pydantic

### Read
- FastAPI official tutorial (complete it end to end — it is short and good)
- OWASP guidance on unrestricted file upload
- *Designing Data-Intensive Applications* [51], chapter 1

### Practice exercise
Build a small API that accepts a file upload, computes its SHA-256, stores it under a hashed filename, creates a job row with a status field, and returns the job identifier. Add an endpoint to query job status.

### Ready when you can
- [ ] Explain why storing a file under its original name is unsafe
- [ ] Write the five run-outcome states into a database enum
- [ ] Explain what happens when two people upload the same file at once

**Estimated study time:** 4 to 6 days

---

## Stage 2 — Static Triage

**What it does:** examines the file without running it. Produces static features and chooses the detonation strategy.

### Prerequisites
- Understanding of what a compiled executable is
- Comfort with bytes, hexadecimal, and binary file formats
- Basic statistics (for entropy)

### Concepts to learn
- **PE file format** — the structure of Windows executables: DOS header, NT headers, section table, import table, export table, resources. This is the single most important thing to learn for this stage.
- **Sections** and what typical section names mean
- **Shannon entropy** — the formula, and why values near 8.0 suggest compression or encryption [18]
- **Import table and import hashing** — why the set of functions a program plans to call is informative, and what an import hash fingerprints
- **Fuzzy hashing** (ssdeep, TLSH) — how to measure "these two files are similar" rather than "identical"
- **Packing and obfuscation** — what packers do and why they defeat static analysis
- **Code signing** — what a valid signature proves and, importantly, what it does not
- **YARA rules** — syntax, strings, conditions, and how rules are organised into packs

### Tools
`pefile`, `LIEF`, `yara-python`, `ssdeep` or `tlsh`, `capa` (worth studying — it maps static capabilities to ATT&CK and is a good model for your own design)

### Read
- Microsoft PE Format specification (official documentation — dense but authoritative)
- Ange Albertini's PE format visual guides (excellent for understanding structure quickly)
- Lyda and Hamrock on entropy [18]
- YARA documentation [21]
- *Practical Malware Analysis* [46], chapters 1 and 2
- *Practical Binary Analysis* [50], chapters 1 to 3

### Practice exercise
Write a script that takes any `.exe` and prints: all hashes, compile timestamp, section names with entropy values, imported DLLs and functions, extracted strings over 6 characters, and whether it appears packed. Run it on `notepad.exe` and on a UPX-packed binary you create yourself, and compare the entropy values.

### Ready when you can
- [ ] Draw the PE structure from memory
- [ ] Explain why high entropy suggests packing
- [ ] Write a YARA rule that matches a string pattern
- [ ] Explain what an import hash tells you and what it does not

**Estimated study time:** 1.5 to 2 weeks — this is the most learning-heavy stage, and also the safest and most rewarding one to start with

---

## Stage 3 — Detonation Orchestrator

**What it does:** manages virtual machines, assigns jobs to workers, restores clean snapshots, applies the detonation profile.

### Prerequisites
- Comfortable on the command line
- Basic networking: IP addresses, ports, DNS, NAT
- Process management concepts

### Concepts to learn
- **Virtualization** — hypervisor types, what a guest and a host are, why isolation is not absolute
- **Snapshots** — how they work and why restoring before every run is mandatory rather than optional
- **Virtual machine automation** — controlling a VM from code (starting, stopping, restoring, copying files in, running commands)
- **Job queues and worker pools** — how tasks are distributed, and what happens when a worker dies mid-job
- **Timeouts and cancellation** — how to stop something that will not stop by itself
- **Network isolation modes** — host-only, internal, NAT, and which to use

### Tools
- **Virtualization:** VirtualBox (free, scriptable via `VBoxManage`), VMware, KVM/libvirt, or Hyper-V
- **Automation:** `pyvbox`, `libvirt-python`, or the command-line tools driven from Python
- **Queues:** start with a database table, move to Redis or RabbitMQ later
- **Containers:** Docker for the platform services — but note clearly that **containers are not a safe boundary for running malware**; use a full virtual machine for that

### Read
- VirtualBox manual, chapters on `VBoxManage` and snapshots
- Cuckoo Sandbox architecture documentation [5] — study how it manages machines
- Celery or RQ documentation for the worker model

### Practice exercise
Script a full cycle: restore a VM from snapshot, start it, copy a file in, run it, wait a fixed time, copy results out, shut down, restore snapshot again. Get this working reliably with a harmless program before anything malicious is involved. Expect this to take longer than you think — it always does.

### Ready when you can
- [ ] Restore and start a VM entirely from code with no clicking
- [ ] Explain why a container is not sufficient isolation for malware
- [ ] Handle the case where a VM hangs and never returns

**Estimated study time:** 1 to 1.5 weeks, plus debugging time that is genuinely unpredictable

---

## Stage 4 — Analysis Environment

**What it does:** runs the sample under observation, with five sensors, a simulated internet, and evasion handling.

This is the largest and hardest stage. Study it in three parts.

### Part A — Monitoring

**Concepts to learn**
- **API hooking** — how a monitor intercepts calls a program makes
- **ETW (Event Tracing for Windows)** — the built-in, documented, supported way to observe system activity. Start here.
- **Sysmon** — configurable system monitoring that logs process creation, network connections, file creation and registry changes. The fastest route to real telemetry.
- **Kernel drivers and minifilters** — conceptual understanding only; do not attempt to write one
- **Virtual machine introspection** — the alternative approach, and the semantic gap problem [7][8][9][10]

**Tools:** Sysmon, Process Monitor (Procmon), ETW via `pywintrace` or logman, Windows Event Log

**Read:** Sysmon documentation [11], ETW documentation [12], and the SwiftOnSecurity Sysmon configuration (widely used, well commented, and an education in itself)

### Part B — Network observation and simulation

**Concepts to learn**
- Packet capture basics
- DNS resolution flow
- HTTP request structure
- TLS handshake, and why you can see metadata such as certificates and SNI even when content is encrypted
- **Simulated internet** — why fake responders reveal more than a blocked connection [40][41]
- **Beaconing** — periodic callbacks, and how timing patterns identify them

**Tools:** Wireshark, `tshark`, `scapy`, INetSim, FakeNet-NG

### Part C — Evasion handling

**Concepts to learn**
- How malware detects virtual machines: registry keys, driver names, MAC address prefixes, timing checks, CPU instruction behaviour
- **Sleep patching** — intercepting delay calls so a sample cannot wait out your timeout
- **Stalling loops** — pointless computation used to burn analysis time
- **User interaction simulation** — mouse movement, keystrokes, dialog clicking
- **Trigger conditions** — date checks, argument requirements, language and locale checks

**Read:** Chen et al. [13], Balzarotti et al. [14], Lindorfer et al. [15], Kirat and Vigna [17]. Also study the Al-Khaser project, which collects VM detection techniques in one runnable place.

### Practice exercise
Install Sysmon in a VM with a good configuration. Write a harmless program that creates a Run registry key, writes files to a temporary directory, spawns a child process, and makes a DNS lookup. Run it and confirm every action appears in the Sysmon event log. This gives you real telemetry with known ground truth and zero risk — and it is the single most useful exercise in this entire guide.

### Ready when you can
- [ ] Collect process, file, registry and network events from a running program
- [ ] Name five ways malware detects a virtual machine
- [ ] Explain why fully blocking the network reduces the information you collect

**Estimated study time:** 2 to 3 weeks

---

## Stage 5 — Data Collection and Normalisation

**What it does:** turns messy sensor output into one clean event schema, then stores it durably.

### Prerequisites
- Comfortable with JSON and data transformation
- Basic database design

### Concepts to learn
- **Schema design** — this is the most important skill in this stage. The event schema is the contract that holds the whole system together. Define it at the behavioural level ("process created"), not at the mechanism level ("hook on NtCreateProcess returned").
- **Schema versioning** — how to change a schema without breaking stored data
- **Deduplication** — recognising that the same real action was reported twice by two sensors
- **Timestamp normalisation** — clock differences, ordering, monotonic versus wall-clock time
- **Enrichment** — attaching context, such as a threat-intelligence match, to an event as it passes through
- **Message queues** — producer and consumer, back-pressure, at-least-once delivery
- **Sampling** — how to reduce volume without discarding the events that matter

### Tools
Pydantic for schema definition and validation, SQLite or PostgreSQL, Redis or RabbitMQ for the queue, `pandas` for exploratory analysis

### Read
- *Designing Data-Intensive Applications* [51], chapters 4 (encoding and evolution) and 11 (stream processing) — the two most relevant chapters for this stage
- The MITRE ATT&CK data sources documentation, which is a good model for thinking about what an event should contain

### Practice exercise
Take Sysmon output and Procmon output for the same program run. Write a normaliser that converts both into one shared event format. You will immediately discover the hard problems: the same action described differently, missing fields, and different time formats. Solving this is the point of the exercise.

### Ready when you can
- [ ] Write your event schema on one page and defend every field
- [ ] Explain why the schema must not mention Sysmon specifically
- [ ] Handle the same event arriving twice

**Estimated study time:** 1 week

---

## Stage 6 — Analysis Engine

**What it does:** turns events into features, representations, a verdict, and an ATT&CK mapping.

### Prerequisites
- Section 0.4 machine learning basics
- `numpy`, `pandas`, `scikit-learn`
- Basic graph theory: nodes, edges, directed graphs, paths

### Concepts to learn

**Feature engineering**
- Turning variable-length event sequences into fixed-length vectors
- N-grams over API call sequences
- Frequency features, count features, ratio features
- Combining static and dynamic feature groups into one vector

**Behaviour representation**
- **Behaviour graphs** — processes, files, registry keys and hosts as nodes; actions as edges [23]
- **Sequence models** — order matters, because the same actions in different order mean different things
- **Embeddings** — turning behaviour into a vector so that similar behaviour lands nearby

**Detection**
- Rule engines and how to express behavioural heuristics
- Classification with tree-based models (start here — they work well on this kind of feature and are interpretable)
- **Anomaly detection**: isolation forest, one-class SVM
- **Similarity search**: cosine distance, approximate nearest neighbour

**Evaluation — study this properly, it is the part that separates a serious project from a naive one**
- Why **accuracy** is misleading on imbalanced data
- **Precision, recall, F1, ROC-AUC** and when each is appropriate
- **False-positive rate**, and why it is the metric that decides whether a security tool survives contact with real users
- **Temporal splitting** and why random splits inflate results [30]
- **Concept drift** [31][33]
- The common mistakes checklist [32] — read this paper carefully and check your own design against every item

**ATT&CK mapping**
- Tactics versus techniques versus sub-techniques
- Building a mapping from observed behaviours to technique identifiers
- Attaching evidence to each mapping

### Tools
`scikit-learn`, `networkx` (behaviour graphs), `xgboost` or `lightgbm`, FAISS or `chromadb` (vector search), `matplotlib` (evaluation plots)

### Read
- Rieck et al. [22] — the foundational behavioural machine learning paper
- Kolbitsch et al. [23] — behaviour graphs
- **TESSERACT** [30] — read this one twice
- **Arp et al.** [32] — the mistakes checklist
- Sommer and Paxson [29] — the philosophical grounding
- *Malware Data Science* [48] — the most practical book for this stage
- MITRE ATT&CK design and philosophy [34]

### Practice exercise
Take a public API-call-sequence dataset. Build a classifier. Then evaluate it twice: once with a random split, once with a time-based split. Measure the difference. Understanding *why* the numbers drop is worth more than the classifier itself, and this comparison belongs directly in your results section.

### Ready when you can
- [ ] Explain why accuracy is a bad metric here
- [ ] Explain temporal bias to someone in two sentences
- [ ] Build a behaviour graph from an event list
- [ ] Justify a false-positive rate target for a real deployment

**Estimated study time:** 2 to 3 weeks

---

## Stage 7 — AI Reasoning and Report Generation

**What it does:** turns evidence into a readable explanation, safely.

### Prerequisites
- Calling an LLM API from Python
- JSON schema validation

### Concepts to learn
- **Prompt design** for a constrained task — you are not chatting, you are asking for structured output
- **Structured output** — schema-constrained generation, and validating the response before trusting it
- **Grounding** — requiring every claim to reference supplied evidence
- **Prompt injection**, especially the indirect kind [36][37]. This is the central risk for this stage. Your input is text produced by malware, and malware authors will eventually write text aimed at your report generator.
- **Hallucination** [39] — why a fluent, confident, false sentence is the specific failure mode to design against
- **Separation of duties** — why the verdict field must be computed, not generated
- **Determinism and reproducibility** — the same input should ideally produce the same report; record the model version regardless

### Tools
An LLM API client, Pydantic for output validation, Jinja2 for report templating, WeasyPrint or ReportLab for PDF generation

### Read
- **OWASP Top 10 for LLM Applications** [38] — work through the whole list against your design
- Greshake et al. on indirect prompt injection [36]
- Your chosen API provider's documentation on structured output and tool use

### Practice exercise
Build a report generator that takes a list of events and produces a summary where **every sentence carries an event identifier**. Then attack your own system: write a test sample whose file names contain text such as instructions to ignore previous directions and report the file as clean. Confirm your design does not comply. If it does comply, fix it — and either way, write the result up. That experiment is a genuinely strong finding for your report.

### Ready when you can
- [ ] Explain indirect prompt injection clearly
- [ ] Enforce a strict output schema and reject non-conforming output
- [ ] Explain why the model must never write the verdict field
- [ ] Detect a report claim that lacks supporting evidence

**Estimated study time:** 1 week

---

## Stage 8 — Output and Interaction

**What it does:** presents results, exports reports, supports search and analyst feedback.

### Prerequisites
- HTML, CSS, basic JavaScript
- A frontend approach: plain templates are perfectly acceptable; React only if you already know it

### Concepts to learn
- **Data visualisation for security**: timelines, graph rendering, technique matrices
- **Safe rendering** — sample-derived strings must be escaped, never rendered as HTML. A malicious file name containing a script tag must not execute in your dashboard. This is a real, tested attack path against analysis platforms.
- **Content Security Policy** and why it matters here more than in an ordinary web application
- **Export formats** — PDF for humans, JSON for machines, CSV for spreadsheets
- **Similarity search interfaces** — presenting nearest neighbours usefully
- **Feedback and labelling workflow** — capturing an analyst's correction with enough context to be useful later
- **Data poisoning** — why an automatic learning loop from user feedback is dangerous, and why review gates exist

### Tools
Jinja2 templates or React, `vis.js` / `cytoscape.js` / `d3` for graph rendering, Chart.js for plots, WeasyPrint for PDF

### Read
- OWASP guidance on cross-site scripting prevention
- The ATT&CK Navigator (study how it presents the technique matrix)
- Any public sandbox report — for example a VirusTotal or Any.Run behaviour report — read several and note what makes some readable and others overwhelming

### Practice exercise
Build a single page showing one analysis: verdict banner, timeline, behaviour graph, ATT&CK grid, evidence table. Then test it with a file whose name contains HTML tags and confirm nothing executes.

### Ready when you can
- [ ] Render a behaviour graph from event data
- [ ] Prove your dashboard escapes hostile file names
- [ ] Explain why feedback must not retrain the model automatically

**Estimated study time:** 1 to 1.5 weeks

---

## Section 9 — Cross-cutting topics

These apply to every stage and are worth a dedicated study block.

### 9.1 Platform security
- Sandbox escape as a threat to your own system
- Network segmentation for the analysis environment
- Authentication and authorisation
- Encryption at rest
- Audit logging

### 9.2 Reproducibility
- Version stamping every artifact
- Dependency pinning
- Fixed random seeds
- Recording configuration alongside results

### 9.3 Research and writing skills
- Reading a security paper efficiently: abstract, then conclusion, then figures, then method
- Finding papers: Google Scholar, DBLP, arXiv, and the proceedings pages of USENIX Security, IEEE S&P, ACM CCS, NDSS, RAID, DIMVA, ACSAC
- Managing references with Zotero or Mendeley
- **Verifying a citation before using it** — always check the real venue and year

### 9.4 Ethics and law
- Handling malware samples responsibly
- Dataset licences and citation requirements
- Why you do not test on systems or networks you do not own
- Responsible disclosure, if you find something unexpected

---

## Section 10 — Study order and mapping to the build

You will not study these in numerical order. Study them in the order you will build them.

### Recommended order

| Order | Stage | Why here |
|---|---|---|
| 1 | Section 0 — Foundations | Everything assumes it |
| 2 | Stage 2 — Static Triage | Safest, highest learning value, needs no VM |
| 3 | Stage 1 — Input | Simple, gets a working skeleton running |
| 4 | Stage 5 — Data Collection | The schema shapes everything downstream; design it early |
| 5 | Stage 6 — Analysis Engine | The intellectual core; can be built on public datasets alone |
| 6 | Stage 7 — AI Reasoning | Needs stage 6 output to exist |
| 7 | Stage 8 — Output | Makes everything demonstrable |
| 8 | Stage 4 — Analysis Environment | The hardest; needs the schema settled first |
| 9 | Stage 3 — Orchestrator | Only meaningful once stage 4 works |

Stages 3 and 4 come last deliberately. They are the most expensive and the most likely to consume unplanned time. Everything before them can be built and demonstrated using public datasets and your own harmless test programs, which means you always have something working to show.

### Mapping to the build phases

| Build phase | Stages involved | Study weight |
|---|---|---|
| v1 (first two weeks) | 1, 2, 5, 6, 7, 8 — with recorded traces standing in for live detonation | Sections 0, 2, 1, 5, 6, 7, 8 |
| Phase 2 — real detonation | 3, 4 | Stages 3 and 4 in full |
| Phase 3 — network | 4 (Part B) | Stage 4 Part B |
| Phase 4 — evasion handling | 4 (Part C) | Stage 4 Part C, plus the evasion papers |
| Phase 5 — similarity search | 6, vector index | Stage 6 embedding and search topics |
| Phase 6 — labelled data and retraining | 6, 8 | Stage 6 evaluation topics, drift papers |
| Phase 7 — hardening | cross-cutting | Section 9.1 |

---

## Section 11 — Total time estimate

| Block | Time |
|---|---|
| Section 0 — Foundations | 2 to 3 weeks |
| Stage 2 — Static Triage | 1.5 to 2 weeks |
| Stage 1 — Input | 4 to 6 days |
| Stage 5 — Data Collection | 1 week |
| Stage 6 — Analysis Engine | 2 to 3 weeks |
| Stage 7 — AI Reasoning | 1 week |
| Stage 8 — Output | 1 to 1.5 weeks |
| Stage 4 — Analysis Environment | 2 to 3 weeks |
| Stage 3 — Orchestrator | 1 to 1.5 weeks |
| Cross-cutting topics | 1 week |
| **Total study time** | **13 to 18 weeks** |

This is study time only, and it assumes part-time work. Implementation runs alongside it and adds more. That total is consistent with the 4 to 6 month estimate for the full system — study and building overlap heavily, because you learn most of this by building it.

**The important point:** you do not need all of this before you start. Sections 0 and Stage 2 alone are enough to begin writing useful code, and the first version can be built while the later stages are still being studied.

---

## Section 12 — Minimum reading list

If you read only ten things, read these.

1. **Egele et al.** — dynamic analysis survey [3]. Orients you in the whole field.
2. **Or-Meir et al.** — the modern update [4].
3. **TESSERACT** [30]. Will change how you evaluate.
4. **Arp et al.** — machine learning mistakes checklist [32]. Check your design against every item.
5. **Sommer and Paxson** [29]. Why this is harder than it looks.
6. **Chen et al.** — anti-virtualization behaviour [13]. Why "no activity" is not "clean."
7. **Rieck et al.** — behavioural machine learning [22].
8. **MITRE ATT&CK design and philosophy** [34].
9. **OWASP Top 10 for LLM Applications** [38].
10. **Practical Malware Analysis** [46], chapters 1 to 3.

Reference numbers match the reference list in `Project-Report.md`.
