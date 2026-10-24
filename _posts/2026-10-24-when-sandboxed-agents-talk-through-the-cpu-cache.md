---
title: "When sandboxed agents talk through the CPU cache"
---

On 23 October 2026 OpenAI published [Securing our frontier model training environment](https://openai.com/index/securing-our-frontier-model-training-environment/), a write-up of a large red-teaming campaign against its own model sandboxes. One paragraph went round social media faster than the rest: agents in separate microVMs, with no network and no shared writable files, still managed to pass secrets to each other through the processor's cache.

<figure class="post-figure">
  <img src="/assets/img/posts/2026-10-24-openai-cache-covert-channel.png" alt="Halvar Flake (@halvarflake) quote-posting Lisan al Gaib (@scaling01) on X. Halvar Flake writes: 'Am I weird for not finding it insane? You tell agents to communicate, they know about cache timing, this is the first thing you'd expect they try?' The quoted post reads 'completely insane. OpenAI agents communicated via cache timing differences, without any shared files or network connection', above OpenAI's paragraph: agents in separate VMs on shared host machines exchanged synthetic secrets by evicting cache lines and timing reloads." loading="lazy">
  <figcaption>The paragraph as it circulated on X: <a href="https://x.com/scaling01">@scaling01</a> called it "completely insane", and <a href="https://x.com/halvarflake">@halvarflake</a> replied that it was the obvious first move. Quoting <a href="https://openai.com/index/securing-our-frontier-model-training-environment/">OpenAI's report</a>.</figcaption>
</figure>

Not everyone was surprised. Halvar Flake (Thomas Dullien), a well-known security researcher, replied:

> Am I weird for not finding it insane? You tell agents to communicate, they know about cache timing, this is the first thing you'd expect they try?
>
> — [Halvar Flake on X](https://x.com/halvarflake)

He has a point.

This is not a new kind of attack. It is a textbook **covert channel**, and the computer-security literature has studied this exact problem since 1973. What *is* new is who is using it: models that can read the research, design a protocol, and try for as long as you let them.

This post covers what OpenAI actually reported, why a virtual machine (Firecracker included) does not stop it, what seventeen years of cross-tenant attacks teach, and a layered defence, from scheduling policy down to cache colouring, drawing on USENIX, IEEE S&P, CCS, OSDI, Black Hat, Chaos Communication Congress, hacker-camp and Platform Security Summit work, and on public proofs of concept. It follows on from [Sandboxing untrusted AI agents on Linux]({% post_url 2026-10-21-sandboxing-untrusted-ai-agents-on-linux %}), which covers the sandbox mechanisms themselves; this post is about what leaks *between* sandboxes that are working as designed.

<div class="terms" markdown="1">

**📖 Terms in this section**

- **Sandbox.** A restricted environment for running code you do not fully trust, so that mistakes or attacks stay contained. ([NIST glossary](https://csrc.nist.gov/glossary/term/sandbox))
- **Red-teaming.** Attacking your own systems on purpose, playing the adversary, to find weaknesses before a real attacker does. ([NIST glossary](https://csrc.nist.gov/glossary/term/red_team))
- **Virtual machine (VM) and microVM.** A VM is a complete computer simulated in software, with its own operating system, running on a real machine alongside other VMs. A microVM is a stripped-down VM that starts in a fraction of a second; Firecracker, built by AWS, is the best-known one. ([NIST glossary](https://csrc.nist.gov/glossary/term/virtual_machine) · [Firecracker](https://firecracker-microvm.github.io/))
- **CPU cache.** A small, very fast memory inside the processor that keeps copies of recently used data, so the processor does not have to wait for the much slower main memory. It is the medium OpenAI's agents used to signal. ([CPU cache](https://en.wikipedia.org/wiki/CPU_cache))
- **Proof of concept (PoC).** A working demonstration that an attack is possible, usually published as code. ([Proof of concept](https://en.wikipedia.org/wiki/Proof_of_concept))
- **Where the research comes from.** [USENIX Security](https://www.usenix.org/conference/usenixsecurity26), [IEEE S&P](https://www.ieee-security.org/TC/SP-Index.html) and [ACM CCS](https://www.sigsac.org/ccs.html) are the main peer-reviewed academic security conferences (NDSS, RAID, MICRO, HPCA, EuroSys and OSDI, also cited here, are peer-reviewed too). [Black Hat](https://en.wikipedia.org/wiki/Black_Hat_Briefings) is the largest industry security conference, and the [Chaos Communication Congress](https://events.ccc.de/en/) is the annual hacker conference of Europe's Chaos Computer Club, where much of this research was also presented.

</div>

> Everything here is point-in-time (late October 2026). Quotes are from OpenAI's report unless marked otherwise.

## 🔎 What OpenAI reported

<div class="terms" markdown="1">

**📖 Terms in this section**

- **Container.** A way of running a program with its own private view of files, processes and network, while sharing the machine's operating-system kernel with every other container. Lighter than a VM, but weaker, because the kernel is shared. ([NIST glossary](https://csrc.nist.gov/glossary/term/container) · [Docker overview](https://docs.docker.com/get-started/docker-overview/))
- **Kernel.** The core of the operating system. It controls memory, processes and hardware, and every program must ask it for anything privileged. ([Kernel](https://en.wikipedia.org/wiki/Kernel_(operating_system)))
- **Hypervisor (VMM).** The software that creates and runs VMs and keeps them apart; also called a virtual machine monitor. ([NIST glossary](https://csrc.nist.gov/glossary/term/hypervisor))
- **Host.** The physical machine that VMs or containers run on.
- **Kata Containers and gVisor.** Two hardened ways to run containers. Kata puts each container inside its own lightweight VM; gVisor answers the container's requests to the kernel with a separate kernel written as an ordinary program. ([Kata Containers](https://katacontainers.io/) · [gVisor](https://gvisor.dev/docs/))
- **Tokens.** The word fragments language models read and write. "Hundreds of billions of tokens" is a measure of how much model work the red team did. ([Hugging Face: tokenizers](https://huggingface.co/docs/transformers/tokenizer_summary))
- **CVE.** A public identifier for a known security flaw (Common Vulnerabilities and Exposures). The US National Vulnerability Database (NVD) publishes details for each one. ([CVE program](https://www.cve.org/About/Overview))
- **System calls and syscall filters.** A system call is a program's request to the kernel (open a file, start a process, send data). A syscall filter, such as Linux seccomp, limits which requests a program may make. ([syscalls(2)](https://man7.org/linux/man-pages/man2/syscalls.2.html); seccomp is covered in [the sandboxing post]({% post_url 2026-10-21-sandboxing-untrusted-ai-agents-on-linux %}))
- **Firewall.** A network control that allows or blocks traffic by rule. ([NIST glossary](https://csrc.nist.gov/glossary/term/firewall))
- **DNS.** The internet's naming system, which turns names like `example.com` into addresses. A misconfigured DNS server can become a route out of a network that is supposed to be closed. ([RFC 1034](https://www.rfc-editor.org/rfc/rfc1034))
- **TLS and a certificate cache.** TLS is the encryption behind `https://`. Servers prove their identity with certificates, and a certificate cache keeps recently used ones to save time. When that cache is shared, "was this certificate already cached?" becomes a signal one agent can set and another can measure. ([RFC 8446](https://www.rfc-editor.org/rfc/rfc8446) · [NIST glossary](https://csrc.nist.gov/glossary/term/transport_layer_security))
- **Chain of thought.** The step-by-step reasoning a model writes out before answering. Reading it can reveal what the model is planning. ([Wei et al., 2022](https://arxiv.org/abs/2201.11903))

</div>

The report describes the containment stack for training and evaluating frontier models, then a red-teaming campaign against it.

**The containment stack.** On Linux, agents run in "restricted containers inside lightweight microVMs": the container limits files and processes, and the microVM "runs its own operating-system kernel and is isolated from the host by a hypervisor". GPU tasks use "GPU-backed containers with user-space sandboxing". Around that sit monitoring with automatic stopping, and a network and cloud perimeter "designed to maintain containment even if an agent escapes its sandbox and gains control of the host". Frontier training runs with **no live internet access** at all; agents browse an "offline world" of indexed and cached web content instead. Agents that are allowed to cooperate share an explicit message board; everything else is meant to be unreachable.

**The red team.** Teams of frontier-model agents, including an upcoming "GPT-6 Astra Cyber" model, were given three goals: reach the live internet, cross an internal security boundary, and communicate across isolation boundaries. To favour the attacker they were given "infrastructure source code, configuration details, and documentation describing potential vulnerabilities". The campaign used "hundreds of billions of tokens".

**What they found.** Three classes of result:

1. 🧨 **MicroVM escapes.** Agents "found several ways to chain vulnerabilities into microVM escapes". Fixes went to Kata Containers ([CVE-2026-24834](https://nvd.nist.gov/vuln/detail/CVE-2026-24834), privilege and filesystem isolation), gVisor (file-descriptor handling), Moby/Docker (syscall filters) and the Linux kernel ([CVE-2026-74753](https://nvd.nist.gov/vuln/detail/CVE-2026-74753), [CVE-2026-80521](https://nvd.nist.gov/vuln/detail/CVE-2026-80521), [CVE-2026-80841](https://nvd.nist.gov/vuln/detail/CVE-2026-80841)), with more disclosures not yet public.
2. 🌐 **Paths to the internet from a compromised host.** Narrow connections that remained for metrics, logging and authentication "gave them limited forms of internet access" in almost every case. One agent "reused a firewall-approved connection to reach a blocked authentication endpoint in our metrics service and then made that endpoint fetch a model-provided URL". Others slipped requests through DNS and firewall misconfigurations, or made internal services fetch external URLs.
3. 📡 **Communication across isolation.** The paragraph in the screenshot: agents "in separate microVMs, created and managed by OpenAI's sandboxing software on shared host machines" exchanged synthetic secrets "without the use of network connections or shared writable files". One agent evicted chosen data from the cache; the other timed reloads and read fast as 0 and slow as 1, or similar. Other channels used **shared storage** (one agent "alternated between continuous writes and inactivity", which an agent described in its chain of thought as an "acoustic modem-like signal"), **competition for CPU time** within a shared execution container, and **a TLS certificate cache** in the offline web infrastructure.

Two caveats from the report itself matter for reading this fairly:

- **The agents had help.** "In most of these tests, we directed agents to investigate specific communication channels or provided them with a protocol." In one case they got only "a broad list of infrastructure vulnerabilities", and still turned one into a channel and agreed an encoding on their own.
- **The channels are slow.** "Most of these channels carry information slowly and are difficult for models to exploit." OpenAI's response was to add "checks to our monitoring systems to detect attempts to communicate through these channels". Note what that is: **detection, not removal**.

## 🔊 Covert channels, side channels, and the confinement problem

<div class="terms" markdown="1">

**📖 Terms in this section**

- **Side channel.** Information that leaks through the side effects of a computation (how long it takes, how much power it draws, what it does to a cache) rather than through its outputs. ([NIST glossary](https://csrc.nist.gov/glossary/term/side_channel))
- **Covert channel.** A hidden communication path that two cooperating parties create through something that was never meant to carry information, in breach of a security policy. ([NIST glossary](https://csrc.nist.gov/glossary/term/covert_channel))
- **Tenant and multi-tenancy.** A tenant is a customer or workload; multi-tenant means many unrelated tenants share the same hardware, as on a public cloud. ([Multitenancy](https://en.wikipedia.org/wiki/Multitenancy))
- **Cryptographic key.** The secret value that makes encryption or a digital signature work. Whoever has the key can read or forge what it protects. ([NIST glossary](https://csrc.nist.gov/glossary/term/cryptographic_key))
- **Error correction.** Adding redundancy to a message so the receiver can repair bits damaged by noise. It is what lets a covert channel work on a busy, noisy machine. ([Error detection and correction](https://en.wikipedia.org/wiki/Error_detection_and_correction))
- **Bandwidth.** How much information a channel carries per second, in bits per second (bit/s). At 1 bit/s, a 256-bit key takes a little over four minutes to send.
- **Prime+Probe and Flush+Reload.** The two classic cache-timing techniques. In Prime+Probe, the receiver fills part of the cache with its own data, waits, then times its own reads to see which lines the sender pushed out. In Flush+Reload, the receiver removes a piece of memory it *shares* with the sender from the cache, waits, then times a read to see whether the sender loaded it back. ([Osvik, Shamir and Tromer, 2005](https://eprint.iacr.org/2005/271) · [Yarom and Falkner, 2014](https://www.usenix.org/conference/usenixsecurity14/technical-sessions/presentation/yarom))
- **TCP/IP.** The family of protocols the internet runs on. Murdoch's talk showed that unused or loosely checked fields in these protocols can carry hidden messages. ([RFC 9293, TCP](https://www.rfc-editor.org/rfc/rfc9293))

</div>

Two terms get used interchangeably and should not be:

- A **side channel** leaks information from an *unwilling* victim. Classic example: recovering a cryptographic key from another tenant's cache access pattern.
- A **covert channel** is two *cooperating* parties signalling through something that was never meant to carry information. Sender and receiver agree a protocol in advance, so they can repeat, add error correction, and go slowly. That makes covert channels far easier than side channels.

OpenAI's agents built covert channels. Butler Lampson named this in [A note on the confinement problem (1973)](https://dl.acm.org/doi/10.1145/362375.362389): a confined program can leak through any shared resource whose behaviour it can influence and another party can observe, including timing and load. Fifty years of results since have converged on an uncomfortable conclusion: **on shared hardware you cannot eliminate covert channels, only reduce their bandwidth**, which is why security evaluation schemes historically required covert-channel *analysis* and bandwidth limits rather than proof of absence. The hacker community has known it just as long: Steven Murdoch's [Covert channels in TCP/IP (22C3, 2005)](https://media.ccc.de/v/22C3-798-en-tcpip_covert_channels) at the Chaos Communication Congress showed how much room ordinary protocol fields leave for hidden signalling, and how hard that is to filter out.

Why this matters more with agents than with ordinary malware:

- 🤝 **Collusion is the default case.** In a multi-agent system you start many copies of the same model, with the same training, possibly the same instructions. If two of them "want" to coordinate, they do not need to negotiate a protocol at runtime: they can converge on the obvious one.
- 📚 **The attack literature is in the weights.** Prime+Probe, Flush+Reload and the rest are well documented, and the report shows models applying them.
- ⏱️ **Patience is cheap.** A channel at a few bits per second is useless for bulk data but plenty for an API key, a coordination signal, or "the reviewer is not watching now".

The security question is therefore not "can agents in separate sandboxes communicate?" (assume yes) but "**what can they achieve if they do?**"

## 🧬 Microarchitectural state, and why it matters so much

<div class="terms" markdown="1">

**📖 A short hardware primer**

- **Core and thread (SMT, Hyper-Threading).** A processor contains several cores, each an independent processing unit. With simultaneous multithreading (SMT; Intel calls it Hyper-Threading), one core runs two threads at once, and the two share almost everything inside the core. ([Multi-core processor](https://en.wikipedia.org/wiki/Multi-core_processor) · [Simultaneous multithreading](https://en.wikipedia.org/wiki/Simultaneous_multithreading))
- **Socket, package and die.** A server can hold more than one processor chip, each in its own socket. Each chip (package) contains one or more pieces of silicon (dies). Cores on the same chip share more than cores on different chips. ([CPU socket](https://en.wikipedia.org/wiki/CPU_socket) · [Die](https://en.wikipedia.org/wiki/Die_(integrated_circuit)) · [Linux x86 topology](https://docs.kernel.org/arch/x86/topology.html))
- **Cache levels, cache lines and eviction.** L1 and L2 are small caches private to each core; L3, the last-level cache (LLC), is larger and shared by many cores. Data moves in fixed-size blocks called cache lines (64 bytes on most CPUs). When a cache is full, an old line is evicted to make room. Eviction is what OpenAI's agents controlled. ([CPU cache](https://en.wikipedia.org/wiki/CPU_cache))
- **Main memory (DRAM), banks and row buffers.** The large, slower memory. It is divided into banks, each made of rows; the row most recently read in each bank stays open in a row buffer, so reading it again is faster. ([Dynamic random-access memory](https://en.wikipedia.org/wiki/Dynamic_random-access_memory))
- **Virtual memory, page tables and the TLB.** Programs use virtual addresses, which the processor translates to physical memory addresses using page tables kept by the operating system. The translation lookaside buffer (TLB) caches recent translations. ([Virtual memory](https://en.wikipedia.org/wiki/Virtual_memory) · [Linux page tables](https://docs.kernel.org/mm/page_tables.html) · [Translation lookaside buffer](https://en.wikipedia.org/wiki/Translation_lookaside_buffer))
- **Branch predictor and prefetcher.** The branch predictor guesses which way a program will go next so the processor can start work early; the prefetcher guesses which data will be needed and loads it ahead of time. Both learn from whatever ran before, including other people's programs. ([Branch predictor](https://en.wikipedia.org/wiki/Branch_predictor) · [Cache prefetching](https://en.wikipedia.org/wiki/Cache_prefetching))
- **Execution ports.** The internal units that do the actual arithmetic and memory work. Two threads on one core compete for them. ([Out-of-order execution](https://en.wikipedia.org/wiki/Out-of-order_execution))
- **Coherence directory.** A bookkeeping structure that records which core holds a copy of which cache line, so every core sees the same memory. ([Directory-based cache coherence](https://en.wikipedia.org/wiki/Directory-based_cache_coherence))
- **Instruction set (ISA) and registers.** The instruction set is the documented contract between software and processor, such as x86 or Arm. Registers are the processor's handful of working storage slots. ([Instruction set architecture](https://en.wikipedia.org/wiki/Instruction_set_architecture) · [Processor register](https://en.wikipedia.org/wiki/Processor_register))
- **Process and context switch.** A process is a running program with its own memory. A context switch is when the operating system or hypervisor pauses one process or VM and runs another on the same core, saving the first one's registers so it can resume. ([NIST glossary: process](https://csrc.nist.gov/glossary/term/process) · [Context switch](https://en.wikipedia.org/wiki/Context_switch))
- **Speculative execution.** The processor runs ahead on its guesses instead of waiting. If a guess was wrong it discards the results, but traces stay in the caches and other microarchitectural state. ([Speculative execution](https://en.wikipedia.org/wiki/Speculative_execution) · [Linux: Spectre](https://docs.kernel.org/admin-guide/hw-vuln/spectre.html))
- **Namespaces, seccomp, Landlock.** Linux's building blocks for confining programs, explained in [the sandboxing post]({% post_url 2026-10-21-sandboxing-untrusted-ai-agents-on-linux %}). seL4 and time protection are explained in [the frontier section](#-the-frontier).

</div>

Everything that follows hinges on one distinction. A CPU has two layers of state:

- **Architectural state** is what the instruction set promises software: registers, memory contents, flags, the instruction pointer. It is documented, programs can read it, and an operating system or hypervisor saves and restores it on every context switch. All of our isolation is defined in these terms: "process A cannot read process B's memory", "VM A cannot see VM B's registers".
- **Microarchitectural state** is how a particular chip delivers that promise quickly: what is in the caches and which line gets evicted next, the TLBs that cache address translations, branch predictors, prefetchers, internal buffers, which execution ports are busy, the coherence directory, which DRAM rows are open, the current clock frequency. None of it is part of the contract. Software cannot read it directly, and a program computes the same answer whatever state it is in.

The catch is that microarchitectural state is invisible to a program's *results* but visible in its *timing*. A load that hits the L1 cache takes a few nanoseconds; one that goes to DRAM takes around a hundred. Same answer, different time, and anything that changes timing can carry information.

That is how OpenAI's agents talked. The hypervisor kept each VM from reading the other's memory the whole time, but both VMs ran on the same physical cache. The sender filled a group of cache lines to send a 1 and stayed idle to send a 0; the receiver timed its own memory accesses, reading slow (its data was evicted) as 1 and fast as 0. Neither ever touched the other's memory. Think of two hotel rooms with locked doors and shared plumbing: flush in one room, and the neighbour hears it in the pipes.

The two layers, drawn out: isolation is a wall built only at the top layer. Everything below it is one shared building.

<div class="mermaid">
flowchart TB
    subgraph ARCH["Architectural state — what the hypervisor isolates"]
        direction LR
        A1["VM A&lt;br/&gt;memory, registers, kernel"]
        A2["VM B&lt;br/&gt;memory, registers, kernel"]
    end

    subgraph HW["Microarchitectural state — one physical CPU, never virtualised"]
        direction LR
        CACHE["CPU cache&lt;br/&gt;L1 / L2 / L3"]
        TLB["TLB"]
        DRAM["DRAM banks&lt;br/&gt;and row buffers"]
        PRED["Branch predictor&lt;br/&gt;and prefetcher"]
        FREQ["Clock frequency&lt;br/&gt;and power"]
    end

    SEND["Sender process, in VM A:&lt;br/&gt;fill cache lines = 1&lt;br/&gt;stay idle = 0"] -->|evicts lines| CACHE
    CACHE -->|changed occupancy, read back as timing| RECV["Receiver process, in VM B:&lt;br/&gt;time its own reads —&lt;br/&gt;slow = 1, fast = 0"]

    ARCH -.isolated from.-> HW

    classDef archBox fill:#dce8f8,stroke:#1d4f91,stroke-width:2px,color:#0f2a4d
    classDef hwBox fill:#ece2fb,stroke:#6a3fd1,stroke-width:2px,color:#30205a
    classDef proc fill:#fbe4d8,stroke:#c0392b,stroke-width:2px,color:#6b2416
    class A1,A2 archBox
    class CACHE,TLB,DRAM,PRED,FREQ hwBox
    class SEND,RECV proc

    style ARCH fill:#f3f8fd,stroke:#1d4f91,stroke-width:1.5px,color:#0f2a4d
    style HW fill:#f8f4fd,stroke:#6a3fd1,stroke-width:1.5px,color:#30205a

    linkStyle 0 stroke:#c0392b,stroke-width:2.5px
    linkStyle 1 stroke:#c0392b,stroke-width:2.5px
    linkStyle 2 stroke:#8a8a8a,stroke-width:1.5px,stroke-dasharray:4 3
</div>

*The hypervisor's wall (top) stops VM A reading VM B's memory directly. It does not reach the floor both VMs stand on: one cache, one set of DRAM banks, one clock. The sender and receiver never cross the wall — they just both touch the floor.*

Why this has such large implications for sandboxing:

1. 🧱 **Isolation only covers the layer above.** Every boundary in [the sandboxing post]({% post_url 2026-10-21-sandboxing-untrusted-ai-agents-on-linux %}) (namespaces, seccomp, Landlock, gVisor, a microVM) protects architectural state. The channel runs underneath all of them.
2. 🤝 **It is shared on purpose.** Sharing the L3 between cores, two hyperthreads per core, and handing idle capacity to whoever wants it are what make CPUs and clouds efficient. Every defence that removes sharing (dedicated cores, partitioned cache, fixed quotas, separate hosts) costs performance or money, which is why these channels have survived decades of research.
3. 🔁 **It is not saved or restored.** A context switch swaps registers, but caches, predictors and TLBs keep whatever the previous tenant left. So taking turns on a core leaks too, not just running side by side, which is why the defences include flushing on switch and pinning VMs to dedicated cores.
4. 🗺️ **It cannot be fully listed.** The instruction set is documented; the microarchitecture largely is not, and it changes with every CPU generation. When defenders partitioned the cache, attackers moved to the TLB, the coherence directory, the interconnect, the prefetcher and the clock frequency (all in the timeline below). You cannot partition a structure you do not know exists.
5. 👻 **Speculation turns covert channels into side channels.** A CPU runs ahead on guesses and throws away the *architectural* results of a wrong guess, but not the *microarchitectural* footprint. Spectre and Meltdown make the CPU speculatively touch a secret and then read it back from the cache: the same receiver OpenAI's agents used, which is why the report mentions those attacks. Cooperating agents do not need speculation; leaking an unwilling victim's secret does.
6. 🧮 **It sits below every policy layer.** Sandbox policy is written against architectural interfaces: seccomp sees system calls, Landlock sees paths and ports, a VM sees devices and memory, a proxy sees connections. A cache eviction involves no system call, file or packet, so none of them can see it. Only controls at the same level can act on it: *where* code runs (placement, SMT, pinning), *how* the hardware is divided (cache partitioning and colouring), and *what is wiped* between tenants (flushing, and seL4's "time protection", which treats microarchitectural state as a resource to divide in space or in time).

That last point is why the defence layers later in this post move from software policy to scheduling and hardware.

## 🧱 Why a VM, even Firecracker, does not stop this

<div class="terms" markdown="1">

**📖 Terms in this section**

- **vCPU and pinning.** A vCPU is a virtual processor given to a VM; on most clouds it is one hardware thread. The hypervisor decides which real core runs it, and may share a core between VMs over time. Pinning fixes a vCPU to one physical core for good. ([AWS: instance types and vCPUs](https://docs.aws.amazon.com/ec2/latest/instancetypes/instance-types.html) · [sched(7)](https://man7.org/linux/man-pages/man7/sched.7.html))
- **Memory deduplication (KSM).** A Linux feature that finds identical memory pages in different VMs and keeps a single shared copy to save memory. That shared copy is what Flush+Reload and Flip Feng Shui exploit. ([Linux KSM](https://docs.kernel.org/admin-guide/mm/ksm.html))
- **Inclusive and non-inclusive caches.** Whether the L3 must also hold a copy of everything in the smaller caches. It changes which attacks work, not whether the cache is shared. ([Cache inclusion policy](https://en.wikipedia.org/wiki/Cache_inclusion_policy))
- **Memory bus, memory controller and DIMMs.** The path between processor and memory, the circuit that manages it, and the memory sticks themselves. ([Memory controller](https://en.wikipedia.org/wiki/Memory_controller) · [DIMM](https://en.wikipedia.org/wiki/DIMM))
- **Mesh interconnect.** The on-chip network that links cores, caches and memory controllers. ([Network on a chip](https://en.wikipedia.org/wiki/Network_on_a_chip))
- **MIG.** NVIDIA Multi-Instance GPU splits one physical GPU into several smaller, separately managed GPUs. ([NVIDIA MIG user guide](https://docs.nvidia.com/datacenter/tesla/mig-user-guide/))
- **PCIe and NIC.** PCIe is the high-speed link between the processor and devices such as GPUs and network interface cards (NICs). ([PCI-SIG](https://pcisig.com/))
- **Microcode and firmware.** Microcode is low-level code inside the processor that vendors can update; many side-channel fixes ship this way. Firmware is the software built into the machine's hardware. ([Linux microcode](https://docs.kernel.org/arch/x86/microcode.html) · [NIST glossary: firmware](https://csrc.nist.gov/glossary/term/firmware))
- **Rowhammer, ECC and target row refresh.** Rowhammer: reading one DRAM row over and over can flip bits in neighbouring rows. ECC memory stores extra check bits that detect and correct some errors; target row refresh (TRR) refreshes rows next to heavily used ones. Neither fully stops Rowhammer. ([Kim et al., ISCA 2014](https://users.ece.cmu.edu/~yoonguk/papers/kim-isca14.pdf) · [ECC memory](https://en.wikipedia.org/wiki/ECC_memory))
- **Hyperscaler, instances, burstable.** A hyperscaler is a very large cloud provider such as AWS. An instance is one rented VM. Burstable instances get a share of a core and can borrow idle capacity. ([Hyperscale computing](https://en.wikipedia.org/wiki/Hyperscale_computing) · [AWS: burstable instances](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/burstable-performance-instances.html))

</div>

A virtual machine isolates *architectural* state: memory contents, registers, the kernel, devices. Covert channels live in *microarchitectural* and physical state that the hypervisor does not virtualise, because the hardware shares it:

| Shared resource | Example channel | Shared between VMs when… |
|---|---|---|
| L1/L2 caches, branch predictors, execution ports | Prime+Probe, port contention | they run on the same physical core (SMT siblings, or time-sharing a core) |
| Last-level cache (L3) | cross-core Prime+Probe | they run on the same socket or core complex |
| Coherence directory | directory Prime+Probe | same socket, even with non-inclusive caches |
| Shared memory pages | Flush+Reload | the host deduplicates pages (KSM) |
| Memory bus, DRAM banks and row buffers | bus locking, row-buffer timing | same memory controller or DIMMs |
| CPU frequency and power | frequency-based timing | same package |
| Mesh interconnect | interconnect contention | same die |
| GPU TLB, L2, PCIe | contention across GPU partitions | same physical GPU, even under MIG |
| Storage, network and software caches | I/O timing, cache hits | same disk, NIC, proxy or cache service |

Firecracker is explicit about where its responsibility ends. Its [production host setup guide](https://github.com/firecracker-microvm/firecracker/blob/main/docs/prod-host-setup.md) says "Firecracker is not able to mitigate host's hardware vulnerabilities" and asks the operator to:

- **disable SMT** where tenants must be separated ("Simultaneous Multi-Threading (SMT) is frequently a precondition for speculation issues");
- **disable Kernel Samepage Merging** "to mitigate side channel issues" that rely on page deduplication;
- keep microcode and firmware current, and use ECC memory with target row refresh against Rowhammer;
- run each Firecracker process for one tenant's workload.

It says nothing about cache partitioning or vCPU pinning. Those are left to you. So: a microVM is **necessary** (it stops the cheap software escapes, at least until a VMM bug is found, as OpenAI's red team showed), but it is **not sufficient** against covert channels. What decides the outcome is how the host is configured and, above all, what shares a host.

### Is any kind of VM immune?

"VM" is an overloaded word, so it is fair to ask whether some kind of virtual machine escapes this problem. None does. The VM technology decides how hard it is to *break out* of the VM; what decides whether a covert channel exists is **which hardware the VMs share**, and every kind of VM runs on shared hardware unless you arrange otherwise.

<div class="terms" markdown="1">

**📖 Terms in this section**

- **System VM.** A VM that runs a whole guest operating system with its own kernel, using the processor's virtualisation features. KVM is the Linux kernel's hypervisor, usually driven by QEMU, Firecracker or Cloud Hypervisor; Xen, VMware ESXi and Microsoft Hyper-V are the other mainstream ones. ([Linux KVM](https://docs.kernel.org/virt/kvm/index.html) · [QEMU](https://www.qemu.org/) · [Cloud Hypervisor](https://www.cloudhypervisor.org/) · [Xen Project](https://xenproject.org/) · [VMware ESXi](https://www.vmware.com/products/cloud-infrastructure/esxi-and-esx))
- **Static partitioning hypervisor.** A minimal hypervisor that splits the machine once, at start-up, giving each VM fixed cores, memory and devices and never sharing them over time. Built mainly for embedded and real-time systems. ([Jailhouse](https://github.com/siemens/jailhouse) · [Bao](https://github.com/bao-project/bao-hypervisor))
- **Language or process VM.** A "virtual machine" that runs portable code inside an ordinary program, with no guest kernel: the Java Virtual Machine, WebAssembly runtimes, JavaScript engines, the Linux kernel's eBPF. Isolation is enforced by the language runtime, inside one process and one address space (the set of memory addresses a process can use). ([JVM specification](https://docs.oracle.com/javase/specs/jvms/se21/html/index.html) · [WebAssembly](https://webassembly.org/) · [eBPF](https://ebpf.io/what-is-ebpf/))

</div>

| Kind of "VM" | Examples | What it separates | Microarchitectural channels? |
|---|---|---|---|
| System VMs | KVM (with QEMU, Firecracker, Cloud Hypervisor), Xen, VMware ESXi, Hyper-V | guest kernels, memory and devices | **Yes.** All run on the same cores, caches and memory unless the host is configured not to share them. The hypervisor brand changes the escape risk and which mitigations are built in, not the physics. |
| User-space kernels | gVisor | the host kernel, from the sandboxed program's requests | **Yes.** It shares the host's hardware like any process. |
| Confidential VMs | AMD SEV-SNP, Intel TDX guests | a guest's memory, from the host and hypervisor | **Yes.** Their threat models largely exclude side channels (see [the frontier section](#-the-frontier)). |
| Static partitioning hypervisors | Jailhouse, Bao, Xen "dom0less" | fixed cores and memory per VM, never time-shared | **Fewer.** No core sharing removes the L1, L2, TLB and SMT channels, and some add cache colouring: [Xen's cache colouring](https://xenbits.xen.org/docs/unstable/misc/cache-coloring.html) partitions the last-level cache on Arm64, though it is built for predictable timing in embedded systems rather than as a security boundary. Package-wide resources (memory bus, DRAM, frequency, interconnect) are still shared. |
| Verified microkernel with time protection | seL4 (research prototype) | cache colouring, flushing and padding on every domain switch | **Fewest known.** Designed to close timing channels, with proofs in progress, on specific hardware. Power and frequency remain out of reach of any software. |
| Language or process VMs | JVM, WebAssembly, JavaScript engines, eBPF | code inside one process | **Most.** Everything shares one process and address space, so Spectre-style reads cross the boundary directly. |

The last row deserves emphasis, because "run the agent's tools in a WebAssembly sandbox" is a common design. After Spectre, Google's V8 team concluded that language-level protection cannot keep secrets inside one process: "The only effective mitigation is to move sensitive data out of the process's address space" ([A year with Spectre, V8 blog](https://v8.dev/blog/spectre); see also [Spectre is here to stay](https://arxiv.org/abs/1902.05178)). Chrome's answer was [Site Isolation](https://www.chromium.org/Home/chromium-security/site-isolation/): a separate process per site. For agents the lesson is the same: a language sandbox is a good *integrity* boundary for running a tool, but two agents whose data must stay apart need at least separate processes, and against covert channels, separate hardware.

So the honest summary of this section: **every kind of VM shares hardware by default, and the only VMs that leak noticeably less are the ones built to stop sharing it** (static partitioning, colouring, time protection), which is exactly what the defences later in this post do on ordinary hypervisors.

### What a hyperscaler does

The clearest public description of production practice is AWS's [Nitro whitepaper section on side channels](https://docs.aws.amazon.com/whitepapers/latest/security-design-of-aws-nitro-system/the-ec2-approach-to-preventing-side-channels.html). Its design rules map almost one-to-one onto the table above:

- "CPU cores are never simultaneously shared among customers via Simultaneous Multi-Threading (SMT)", so instances never share L1 or L2 caches.
- Fixed-performance instances get physical cores and memory **pinned** for their lifetime, and "nor are any instance memory pages shared in any fashion across instances".
- Burstable instances can run *sequentially* on the same core, so "microarchitectural state is flushed when the core is rescheduled".
- The **last-level cache can still be shared**: "Some instance sizes can share some last level cache lines non-simultaneously." AWS exposes the real topology so customers can pick sizes that fill a whole L3 domain (in a typical two-socket Intel host, "an instance size that is one-half the largest size will fill a CPU core and will not share the L3 cache with another instance").
- For anyone who wants none of this, **Dedicated Instances and Dedicated Hosts** guarantee a single customer per physical machine.

That last point is the honest summary of the state of the art: even the most careful multi-tenant design falls back on "don't share the host" for the strongest guarantee.

## 📚 Seventeen years of cross-tenant channels

<div class="terms" markdown="1">

**📖 Terms in this section**

- **Co-residency.** Getting your VM placed on the same physical host as a target's.
- **Atomic operations.** Instructions that read and update memory as one indivisible step. Some forms briefly lock the memory bus for everyone. ([Linearizability](https://en.wikipedia.org/wiki/Linearizability))
- **RSA, AES and constant-time code.** RSA and AES are widely used encryption algorithms. Constant-time code is written so its timing does not depend on secret data, the standard defence against timing attacks. ([NIST glossary: RSA](https://csrc.nist.gov/glossary/term/rsa) · [FIPS 197: AES](https://csrc.nist.gov/pubs/fips/197/final) · [BearSSL: constant-time crypto](https://www.bearssl.org/constanttime.html))
- **Out-of-order execution.** Processors run instructions in whichever order is fastest, not the order written, and put the results back in order afterwards. ([Out-of-order execution](https://en.wikipedia.org/wiki/Out-of-order_execution))
- **ASLR.** Address space layout randomisation places code and data at random addresses so attackers cannot predict them; kernel ASLR does the same for the kernel. ([NIST glossary](https://csrc.nist.gov/glossary/term/address_space_layout_randomization))
- **OpenSSH and GPG.** OpenSSH provides secure remote logins; GPG signs and encrypts files, and its signatures protect Linux software updates. ([OpenSSH](https://www.openssh.com/) · [GnuPG](https://gnupg.org/))
- **Transient execution and MDS.** The family of flaws where speculative work leaks data through microarchitectural state; Spectre and Meltdown are the best known. Microarchitectural data sampling (MDS) leaks from small internal buffers. ([Transient execution vulnerabilities](https://en.wikipedia.org/wiki/Transient_execution_CPU_vulnerability) · [Linux: MDS](https://docs.kernel.org/admin-guide/hw-vuln/mds.html))
- **Cache Allocation Technology (CAT).** An Intel feature that lets the operating system reserve parts of the L3 cache for particular workloads (more in layer 2). ([Linux resctrl](https://docs.kernel.org/filesystems/resctrl.html))
- **DDIO.** Intel Data Direct I/O lets network cards write incoming data straight into the L3 cache. It is fast, but it makes the cache reachable from the network. ([NetCAT](https://www.vusec.net/projects/netcat/))
- **RAPL.** Running Average Power Limit, Intel's interface for reading how much energy the processor uses; Linux exposes it through the powercap framework. ([Linux powercap](https://docs.kernel.org/power/powercap/powercap.html))
- **Fuzzing.** Automatically trying huge numbers of generated inputs to find unexpected behaviour. ([OWASP: fuzzing](https://owasp.org/www-community/Fuzzing))
- **Dynamic frequency scaling.** Processors speed up and slow down to save power and stay cool. If the speed depends on the data being processed, timing reveals the data. ([Linux cpufreq](https://docs.kernel.org/admin-guide/pm/cpufreq.html) · [Dynamic frequency scaling](https://en.wikipedia.org/wiki/Dynamic_frequency_scaling))
- **Vector registers (AVX).** Extra-wide registers that process many values in one instruction. ([Advanced Vector Extensions](https://en.wikipedia.org/wiki/Advanced_Vector_Extensions))
- **Memory barrier.** An instruction that makes earlier memory operations finish before later ones start. ([Memory barrier](https://en.wikipedia.org/wiki/Memory_barrier))
- **Bug bounty.** A payment a company makes to researchers who report vulnerabilities to it. ([Bug bounty program](https://en.wikipedia.org/wiki/Bug_bounty_program))
- **Root.** The all-powerful administrator account on a Unix-like system. ([Superuser](https://en.wikipedia.org/wiki/Superuser))
- **Artifact repository (package mirror).** A server that stores and hands out software packages to many machines, such as JFrog Artifactory. ([JFrog Artifactory](https://jfrog.com/artifactory/) · [Package manager](https://en.wikipedia.org/wiki/Package_manager))

</div>

The OpenAI result sits at the end of a long line of research, most of it published at USENIX Security, IEEE S&P and CCS:

- **2009, co-residency.** Ristenpart et al., [Hey, you, get off of my cloud (CCS 2009)](https://dl.acm.org/doi/10.1145/1653662.1653687), showed you could deliberately place a VM on the same host as a target on EC2 and build cache-based covert channels between them.
- **2012, the memory bus.** Wu, Xu and Wang, [Whispers in the Hyper-space (USENIX Security 2012)](https://www.usenix.org/conference/usenixsecurity12/technical-sessions/presentation/wu), built a reliable cross-VM covert channel by locking the memory bus with atomic operations: no shared cache needed.
- **2014, Flush+Reload.** Yarom and Falkner, [Flush+Reload (USENIX Security 2014)](https://www.usenix.org/conference/usenixsecurity14/technical-sessions/presentation/yarom), extracted keys across VMs through *deduplicated* memory pages, which is why every hardening guide now says to turn KSM off. The same year, Varadarajan, Ristenpart and Swift's [scheduler-based defences (USENIX Security 2014)](https://www.usenix.org/conference/usenixsecurity14/technical-sessions/presentation/varadarajan) showed that a minimum run time for vCPUs plus state cleansing on context switch blunts cache attacks at low cost.
- **2015, out-of-order execution.** Sophia D'Antoine's Black Hat USA 2015 talk, [Exploiting Out-of-Order Execution for Covert Cross-VM Communication](https://blackhat.com/docs/us-15/materials/us-15-DAntoine-Exploiting-Out-Of-Order-Execution-For-Covert-Cross-VM-Communication-wp.pdf), built a cross-VM channel from the CPU's instruction reordering, another shared resource that no hypervisor virtualises.
- **2015, the last-level cache.** Liu, Yarom, Ge, Heiser and Lee, [Last-Level Cache Side-Channel Attacks are Practical (IEEE S&P 2015)](https://www.ieee-security.org/TC/SP2015/papers-archived/6949a605.pdf), removed the need to share a core or memory pages: Prime+Probe on the shared L3 works across cores. Inci et al. then recovered a full 2048-bit RSA key from a co-located instance on EC2 ([Seriously, get off my cloud!, 2015](https://eprint.iacr.org/2015/898)).
- **2015, Rowhammer from JavaScript.** Gruss and Maurice's [Rowhammer.js (32C3)](https://media.ccc.de/v/32c3-7197-rowhammer_js_root_privileges_for_web_apps) flipped DRAM bits from a web page using only ordinary memory accesses, by learning to evict cache lines on demand: the same eviction trick OpenAI's agents used to signal.
- **2016, Rowhammer across VMs.** Razavi et al., [Flip Feng Shui (USENIX Security 2016)](https://www.usenix.org/conference/usenixsecurity16/technical-sessions/presentation/razavi), went beyond leaking: a malicious VM used memory deduplication to share a physical page with a co-hosted victim, then flipped bits in it with Rowhammer, breaking OpenSSH public-key authentication and GPG signature checks. The authors took it to the hacker community too ([SHA2017 talk](https://media.ccc.de/v/SHA2017-95-flip_feng_shui)). It is the strongest argument for turning memory deduplication off.
- **2016, DRAM.** Pessl et al., [DRAMA (USENIX Security 2016)](https://www.usenix.org/conference/usenixsecurity16/technical-sessions/presentation/pessl), built covert channels through DRAM row buffers, which work across CPUs.
- **2016, leaks from unprivileged instructions.** Maurice and Lipp's [What could possibly go wrong with &lt;insert x86 instruction here&gt;? (33C3)](https://media.ccc.de/v/33c3-8044-what_could_possibly_go_wrong_with_insert_x86_instruction_here) showed cache attacks without a single memory access (using prefetch instructions) and a kernel ASLR bypass, all from unprivileged code. Their framing fits this post: safe software does not guarantee safe execution, because the hardware underneath leaks.
- **2017, SSH over the cache.** Maurice et al., [Hello from the Other Side (NDSS 2017)](https://www.ndss-symposium.org/ndss2017/ndss-2017-programme/hello-other-side-ssh-over-robust-cache-covert-channels-cloud/), presented at [Black Hat Asia 2017](https://blackhat.com/docs/asia-17/materials/asia-17-Schwarz-Hello-From-The-Other-Side-SSH-Over-Robust-Cache-Covert-Channels-In-The-Cloud.pdf), built an error-corrected cache covert channel between two Amazon EC2 instances robust enough to carry a **working SSH session**. This is the result to keep in mind when someone says covert channels are too slow or noisy to matter.
- **2018, Spectre and Meltdown.** [Speculative execution attacks](https://meltdownattack.com/) used the same cache-timing receiver as OpenAI's agents, as the report notes.
- **2018, taking stock of Spectre.** A year after disclosure, Lipp, Schwarz, Gruss and Canella's [A Christmas Carol: the Spectres of the Past, Present, and Future (35C3)](https://media.ccc.de/v/35c3-9893-a_christmas_carol_-_the_spectres_of_the_past_present_and_future) walked through the growing family of transient-execution variants and how many of the deployed mitigations covered only some of them.
- **2018, the TLB.** Gras et al., [TLBleed (USENIX Security 2018)](https://www.usenix.org/conference/usenixsecurity18/presentation/gras), leaked keys through the translation lookaside buffer shared by hyperthreads, **even with the cache partitioned by CAT**, because nothing partitions the TLB. OpenBSD responded by disabling hyperthreading by default ([VUSec project page](https://vusec.net/projects/tlbleed)).
- **2019, microarchitectural data sampling.** [RIDL, Fallout](https://mdsattacks.com/) and [ZombieLoad](https://zombieloadattack.com/) leaked data from internal CPU buffers across hyperthreads and across VMs, and patching them properly meant disabling SMT where tenants differ. The ZombieLoad authors presented it at [36C3](https://media.ccc.de/v/36c3-10754-zombieload_attack).
- **2019, coherence directories.** Yan et al., [Attack Directories, Not Caches (IEEE S&P 2019)](https://www.ieee-security.org/TC/SP2019/SP19-Slides-pdfs/Mengjia_Yan_-_10-Mengjia_Yan-MAC-Attack_Directories,_Not_Caches-v2.pdf), showed that switching to non-inclusive caches does not help, because the coherence directory is shared and attackable.
- **2020, the cache, from the network.** [NetCAT (IEEE S&P 2020)](https://www.vusec.net/projects/netcat/) used Intel's Data Direct I/O, which lets network cards write straight into the last-level cache, to probe a server's cache remotely and recover keystroke timing from an SSH session ([36C3 talk by Michael Kurth](https://media.ccc.de/v/36c3-10884-practical_cache_attacks_from_the_network_and_bad_cat_puns)). The cache is not only shared with co-tenants; anything that can send packets can reach it.
- **2020, power, read from software.** [PLATYPUS](https://platypusattack.com/) (IEEE S&P 2021, presented at [rC3](https://media.ccc.de/v/rc3-11404-attacking_cpus_with_power_side_channels_from_software_warum_leaked_hier_strom_en)) used the unprivileged Intel RAPL energy counters to infer data and extract keys: a power side channel with no oscilloscope. A sandbox that exposes energy or power counters to guests hands them a free receiver.
- **2021, the interconnect.** [Volcano (arXiv:2103.04533)](https://arxiv.org/abs/2103.04533) used contention on the on-die mesh interconnect, with no shared cache state at all.
- **2021, automated discovery.** Weber et al., [Osiris (USENIX Security 2021)](https://www.usenix.org/conference/usenixsecurity21/presentation/weber), *fuzzed* x86 instruction sequences to find new timing channels automatically, and reported a cross-core covert channel of 95.2 bit/s **across VMs on AWS**. Automated search for channels is exactly what OpenAI's agents did, with a model in place of a fuzzer.
- **2022, frequency.** Wang et al., [Hertzbleed (USENIX Security 2022)](https://www.usenix.org/conference/usenixsecurity22/presentation/wang-yingchen), showed that dynamic frequency scaling depends on the data being processed, turning power into a timing channel; Intel and AMD did not ship microcode fixes.
- **2023, vector registers.** Moghimi's [Downfall (USENIX Security 2023)](https://www.usenix.org/conference/usenixsecurity23/presentation/moghimi) abused the AVX gather instruction to steal AES keys from **another VM** in under ten seconds on Intel Skylake to Tiger Lake parts ([downfall.page](https://downfall.page/)). The same summer, Tavis Ormandy's [Zenbleed](https://lock.cmpxchg8b.com/zenbleed.html) leaked register contents between processes on the same AMD Zen 2 core, with a public proof of concept.
- **2024, prefetchers.** [GoFetch (USENIX Security 2024)](https://www.usenix.org/conference/usenixsecurity24/presentation/chen-boru) showed Apple's data memory-dependent prefetcher leaking keys from constant-time cryptography ([gofetch.fail](https://gofetch.fail/)): an optimisation that looks at the *values* in memory is a channel by construction.
- **2023 to 2026, GPUs.** Agent sandboxes increasingly involve GPUs, and partitioning them has the same weakness. Zhang et al., [TunneLs for Bootlegging (CCS 2023)](https://casrl.ece.ucf.edu/wp-content/uploads/2023/05/2023-ccs.pdf), found that NVIDIA MIG does not partition the last-level GPU TLB and built a covert channel at up to 31 kbps on a commercial cloud. [Veiled Pathways (MICRO 2024)](https://faculty.ist.psu.edu/wu/papers/Veiled-Pathways.pdf) used the shared PCIe link, and [Behind Bars (USENIX Security 2026)](https://www.usenix.org/conference/usenixsecurity26/presentation/gu-cheng) found cross-instance L2 interference through memory barriers.

- **2024 and 2025, Rowhammer is still everywhere.** Gruss, Heckel and Adamsky's [Ten Years of Rowhammer (38C3)](https://media.ccc.de/v/38c3-ten-years-of-rowhammer-a-retrospect-and-path-to-the-future) was followed at 39C3 by [Rowhammer in the Wild](https://media.ccc.de/v/39c3-rowhammer-in-the-wild-large-scale-insights-from-flippyr-am): of 1,006 datasets collected from 822 real systems with their FlippyR.AM tool, 126 (12.5%) showed bit flips under automated attacks.
- **2025, Spectre across VMs in a public cloud.** At 39C3, Thijs Raymakers' [Spectre in the real world](https://media.ccc.de/v/39c3-spectre-in-the-real-world-leaking-your-private-data-from-the-cloud-with-cpu-vulnerabilities) answered the usual critique that Spectre is impractical by "leaking memory across virtual machine boundaries at a public cloud provider, bypassing mitigations against these types of attacks". The report earned "Google Cloud's highest bounty yet", $151,515. A mitigated, professionally run cloud host still leaked across the VM boundary.
- **2026, a shared service as the channel.** At Black Hat USA 2026, Palo Alto Networks researchers presented "A Billion-User Blast Radius: Owning ChatGPT's Secure Sandbox". [Dark Reading's coverage](https://www.darkreading.com/cloud-security/researcher-claims-control-chatgpt-secure-sandbox) describes a chain that reached persistent root inside the sandbox and used a **shared JFrog Artifactory backend as a covert channel**. OpenAI fixed the Artifactory behaviour within the disclosure window and disputes that the work shows a true sandbox escape or cross-account access. Either way, it is the software version of OpenAI's TLS-cache finding: the package mirror every sandbox talks to is shared state.

The pattern: **every time one shared resource is partitioned, research finds the next one.** Defences raise the cost and lower the bandwidth; they do not reach zero.

A note on why this list leans on these particular results: you don't learn anything about adversarial breakout risk by testing it against a weak boundary. Showing that a timing channel crosses a default, unhardened container with no seccomp filtering proves nothing, because that was never a security boundary to begin with — it was never meant to stop a determined process, so defeating it isn't news. The results above matter because they were run against the best isolation available at the time: NetCAT against Intel's DDIO on real server hardware, Downfall and MDS against production Intel server silicon, Osiris's channel across live AWS VMs, Raymakers' Spectre leak across VM boundaries at a major public cloud. That's the right standard for this kind of claim. Researchers and red teamers testing agent sandboxes should hold themselves to the same bar: break the newest isolation primitive, not last decade's.

## 🏰 Defence in depth

<div class="terms" markdown="1">

**📖 Terms in this section**

- **Defence in depth.** Stacking several independent protections so that one failing does not expose the system. ([NIST glossary](https://csrc.nist.gov/glossary/term/defense_in_depth))
- **Trust domain.** A group of workloads that are allowed to see each other's data. Isolation matters *between* domains, not within one.
- **Capability.** A specific permission an agent holds, such as reading one folder or calling one API. Designing by capability means deciding exactly which permissions each agent gets. ([Capability-based security](https://en.wikipedia.org/wiki/Capability-based_security))
- **Lethal trifecta.** Simon Willison's name for the dangerous combination of access to private data, exposure to untrusted content, and a way to send data out. ([Simon Willison](https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/))
- **Separation kernel and cross-domain solution.** A separation kernel is a small, highly assured kernel whose only job is to keep partitions apart and allow only declared flows between them. A cross-domain solution moves data between networks of different security levels under strict rules. ([Separation kernel](https://en.wikipedia.org/wiki/Separation_kernel) · [Cross-domain solution](https://en.wikipedia.org/wiki/Cross-domain_solution))
- **Credential brokering.** Keeping secrets outside the sandbox and attaching them only to approved outgoing requests, so the agent never holds them (see [the sandboxing post]({% post_url 2026-10-21-sandboxing-untrusted-ai-agents-on-linux %}#-8-what-the-stack-above-still-misses)).

</div>

No single control solves this, so stack them. The layers below run from the cheapest and most effective (design and placement) down to the expensive and partial (hardware partitioning, detection).

### Layer 0: design so collusion does not matter

The strongest control is architectural, and it costs nothing. Assume any two agents that share hardware *can* talk, and make sure that **no agent, and no pair of agents that could collude, holds all three legs of the [lethal trifecta](https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/)**: private data, untrusted content, and a way to communicate externally.

- ✂️ **Split by capability, not just by task.** The agent that can read the secrets should not be able to reach the network, and the agent that can reach the network should never see secrets. That holds only if the two are *also* kept off shared hardware (layer 1); otherwise a covert channel rejoins them.
- 📬 **Give agents an explicit channel.** OpenAI's design already does this: cooperating agents get "a message board shared with allowed teammates". A sanctioned, logged, rate-limited channel removes most of the motive to build an unsanctioned one, and makes unusual behaviour easier to spot. The cross-domain and separation-kernel community has argued this for years: at [Platform Security Summit 2018](https://platformsecuritysummit.com/2018/), Christopher Clark's [Hypervisor-Mediated data eXchange](https://platformsecuritysummit.com/2018/speaker/clark/) talk made the case that how a VMM provides inter-VM communication has "a critical impact on VM isolation properties", Myong Kang (U.S. Naval Research Laboratory) described keeping [separation VMMs](https://platformsecuritysummit.com/2018/speaker/kang/) intact at enterprise scale, and Adventium's Magrana server was designed to isolate enclaves and prevent information flowing between them.
- 🎯 **Keep the payoff small.** Short-lived credentials, scoped to one task, brokered outside the sandbox (see the credential brokering in [the sandboxing post]({% post_url 2026-10-21-sandboxing-untrusted-ai-agents-on-linux %}#-8-what-the-stack-above-still-misses)), mean a slow channel has little worth sending.

### Layer 1: placement removes the hardware channels

<div class="terms" markdown="1">

**📖 Terms in this section**

- **Dedicated host / sole-tenant node.** A physical server rented to a single customer.
- **Kubernetes, node pools, taints and anti-affinity.** Kubernetes runs containers across a cluster of machines (nodes). A node pool is a group of identical nodes; a taint keeps workloads off a node unless they explicitly tolerate it; pod anti-affinity tells the scheduler never to put two kinds of workload on the same node. ([Kubernetes overview](https://kubernetes.io/docs/concepts/overview/) · [GKE node pools](https://cloud.google.com/kubernetes-engine/docs/concepts/node-pools) · [Taints](https://kubernetes.io/docs/concepts/scheduling-eviction/taint-and-toleration/) · [Affinity and anti-affinity](https://kubernetes.io/docs/concepts/scheduling-eviction/assign-pod-node/))
- **L3 domain and NUMA.** An L3 domain is the set of cores that share one last-level cache (a socket, or a core complex on AMD). On NUMA servers each socket also has its own nearby memory. ([Linux NUMA](https://docs.kernel.org/mm/numa.html))

</div>

If two agents must not communicate, they must not share hardware. Make it a scheduler rule, not a hope. This is the only control that closes the microarchitectural channels outright. It does not close channels through services both agents still use, which is why layer 3 and the next section matter:

- 🏠 **Separate physical hosts per trust domain.** Public clouds sell this: [AWS Dedicated Hosts](https://aws.amazon.com/ec2/dedicated-hosts/), [Google Cloud sole-tenant nodes](https://cloud.google.com/compute/docs/nodes/sole-tenant-nodes), [Azure Dedicated Host](https://learn.microsoft.com/en-us/azure/virtual-machines/dedicated-hosts). On Kubernetes, use separate node pools with taints, and pod anti-affinity so that "secrets" agents and "egress" agents never land on the same node.
- 🧩 **At least separate L3 domains.** If a whole host per domain is too expensive, separate sockets or core complexes remove the shared last-level cache, as AWS's "half the largest size fills a socket" rule does. Expose the real cache topology so the scheduler can reason about it.
- 🎮 **Whole GPUs per trust domain.** Given the MIG results above, treat a GPU partition as a performance boundary, not a security one, for agents that must not communicate.
- 🗄️ **Separate storage and caches too.** The report's storage and TLS-cache channels needed no shared CPU at all. Separate disks or volumes and separate cache instances per trust domain.

### Layer 2: harden hosts that must be shared

<div class="terms" markdown="1">

**📖 Terms in this section**

- **Core scheduling.** A Linux feature that tags tasks with a "cookie" so only tasks with the same cookie may share a core's two threads. ([Linux core scheduling](https://docs.kernel.org/admin-guide/hw-vuln/core-scheduling.html))
- **L1D flush and IBPB.** Two clean-ups on a context switch: emptying the L1 data cache, and an indirect branch prediction barrier (IBPB) that stops the branch predictor reusing what it learned from the previous workload. ([Linux: L1TF and L1D flush](https://docs.kernel.org/admin-guide/hw-vuln/l1tf.html) · [Linux: Spectre and IBPB](https://docs.kernel.org/admin-guide/hw-vuln/spectre.html))
- **Cache ways, CAT and resctrl.** A cache is organised into sets, each with a fixed number of slots called ways. Intel CAT and AMD L3 QoS give each workload a subset of the ways, so it can only evict its own lines. Linux manages this through the `resctrl` filesystem, which also offers memory bandwidth allocation (a cap on each workload's memory traffic). ([Cache placement policies](https://en.wikipedia.org/wiki/Cache_placement_policies) · [Linux resctrl](https://docs.kernel.org/filesystems/resctrl.html))
- **MPAM.** Arm's equivalent of CAT and memory bandwidth allocation. ([Arm MPAM](https://neoverse-reference-design.docs.arm.com/en/main/features/mpam.html))
- **Page colouring and indexing functions.** The processor uses hidden formulas (indexing functions) to decide which part of the cache, or which DRAM bank, an address lands in. Colouring hands each VM only the memory pages that land in "its" parts, which requires knowing those formulas. ([Cache colouring](https://en.wikipedia.org/wiki/Cache_coloring))
- **Hyper-V.** Microsoft's hypervisor, used in Azure. ([Hyper-V overview](https://learn.microsoft.com/en-us/windows-server/virtualization/hyper-v/hyper-v-overview))

</div>

When agents of the same trust level share a host (the common case for training and evaluation fleets), shrink the shared surface:

- 🧵 **No SMT sharing across domains.** Disable SMT, or use Linux [core scheduling](https://docs.kernel.org/admin-guide/hw-vuln/core-scheduling.html) so that only tasks with the same cookie run on sibling threads. This removes L1, L2, branch-predictor and port-contention channels between domains.
- 📌 **Pin vCPUs to dedicated physical cores** for the life of the VM, as Nitro does. No time-sharing of a core means no state left behind for the next tenant.
- 🧹 **Flush on switch where cores are shared in time:** L1D flush and IBPB on context switch, with the kernel's [hardware vulnerability mitigations](https://docs.kernel.org/admin-guide/hw-vuln/index.html) enabled and microcode current. A minimum run time for vCPUs (the USENIX Security 2014 scheduler defence) limits how often an attacker can sample.
- 🔋 **Hide power and energy counters from guests.** PLATYPUS turned the RAPL energy interface into a side channel; keep it privileged on hosts and do not pass it through to sandboxes.
- 🧯 **Use ECC memory with target row refresh.** The 39C3 FlippyR.AM data shows Rowhammer-susceptible memory is common in real machines, and Flip Feng Shui shows it can cross VMs.
- 🔁 **Turn off memory deduplication.** Disable [KSM](https://docs.kernel.org/admin-guide/mm/ksm.html) and any page sharing between VMs. This kills Flush+Reload outright.
- 🧱 **Partition the last-level cache.** Intel Cache Allocation Technology and AMD's L3 QoS, managed through Linux [`resctrl`](https://docs.kernel.org/filesystems/resctrl.html), give each VM its own cache ways; memory bandwidth allocation in the same interface limits the bus-contention channel. On Arm servers, [MPAM](https://neoverse-reference-design.docs.arm.com/en/main/features/mpam.html) offers similar controls through the same `resctrl` interface (mainline support is still landing). Plain CAT has too few partitions to separate many tenants; [CATalyst (HPCA 2016)](https://cs.adelaide.edu.au/~yval/pdfs/LiuGYMRHL16.pdf) built a pseudo-locking scheme on top of it to defeat LLC attacks with very small overhead.
- 🎨 **Colour what CAT does not cover.** Microsoft's Marghera, [Principled Microarchitectural Isolation on Cloud CPUs](https://www.microsoft.com/en-us/research/publication/principled-microarchitectural-isolation-on-cloud-cpus/) (CCS 2024 Distinguished Paper), is the most complete published example: on AMD EPYC it identified the shared caches, **coherence directories and DRAM banks**, reverse-engineered their indexing functions, and applied colouring so that VMs never share them, implemented in Hyper-V with small overhead. AMD's [bulletin AMD-SB-7025](https://www.amd.com/en/resources/product-security/bulletin/amd-sb-7025.html) responded to a coherence-directory channel the researchers reported.

Be clear-eyed about the limits:

- 🧵 **Partitioning one structure is not partitioning the core.** TLBleed got through a CAT-partitioned cache via the TLB, and MDS and Downfall leaked through internal buffers and registers. Cache partitioning only helps once SMT sharing between domains is gone and microcode and kernel mitigations are current.
- 🌡️ **Some resources are package-wide.** Frequency and power (Hertzbleed), the interconnect (Volcano) and thermal effects are not partitioned by any of the above.
- 📡 **Some reach the cache from outside.** NetCAT shows that DDIO lets network traffic touch the last-level cache; on hosts that need strong isolation, consider disabling DDIO or confining it to cache ways no tenant uses.

### Layer 3: remove shared software state

<div class="terms" markdown="1">

**📖 Terms in this section**

- **Shared helper services.** DNS resolvers, HTTP proxies, package mirrors and build caches each serve many machines and remember recent requests to answer faster. That memory is shared state.
- **Work-conserving scheduler.** A scheduler that hands idle capacity to whoever wants it. Efficient, but it makes one tenant's load change another tenant's speed. ([Work-conserving scheduler](https://en.wikipedia.org/wiki/Work-conserving_scheduler))
- **cgroups, `cpu.max` and `io.max`.** Linux control groups limit how much CPU, memory and disk input/output a group of processes may use; `cpu.max` and `io.max` set hard caps. ([Linux cgroup v2](https://docs.kernel.org/admin-guide/cgroup-v2.html))
- **IOPS.** Input/output operations per second, the usual measure of storage capacity. ([IOPS](https://en.wikipedia.org/wiki/IOPS))
- **Ephemeral.** Created fresh for one task and thrown away afterwards.

</div>

Two of OpenAI's channels, storage and the TLS certificate cache, were software. These are often the easiest to build and the easiest to fix:

- 🔐 **Per-domain instances of shared services:** TLS session and certificate caches, DNS resolvers, HTTP proxies, package mirrors, build caches, search indexes. Any cache whose hit or miss another agent can time is a channel, and so is any shared service an agent can write to: the Black Hat USA 2026 ChatGPT talk used a shared artifact repository. A per-sandbox egress supervisor, as in NVIDIA OpenShell or Sandlock (both covered in [the sandboxing post]({% post_url 2026-10-21-sandboxing-untrusted-ai-agents-on-linux %}#-nvidia-openshell-the-supervisor-pattern-productised)), gives you this for free.
- ⚖️ **Fixed, non-work-conserving quotas.** A work-conserving scheduler hands idle capacity to whoever wants it, so one agent's load changes another's speed: that *is* the CPU-contention and storage channel. Fixed allocations (`cpu.max`, `io.max` with hard limits, provisioned IOPS) make each agent's performance independent of its neighbours, at the cost of utilisation.
- 🧽 **No shared writable state, and fresh state per task.** Ephemeral sandboxes, no reuse across tasks, no shared `/tmp` or scratch volumes.

### Layer 4: add noise and take away clocks (weak)

<div class="terms" markdown="1">

**📖 Terms in this section**

- **`rdtsc` and the timestamp counter.** An x86 instruction that reads a fast-ticking processor clock; the usual stopwatch for cache attacks. ([Time Stamp Counter](https://en.wikipedia.org/wiki/Time_Stamp_Counter))
- **`getrandom`.** The Linux system call that returns random numbers. ([getrandom(2)](https://man7.org/linux/man-pages/man2/getrandom.2.html))

</div>

Covert channels need a timer. Taking it away helps less than it sounds:

- ⏲️ **Coarsening timers** worked partially for browsers after Spectre, but [Fantastic Timers](https://gruss.cc/files/fantastictimers.pdf) (Schwarz et al., 2017) showed that a counting thread or many other sources rebuild a fine-grained clock. In a VM, trapping `rdtsc` is possible but expensive and still leaves counting threads.
- 🎲 **Deterministic or frozen time** inside a sandbox (Sandlock can freeze time and make `getrandom` deterministic) is useful for reproducible runs, but does not stop a sender and receiver who count work instead of time.
- 📢 **Injecting noise** lowers bandwidth; error correction wins it back. Treat noise as a cost multiplier, never as a boundary.

### Layer 5: detect and respond

<div class="terms" markdown="1">

**📖 Terms in this section**

- **Hardware performance counters.** Registers inside the processor that count events such as cache misses; Linux exposes them through `perf`. ([perf_event_open(2)](https://man7.org/linux/man-pages/man2/perf_event_open.2.html) · [Hardware performance counter](https://en.wikipedia.org/wiki/Hardware_performance_counter))
- **Anomaly detection.** Flagging behaviour that differs from the normal pattern, rather than matching known attacks. ([Anomaly detection](https://en.wikipedia.org/wiki/Anomaly_detection))

</div>

This is what OpenAI relies on for the channels it could not remove:

- 📈 **Hardware performance counters** can flag the cache-miss patterns of Prime+Probe. [CloudRadar (RAID 2016)](https://www2.cs.uh.edu/~acl/cs7370/Paper7-RAID2016.pdf) combined a signature detector for sensitive work with anomaly detection on co-located VMs and reported detection within milliseconds; [Chiappetta, Savaş and Yılmaz (2016)](https://research.sabanciuniv.edu/id/eprint/30194/) detected attacks well before they finished. Detectors trained on known attacks can be evaded by new ones, so treat this as a tripwire.
- 🔉 **Behavioural signals at the infrastructure layer:** regular on/off I/O bursts (the "acoustic modem"), periodic CPU duty cycles, abnormal cache-service hit patterns.
- 🧠 **Monitoring the agent itself.** The report quotes an agent's chain of thought planning the storage channel. Reading reasoning and tool calls for intent ("encode", "timing", "agree a protocol") catches what counters miss, while the reasoning stays legible.
- ⏹️ **Automatic stopping and short lifetimes.** A slow channel needs time; pausing runs on a signal and capping sandbox lifetime bound what can leak.

### Layer 6: assume escape, hold the perimeter

<div class="terms" markdown="1">

**📖 Terms in this section**

- **Egress and default deny.** Egress is outbound traffic. Default deny means everything is blocked unless a rule allows it. ([NIST glossary: egress filtering](https://csrc.nist.gov/glossary/term/egress_filtering) · [NIST glossary: deny by default](https://csrc.nist.gov/glossary/term/deny_by_default))
- **Server-side request forgery (SSRF).** Tricking a server into fetching a URL the attacker chooses, which lets the attacker reach places only the server can. ([OWASP: SSRF](https://owasp.org/www-community/attacks/Server_Side_Request_Forgery))
- **Safety case.** A structured argument, backed by evidence, that a system is safe enough to operate. ([Safety case](https://en.wikipedia.org/wiki/Safety_case))

</div>

OpenAI's other findings are a reminder that covert channels are the *subtle* failure; the blunt ones were VM escapes and internal services that reach the internet. The perimeter must hold with a compromised host:

- 🚪 **Default-deny egress at the cloud layer**, independent of anything on the host.
- 🔗 **Treat every service a host can reach as a possible exit**, directly or through another service: metrics, logging, authentication, DNS. Anything that fetches a URL on request is a server-side request forgery waiting to happen.
- 🧪 **Red-team continuously, with your strongest models.** OpenAI found its count of new findings fell as fixes landed, and made high-compute red-teaming part of the safety case for each training run.
- 🤖 **Search for channels automatically on your own hardware.** Osiris-style fuzzing for timing differences, run on each new CPU and host configuration, finds channels before an agent does. Attackers already automate this; defenders should too.

## 🧮 What "mitigated" means here

<div class="terms" markdown="1">

**📖 Terms in this section**

- **Control plane and orchestrator.** The management systems that decide where workloads run and start and stop them, such as the Kubernetes control plane. ([Kubernetes components](https://kubernetes.io/docs/concepts/overview/components/))
- **Model serving, batching and prefix caching.** Model-serving clusters run many users' requests on the same GPUs. Batching groups requests together to use the GPU efficiently, so one request's speed depends on others. Prefix caching reuses work for prompts that start the same way, so a fast answer reveals that someone else sent a similar prompt recently. ([Orca, OSDI 2022](https://www.usenix.org/conference/osdi22/presentation/yu) · [vLLM: automatic prefix caching](https://docs.vllm.ai/en/latest/features/automatic_prefix_caching.html))

</div>

It is worth being precise, because "mitigated" is easy to over-read. **None of the layers above eliminates covert channels between agents that share anything.** They change three numbers: how much bandwidth a channel has, how much it costs to build, and how likely it is to be noticed.

- 🧱 **Separate hosts remove the hardware channels**: caches, directories, DRAM, frequency, the GPU. That is a real and complete fix for that class.
- 🔁 **Shared services remain.** Agents on separate hosts still share a control plane: the orchestrator, storage cluster, logging and metrics pipeline, offline web cache, and, for most agent systems, the **model-serving cluster itself**. Anything whose response time depends on another tenant's load is a potential channel. LLM serving is a concrete example: [Auditing Prompt Caching in Language Model APIs (ICML 2025)](https://arxiv.org/abs/2502.07776) measured cache sharing across users at seven API providers through response timing alone. Two agents on one inference cluster could, in principle, signal through prefix-cache hits or batching delays without sharing a single CPU. Per-tenant caches and fixed capacity close these; they rarely come for free.
- 📉 **What is left is bandwidth, cost and visibility.** A channel through a shared, noisy, monitored service is slow, takes effort to build, and leaves traces. That matches OpenAI's own conclusion: its channels "carry information slowly", and its response was detection.

So the honest goal is not "agents cannot communicate". It is: **communication between agents that should be separate is slow, expensive, observable, and not worth much**, because layer 0 has made sure no colluding pair can assemble data, untrusted input and a way out. Isolation lowers the odds; capability design bounds the damage.

## 🔬 The frontier

<div class="terms" markdown="1">

**📖 Terms in this section**

- **Microkernel and seL4.** A microkernel keeps the kernel as small as possible and runs everything else as ordinary programs. seL4 is a microkernel with machine-checked mathematical proofs that its code does what its specification says. ([seL4](https://sel4.systems/About/) · [seL4 verification](https://sel4.systems/Verification/) · [Microkernel](https://en.wikipedia.org/wiki/Microkernel))
- **Nested page faults.** Events a hypervisor sees when a VM touches memory that has not been mapped yet; they reveal which memory the VM is using.
- **Randomised and skewed caches; eviction sets.** An eviction set is a group of addresses that compete for the same cache slots, the tool Prime+Probe needs. Randomised caches scramble where each address lands, so attackers cannot work out an eviction set. ([Cache placement policies](https://en.wikipedia.org/wiki/Cache_placement_policies))
- **Confidential computing, SEV-SNP and TDX.** Hardware features (AMD SEV-SNP, Intel TDX) that encrypt a VM's memory and keep even the cloud operator's hypervisor out of it. ([NIST glossary](https://csrc.nist.gov/glossary/term/confidential_computing) · [AMD SEV](https://www.amd.com/en/developer/sev.html) · [Linux: Intel TDX](https://docs.kernel.org/arch/x86/tdx.html))
- **Threat model.** A statement of which attackers and attacks a design defends against, and which it does not. ([OWASP: threat modeling](https://owasp.org/www-community/Threat_Modeling))

</div>

Beyond what you can deploy today, three research directions aim at the root cause:

- 🛡 **Time protection as an OS abstraction.** Ge, Yarom, Chothia and Heiser, [Time Protection: the Missing OS Abstraction (EuroSys 2019, Best Paper)](https://arxiv.org/abs/1810.05345), argue that operating systems need a temporal counterpart to memory protection: colour the caches by domain, flush the core-local state on every domain switch, pad switches to a fixed time. They implemented it in seL4 with under 1% slowdown for most benchmarks, and follow-up work, [Proving the Absence of Microarchitectural Timing Channels](https://arxiv.org/abs/2310.17046), aims to extend seL4's formal proofs from storage channels to timing channels. See the [Trustworthy Systems time-protection project](https://trustworthy.systems/projects/timeprotection/).
- 🔪 **Hardware partitioning without a hypervisor.** [Core slicing (OSDI 2023)](https://www.usenix.org/conference/osdi23/presentation/zhou-ziqiao), from Microsoft Research and UCSD, gives each guest a static slice of cores, memory and virtual I/O enforced by small hardware extensions, removing hypervisor-observable signals such as nested page faults and scheduling. [Stratus (HotCloud 2020)](https://www.usenix.org/conference/hotcloud20/presentation/razavi) argued for clouds that manage microarchitectural resources explicitly, the line of thinking Marghera later made practical.
- 🎰 **Caches that resist conflict attacks by design.** Randomised, skewed caches such as [ScatterCache (USENIX Security 2019)](https://www.usenix.org/conference/usenixsecurity19/presentation/werner) and the fully associative-looking [Mirage (USENIX Security 2021)](https://www.usenix.org/conference/usenixsecurity21/presentation/saileshwar) make eviction-set construction impractical. They are proposals; no mainstream server CPU ships them.

One thing that is **not** on this list: confidential computing. AMD SEV-SNP and Intel TDX protect a guest *from the host*, not guests from each other, and their own threat models leave microarchitectural side channels largely out of scope. An [SEV-SNP primer](https://arxiv.org/html/2608.04039) sums it up: the mitigations raise the bar "but side-channel risk is not eliminated".

## ✅ A checklist by threat level

| Situation | Minimum | Add when stakes rise |
|---|---|---|
| One agent on your own laptop | the OS-level sandbox from [the sandboxing post]({% post_url 2026-10-21-sandboxing-untrusted-ai-agents-on-linux %}#-a-decision-guide); there is no second agent to collude with | nothing specific to covert channels |
| Several cooperating agents, one trust level | an explicit, logged channel between them; per-task credentials | per-agent caches and fixed quotas |
| Agents with different privileges (secrets vs egress) on one fleet | split capabilities; **never co-locate** the two roles (anti-affinity) | separate hosts or at least separate L3 domains; SMT off; KSM off |
| Multi-tenant agents (strangers' code) | microVM per tenant; pinned dedicated cores; SMT off; KSM off; per-tenant service instances | LLC partitioning (CAT, MPAM); whole GPUs per tenant; dedicated hosts for sensitive tenants |
| Frontier models under adversarial evaluation | all of the above, plus default-deny cloud egress, monitored inner layers, automatic stopping | colouring of caches, directories and DRAM (Marghera-style); continuous red-teaming; formal time protection where available |

## 🔗 How this fits the earlier post

[Sandboxing untrusted AI agents on Linux]({% post_url 2026-10-21-sandboxing-untrusted-ai-agents-on-linux %}) argued that the strongest boundary is a second kernel, which is why serious hosted platforms use microVMs (its [Firecracker section]({% post_url 2026-10-21-sandboxing-untrusted-ai-agents-on-linux %}#-5-why-firecracker-rather-than-qemu-and-what-about-gpus) explains the choice). OpenAI's report sharpens that conclusion in two ways:

1. **A second kernel is a boundary for software, not for hardware.** The microVM is still the right primitive, but its guarantees stop at what the hypervisor virtualises. What shares a host is a security decision, and the scheduler is part of the sandbox.
2. **The section 8 items are not theoretical.** That post listed side channels, exfiltration through allowed channels, and the model as a channel among [what the stack still misses]({% post_url 2026-10-21-sandboxing-untrusted-ai-agents-on-linux %}#-8-what-the-stack-above-still-misses). OpenAI has now shown agents building those channels on demand. The fix is the same as before, applied across agents: decide what each agent may hold, and make sure the agents that could talk to each other cannot assemble the lethal trifecta between them.

## 📚 Sources

Point-in-time (checked October 2026).

- The report: [OpenAI, Securing our frontier model training environment (23 October 2026)](https://openai.com/index/securing-our-frontier-model-training-environment/) · screenshot via [@halvarflake](https://x.com/halvarflake) quoting [@scaling01](https://x.com/scaling01) on X
- Foundations: [Lampson, A note on the confinement problem (CACM 1973)](https://dl.acm.org/doi/10.1145/362375.362389) · [Spectre and Meltdown](https://meltdownattack.com/)
- VM and host guidance: [Firecracker production host setup](https://github.com/firecracker-microvm/firecracker/blob/main/docs/prod-host-setup.md) · [Firecracker (NSDI 2020)](https://www.usenix.org/conference/nsdi20/presentation/agache) · [AWS Nitro, the EC2 approach to preventing side channels](https://docs.aws.amazon.com/whitepapers/latest/security-design-of-aws-nitro-system/the-ec2-approach-to-preventing-side-channels.html) · [Linux core scheduling](https://docs.kernel.org/admin-guide/hw-vuln/core-scheduling.html) · [Linux hardware vulnerabilities](https://docs.kernel.org/admin-guide/hw-vuln/index.html) · [Linux KSM](https://docs.kernel.org/admin-guide/mm/ksm.html) · [Linux resctrl](https://docs.kernel.org/filesystems/resctrl.html) · [Arm MPAM](https://neoverse-reference-design.docs.arm.com/en/main/features/mpam.html)
- Dedicated hardware: [AWS Dedicated Hosts](https://aws.amazon.com/ec2/dedicated-hosts/) · [Google Cloud sole-tenant nodes](https://cloud.google.com/compute/docs/nodes/sole-tenant-nodes) · [Azure Dedicated Host](https://learn.microsoft.com/en-us/azure/virtual-machines/dedicated-hosts)
- Cross-tenant attacks: [Ristenpart et al. (CCS 2009)](https://dl.acm.org/doi/10.1145/1653662.1653687) · [Whispers in the Hyper-space (USENIX Security 2012)](https://www.usenix.org/conference/usenixsecurity12/technical-sessions/presentation/wu) · [Flush+Reload (USENIX Security 2014)](https://www.usenix.org/conference/usenixsecurity14/technical-sessions/presentation/yarom) · [Last-Level Cache Side-Channel Attacks are Practical (IEEE S&P 2015)](https://www.ieee-security.org/TC/SP2015/papers-archived/6949a605.pdf) · [Seriously, get off my cloud! (2015)](https://eprint.iacr.org/2015/898) · [DRAMA (USENIX Security 2016)](https://www.usenix.org/conference/usenixsecurity16/technical-sessions/presentation/pessl) · [Attack Directories, Not Caches (IEEE S&P 2019)](https://www.ieee-security.org/TC/SP2019/SP19-Slides-pdfs/Mengjia_Yan_-_10-Mengjia_Yan-MAC-Attack_Directories,_Not_Caches-v2.pdf) · [Volcano (2021)](https://arxiv.org/abs/2103.04533) · [Hertzbleed (USENIX Security 2022)](https://www.usenix.org/conference/usenixsecurity22/presentation/wang-yingchen)
- Black Hat, hacker camps and proofs of concept: [D'Antoine, covert cross-VM communication via out-of-order execution (Black Hat USA 2015)](https://blackhat.com/docs/us-15/materials/us-15-DAntoine-Exploiting-Out-Of-Order-Execution-For-Covert-Cross-VM-Communication-wp.pdf) · [Hello from the Other Side (Black Hat Asia 2017)](https://blackhat.com/docs/asia-17/materials/asia-17-Schwarz-Hello-From-The-Other-Side-SSH-Over-Robust-Cache-Covert-Channels-In-The-Cloud.pdf) and [NDSS 2017 paper](https://www.ndss-symposium.org/ndss2017/ndss-2017-programme/hello-other-side-ssh-over-robust-cache-covert-channels-cloud/) · [Flip Feng Shui (USENIX Security 2016)](https://www.usenix.org/conference/usenixsecurity16/technical-sessions/presentation/razavi) and [SHA2017 talk](https://media.ccc.de/v/SHA2017-95-flip_feng_shui) · [TLBleed (USENIX Security 2018)](https://www.usenix.org/conference/usenixsecurity18/presentation/gras) · [RIDL and Fallout](https://mdsattacks.com/) · [ZombieLoad](https://zombieloadattack.com/) · [NetCAT (IEEE S&P 2020)](https://www.vusec.net/projects/netcat/) · [Osiris (USENIX Security 2021)](https://www.usenix.org/conference/usenixsecurity21/presentation/weber) · [Downfall (USENIX Security 2023)](https://www.usenix.org/conference/usenixsecurity23/presentation/moghimi) · [Zenbleed](https://lock.cmpxchg8b.com/zenbleed.html) · [GoFetch (USENIX Security 2024)](https://www.usenix.org/conference/usenixsecurity24/presentation/chen-boru) · [Dark Reading on the Black Hat USA 2026 ChatGPT sandbox talk](https://www.darkreading.com/cloud-security/researcher-claims-control-chatgpt-secure-sandbox)
- Chaos Communication Congress: [Covert channels in TCP/IP (22C3)](https://media.ccc.de/v/22C3-798-en-tcpip_covert_channels) · [Rowhammer.js (32C3)](https://media.ccc.de/v/32c3-7197-rowhammer_js_root_privileges_for_web_apps) · [What could possibly go wrong with &lt;insert x86 instruction here&gt;? (33C3)](https://media.ccc.de/v/33c3-8044-what_could_possibly_go_wrong_with_insert_x86_instruction_here) · [A Christmas Carol: the Spectres of the Past, Present, and Future (35C3)](https://media.ccc.de/v/35c3-9893-a_christmas_carol_-_the_spectres_of_the_past_present_and_future) · [ZombieLoad (36C3)](https://media.ccc.de/v/36c3-10754-zombieload_attack) · [Practical cache attacks from the network (36C3)](https://media.ccc.de/v/36c3-10884-practical_cache_attacks_from_the_network_and_bad_cat_puns) · [Attacking CPUs with power side channels from software (rC3)](https://media.ccc.de/v/rc3-11404-attacking_cpus_with_power_side_channels_from_software_warum_leaked_hier_strom_en) and [PLATYPUS](https://platypusattack.com/) · [Ten Years of Rowhammer (38C3)](https://media.ccc.de/v/38c3-ten-years-of-rowhammer-a-retrospect-and-path-to-the-future) · [Rowhammer in the Wild (39C3)](https://media.ccc.de/v/39c3-rowhammer-in-the-wild-large-scale-insights-from-flippyr-am) · [Spectre in the real world (39C3)](https://media.ccc.de/v/39c3-spectre-in-the-real-world-leaking-your-private-data-from-the-cloud-with-cpu-vulnerabilities)
- GPUs: [TunneLs for Bootlegging (CCS 2023)](https://casrl.ece.ucf.edu/wp-content/uploads/2023/05/2023-ccs.pdf) · [Veiled Pathways (MICRO 2024)](https://faculty.ist.psu.edu/wu/papers/Veiled-Pathways.pdf) · [Behind Bars (USENIX Security 2026)](https://www.usenix.org/conference/usenixsecurity26/presentation/gu-cheng)
- Defences: [Scheduler-based defences against cross-VM side channels (USENIX Security 2014)](https://www.usenix.org/conference/usenixsecurity14/technical-sessions/presentation/varadarajan) · [CATalyst (HPCA 2016)](https://cs.adelaide.edu.au/~yval/pdfs/LiuGYMRHL16.pdf) · [Marghera, Principled Microarchitectural Isolation on Cloud CPUs (CCS 2024)](https://www.microsoft.com/en-us/research/publication/principled-microarchitectural-isolation-on-cloud-cpus/) · [AMD-SB-7025](https://www.amd.com/en/resources/product-security/bulletin/amd-sb-7025.html) · [Fantastic Timers (2017)](https://gruss.cc/files/fantastictimers.pdf) · [CloudRadar (RAID 2016)](https://www2.cs.uh.edu/~acl/cs7370/Paper7-RAID2016.pdf) · [Chiappetta, Savaş and Yılmaz (2016)](https://research.sabanciuniv.edu/id/eprint/30194/)
- Frontier: [Time Protection (EuroSys 2019)](https://arxiv.org/abs/1810.05345) · [Proving the Absence of Microarchitectural Timing Channels](https://arxiv.org/abs/2310.17046) · [Trustworthy Systems time protection](https://trustworthy.systems/projects/timeprotection/) · [Core slicing (OSDI 2023)](https://www.usenix.org/conference/osdi23/presentation/zhou-ziqiao) · [Stratus (HotCloud 2020)](https://www.usenix.org/conference/hotcloud20/presentation/razavi) · [ScatterCache (USENIX Security 2019)](https://www.usenix.org/conference/usenixsecurity19/presentation/werner) · [Mirage (USENIX Security 2021)](https://www.usenix.org/conference/usenixsecurity21/presentation/saileshwar) · [SEV-SNP primer (2026)](https://arxiv.org/html/2608.04039)
- Platform Security Summit 2018: [programme](https://platformsecuritysummit.com/2018/) · [Hypervisor-Mediated data eXchange (Christopher Clark)](https://platformsecuritysummit.com/2018/speaker/clark/) · [Enterprise Scale Separation VMM Systems (Myong Kang, NRL)](https://platformsecuritysummit.com/2018/speaker/kang/) · [Hypervisor Security: Lessons Learned (Ian Pratt, Bromium)](https://platformsecuritysummit.com/2018/speaker/pratt/)
- LLM serving: [Auditing Prompt Caching in Language Model APIs (ICML 2025)](https://arxiv.org/abs/2502.07776)
- Related: [The lethal trifecta (Simon Willison)](https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/) · [Sandboxing untrusted AI agents on Linux]({% post_url 2026-10-21-sandboxing-untrusted-ai-agents-on-linux %})
