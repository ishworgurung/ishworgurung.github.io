# Sandboxing untrusted AI agents on Linux

An AI coding agent runs code that nobody reviewed: shell commands, generated scripts, `pip` and `npm` installs, tool plugins. It can be steered by prompt injection hidden in a web page or a dependency, and even a well-meaning agent can `rm -rf` the wrong tree. So what does a sandbox for that code actually have to do on Linux, and why is "minimal" so hard?

### TL;DR

A Linux sandbox is a **stack of partial mechanisms that all share one host kernel**. Each layer stops one class of thing and nothing else, and there is no single switch. The strongest boundary is a *second kernel*, which means a virtual machine. That is why the serious hosted products are microVMs, and why the OS-level tools (Landlock, seccomp, bubblewrap) are best kept for code you mostly trust on a machine you control.

The mechanisms involved, roughly from weakest to strongest boundary:

| Layer | Question it answers | What it does **not** stop |
|---|---|---|
| **cgroup v2** | how *much*? | anything within quota; not a security boundary |
| **user namespace** | *who* am I? | kernel bugs reachable by unprivileged users |
| **pid/net/ipc/uts namespaces** | what can I *see*? | the shared kernel behind every view |
| **mount namespace + `pivot_root`** | what *filesystem*? | files under the roots you granted |
| **capabilities + `no_new_privs`** | can I *re-privilege*? | syscalls that need no privilege |
| **Landlock** | which *paths* (and increasingly sockets, signals)? | non-filesystem syscalls |
| **seccomp-bpf** | which *syscalls*? | anything an allowed syscall can reach |

> Everything here is point-in-time (October 2026). Details of products and papers move monthly, so verify specifics before relying on them. Sections marked "general knowledge" were not checked against sources.

---

## 1. The current challenges

**One shared kernel is the whole problem.** Namespaces, cgroups, capabilities, seccomp and Landlock all run *in* the host kernel. A single kernel vulnerability reachable from the sandbox is a full escape. The Linux syscall surface is enormous (hundreds of syscalls, each with many argument shapes), and features like io_uring *add* surface. Enabling unprivileged user namespaces, which you need to sandbox without root, itself exposes more kernel code to untrusted callers and has been a recurring source of local privilege-escalation CVEs.

**Agents need capability, which fights confinement.** A file-only agent is easy to box. A *useful* coding agent wants to install packages (network), spawn compilers and test runners (exec and many syscalls), read large parts of the filesystem, and sometimes use GPUs. Every capability you grant is attack surface you re-open. The art is *least privilege per task*, which is exactly what is hard to specify up front.

**Network egress is the real prize, and the hardest to get right.** The damaging outcomes are network actions: exfiltrating secrets, reaching internal services, hitting the cloud metadata endpoint (`169.254.169.254`), pulling a malicious payload. A binary on/off switch (blocking `AF_INET` sockets in seccomp) is too coarse for an agent that must reach a package registry. A *filtering proxy* is the right tool, but it needs TLS interception or a domain allow-list, plus care that the agent can't just talk to `localhost` services or use DNS as a covert channel.

**Secrets and ambient authority leak in surprising ways.** Environment variables, inherited file descriptors, cloud instance-metadata credentials, `~/.aws`, `~/.ssh`, a mounted Docker socket, a `GITHUB_TOKEN` in the environment: none of these are "files the agent opened", so a filesystem sandbox alone misses them. A 2026 security note on AWS Bedrock AgentCore argued that its code-interpreter microVM still exposes execution-role credentials via the metadata service; AWS considers that by design. Whoever is right, the lesson stands: *isolation of the compute does not imply isolation of the credentials*.

**Views leak the host.** Inside a container, `/proc/cpuinfo`, `/proc/meminfo` and `/proc/stat` show the *host's* numbers unless something virtualises them (`lxcfs`). That is the same reason `top` in a container shows host CPU and steal time. Information disclosure is a weaker threat than escape, but it feeds fingerprinting and side channels.

**Correctness is a sequencing minefield.** The layers have prerequisite chains and failure modes. `no_new_privs` must be set before an unprivileged seccomp filter. A gid map needs `setgroups=deny`. A bind mount can't go read-only in one step on older kernels. Landlock rights must be masked to the running ABI or `restrict_self` fails. Seccomp goes in last, so your own setup syscalls aren't filtered. Each is a place to silently under-confine, and **a half-applied sandbox is worse than none**, because you think you're protected. A good sandbox aborts on any layer that fails rather than running the agent half-confined.

**Deny-lists have traps.** A syscall deny-list is deceptively easy to under-build:

- **io_uring.** It can perform socket, connect and `openat` operations *as ring operations*, without issuing those syscalls, so a naive seccomp network block is sidestepped by an agent that opens a ring and connects through it. Any deny-list that ignores io_uring is porous.
- **The x32 ABI.** On x86-64, x32 syscalls carry the same `AUDIT_ARCH_X86_64` token but OR `0x40000000` into the number. A filter that only compares plain numbers lets the x32 variant of every denied call through.
- **`ioctl(TIOCSTI)`.** A process sharing the controlling terminal can push bytes into the terminal's input queue, and the parent shell runs them after the sandbox exits. That is a full escape that touches no file and opens no socket.
- **Arch confusion.** A 32-bit (`i386`) calling convention uses different numbers for different calls, so a filter must check the architecture first.

Each hole is invisible if you reason about syscalls by name. This is why serious sandboxes invert to **deny-by-default** and lean on audited, maintained profiles instead of a hand-rolled list.

**Portability and kernel-version drift.** Landlock needs Linux 5.13 or newer and grows new abilities per ABI (network connect scoping, IPC scoping and pathname-unix-socket scoping are recent or in flight). Seccomp syscall numbers are per-architecture. Unprivileged user namespaces are disabled on some hardened distributions, and Ubuntu 24.04's AppArmor policy blocks bubblewrap's user namespaces by default. A sandbox that works on your machine may fail open elsewhere.

**Performance and density.** Hosted agent platforms run *many* sandboxes and want sub-second cold starts and snapshot/restore. OS-level sandboxes are cheap (microseconds to milliseconds) but weak. VMs are strong but were historically slow to boot, which is the gap Firecracker plus snapshotting closed, and why microVMs became viable for this at all.

---

## 2. Where the future is moving

- **MicroVMs are becoming the default for *untrusted* code, not the exception.** Firecracker-style microVMs give each sandbox its own kernel at roughly 100 to 150 ms cold start, and snapshot/restore (lazy page-fault-driven restore via `userfaultfd`) makes per-task or per-step forking cheap. The hosted market (E2B, Vercel Sandbox, AWS AgentCore) has largely standardised on this.

- **A tiered "right-sized isolation" model is winning over one-size-fits-all.** Guidance is converging across 2026 write-ups: OS-level confinement (Landlock, seccomp, bubblewrap) for *trusted* code on *trusted* machines; gVisor as a middle tier; microVMs and Kata for *untrusted, multi-tenant* code. The interesting engineering is in *choosing* and *composing* tiers per workload, not in one perfect sandbox.

- **Landlock is maturing into a real agent primitive.** It began filesystem-only (Linux 5.13). ABI 6 (Linux 6.12) added IPC and signal *scoping*, and later work adds network and unix-socket scoping. That turns Landlock from "restrict files" into "restrict a process tree's whole resource reach", unprivileged and self-applied, which is ideal for a CLI agent that sandboxes itself.

- **seccomp-notify supervisors put user-space policy in the loop.** Instead of a static allow/deny BPF program, the kernel can *forward* a syscall to a supervisor process that decides at runtime and can even virtualise the effect. The 2026 research prototype **Sandlock** (Wang and Zheng, [arXiv:2605.26298](https://arxiv.org/abs/2605.26298)) combines Landlock and seccomp with a seccomp-notification supervisor to get dynamic network decisions, HTTP-level access control, and TOCTOU-safe inspection of `execve` arguments, all unprivileged, with about 5 ms startup overhead. "Static policy compiled into the kernel, plus a narrow supervisor for the hard cases" is likely where lightweight agent sandboxes head.

- **Orchestration is standardising.** The Kubernetes SIG's **agent-sandbox** (a `Sandbox` CRD with warm pools, delegating isolation to gVisor or Kata via `RuntimeClass`) signals that "a sandbox" is becoming a first-class, schedulable object with stable identity, persistent storage and a sub-second claim from a pre-warmed pool, rather than an ad-hoc `docker run`.

- **Snapshotting is a product feature, not just a speed trick.** Pause/resume, fork-a-running-state, and "close your laptop, the agent keeps going" (AWS AgentCore) are becoming table stakes. That pushes toward VM-level isolation, because snapshotting a whole guest is cleaner than checkpointing a process tree (CRIU is fragile).

- **Egress control moves up the stack.** The trend is away from "block all sockets" toward *identity-aware filtering proxies* with per-domain allow-lists and audit. Agents must reach *some* network, and the useful policy is about *where*, not *whether*.

---

## 3. Contenders vs the status quo

The status quo for running arbitrary code has been **OCI containers** (Docker and `runc`): namespaces, cgroups, a default seccomp profile and dropped capabilities. They have good ergonomics and a huge ecosystem, but they share a kernel, so they are insufficient for genuinely untrusted, multi-tenant code. The contenders differ mainly in **where the trust boundary sits**.

| Approach | Boundary | Isolation strength | Start | Cost / density | Best fit for agents |
|---|---|---|---|---|---|
| `chroot` | path resolution only | ~none (escapable) | instant | free | not a sandbox |
| **bwrap / nsjail / Landlock launchers** | namespaces, shared kernel | low to moderate | ~ms | very high | trusted code; per-call confinement |
| **OCI container** (`runc`) | namespaces + seccomp, shared kernel | moderate | ~100 ms | very high | semi-trusted; the status quo |
| **gVisor** | user-space kernel intercepts syscalls | high (small host surface) | ~100 to 300 ms | high | untrusted code without a VM; some compatibility cost |
| **Kata / Firecracker / Cloud Hypervisor** | separate guest kernel (KVM) | highest (on Linux) | ~100 to 150 ms, faster from snapshot | moderate | untrusted, multi-tenant: the serious default |
| **WASM runtime** | capability-based VM, no syscalls | high for *what it supports* | ~ms | very high | narrow, pure-compute tools |

Moving down the table trades **density and compatibility** for **isolation strength**. Containers sit in the middle and are fine for code you mostly trust. The direction of travel for *untrusted* agent code is toward gVisor and especially microVMs, with OS-level tools relegated to the innermost layer or to trusted single-user setups.

A few nuances the table flattens:

- **gVisor vs microVM** isn't strictly "weaker vs stronger". gVisor shrinks the *host* syscall surface to a few dozen but adds its own (smaller) kernel's surface and some workload incompatibility. A microVM gives a full, familiar kernel per guest, but a larger in-guest surface, and the KVM/virtio boundary is the thing to trust.
- **WASM** is the strongest *per-feature* boundary (no ambient syscalls at all), but it can only run what has been compiled to it and wired to explicit host capabilities. It is great for a sandboxed function, not for "run this arbitrary repo's test suite".
- **Composition beats any single row.** Real systems stack them: OS-level confinement *inside* a container *inside* a microVM, with a filtering proxy on egress. Each layer catches what the one inside it missed.

---

## 4. How leading systems sandbox untrusted AI agents

Two families, by where they run.

### Local coding-agent CLIs (the OS-level tier)

- **OpenAI Codex CLI.** On Linux it uses **Landlock and seccomp**: Landlock restricts the filesystem to user-approved directories, and seccomp blocks outbound network by default. A newer path vendoring **bubblewrap** sits behind a feature flag. On macOS it uses **Seatbelt** (`sandbox-exec`). Its docs warn that inside Docker the needed APIs may be unavailable and sandboxing can fail, which is the portability problem from section 1 made concrete.
- **Claude Code.** Anthropic's **sandbox-runtime** uses **bubblewrap** for filesystem isolation on Linux, plus a **SOCKS5 filtering proxy** for domain-level egress control (it needs `bubblewrap` and `socat`; an optional seccomp filter adds unix-socket blocking). On macOS it uses `sandbox-exec`. By default it warns and runs unsandboxed if dependencies are missing, with a `failIfUnavailable` hard-fail mode for managed deployments. That is the "fail open vs fail closed" decision made visible.
- **Gemini CLI.** The sandbox is **opt-in** (off by default) and pluggable: macOS Seatbelt, or Docker, Podman, **gVisor** or LXC containers. It mainly limits the filesystem to the project directory.

These share a fundamental limit that several guides state: bubblewrap and Seatbelt run on the **same kernel** as the host, so they offer little against kernel exploits. They are suitable mainly for *trusted* code on *trusted* machines, the right tool for a developer running an agent on their own laptop and not for a multi-tenant service executing strangers' code.

### Hosted execution platforms (VM or user-space-kernel tier)

- **E2B.** Each sandbox is a **Firecracker microVM** with its own kernel. The core is Apache-2.0 and self-hostable, with roughly 150 ms cold start from snapshot, and snapshot-based pause/resume is central. It is widely treated as the reference open option.
- **Vercel Sandbox.** **Firecracker microVMs**, with snapshots and time-limited sessions.
- **Modal.** Sandboxes default to **gVisor**, with a VM runtime (own kernel) added for stronger isolation, and filesystem-snapshot persistence. A standout for **GPU** inside the sandbox.
- **AWS Bedrock AgentCore Code Interpreter.** A per-session **isolated Linux microVM** with a persistent workspace and "keep running while your laptop is closed" semantics (see the credential-exposure critique in section 1).
- **Cloudflare Sandbox SDK.** Built on Cloudflare **Containers**, one sandbox per VM. Its docs recommend per-user sandboxes because everything in one sandbox shares resources. Third parties dispute the exact mechanism, and it is pre-1.0.
- **Daytona.** Fast-create persistent workspaces with snapshots and forks. Default isolation is reported as containers on the host kernel, with optional **Kata** or Sysbox for stronger isolation. Licensing and status were in flux in 2026, so verify before relying on it.
- **Kubernetes `agent-sandbox`.** Not an isolator itself: a `Sandbox` CRD plus controller that schedules pods onto **gVisor or Kata** via `RuntimeClass`, with **warm pools** for sub-second starts. It is the orchestration story for self-hosting agent sandboxes at scale.

### The pattern across all of them

1. **Tiered by trust.** Local CLIs accept the shared-kernel tier because the code is semi-trusted and the machine is the user's own. Hosted platforms running *arbitrary* users' code almost universally reach for a **second kernel** (Firecracker) or a **user-space kernel** (gVisor).
2. **Egress is a filtering proxy, not a toggle.** The serious systems control *which* domains, with audit, because agents need package registries and APIs.
3. **Snapshot/restore is a first-class feature**, which itself pushes toward VM isolation.
4. **Least privilege per task**, increasingly expressed declaratively (Landlock rulesets, Kubernetes CRDs, per-call policy) rather than one static container configuration.

---

## 5. Why Firecracker rather than QEMU, and what about GPUs?

*Firecracker-vs-QEMU is general knowledge. The GPU landscape comes from vendor blogs that sometimes disagree, so verify specifics.*

### Could plain QEMU do the job of Firecracker?

Yes. Both put the guest behind hardware virtualisation with its own kernel, so the *kind* of boundary is the same. The difference is what it costs to get it:

- **Tiny device model.** QEMU emulates a very wide range of hardware (legacy devices, USB, many NICs and disk controllers, graphics). Firecracker exposes a handful of virtio devices, a serial port and a minimal keyboard controller. Less emulation code reachable from the guest means less attack surface, and many past QEMU escapes came from obscure emulated devices.
- **Boot time and footprint.** About 100 to 150 ms and a small per-VM memory overhead, against a slower start for a stock QEMU machine type with firmware. Agent workloads create thousands of short-lived sandboxes, so this matters.
- **Density.** Low overhead per VM lets a host pack far more sandboxes.
- **Snapshots.** Snapshot/restore is a core feature, and it is what "resume a warm sandbox" products build on.
- **Built for multi-tenancy.** Written by AWS for Lambda and Fargate in Rust, and run under a *jailer* (seccomp, namespaces, cgroups).

QEMU is the better choice when you need hardware Firecracker lacks (GPU passthrough, USB, other CPU architectures, Windows or macOS guests) or you want the most mature, widely supported tool. QEMU's `microvm` machine type with no firmware and a stripped config gets most of Firecracker's benefits, and Cloud Hypervisor and crosvm are other minimal VMMs. Firecracker is not the only way; it is the one managed platforms standardised on.

### Firecracker and GPUs

Stock Firecracker cannot give a guest a GPU. Its minimal device model has no PCI bus, which rules out PCIe passthrough, and that is a consequence of the design, not an oversight. (Firecracker's PCI story has been changing; check the current release notes.) For GPU workloads, sources point to QEMU or Cloud Hypervisor instead. The options in use:

| Model | Boundary | Catch |
|---|---|---|
| **VFIO passthrough into a VM** (QEMU, Cloud Hypervisor, Kata) | Hypervisor, with exclusive device ownership | One GPU per tenant. Naive passthrough can re-open the boundary through GPU DMA, so it needs an IOMMU and care. |
| **gVisor + `nvproxy`** | Filtered NVIDIA ioctls forwarded to the host driver | Weaker than a VM: the boundary is the driver's ioctl surface. Supports only selected driver versions and CUDA commands. |
| **NVIDIA MIG** | Hardware-level partitions of one card | Supported data-centre GPUs only (A100, H100). Each partition can go to a different VM. |
| **Time-slicing / vGPU** | Little (time-slicing); licensed vendor driver (vGPU) | Time-slicing suits only low-sensitivity workloads. |
| **Plain container + NVIDIA Container Toolkit** | Shared host kernel and driver | Fine for trusted code, poor for untrusted. |
| **No GPU in the sandbox** | n/a | Run agent glue code in a microVM and call inference over an API. Often enough. |

Why it is hard: GPU drivers are large and complex, and passing a device through means the guest drives real hardware over DMA. That widens exactly the surface a microVM was chosen to shrink, and it makes cheap snapshot and migration much harder. The shared-kernel tier has the mirror-image property: a GPU is just `/dev/nvidia*` files you allow through Landlock, which is simple but leaves the driver reachable from the sandboxed process.

### What vendors sell for GPU isolation

Either a **whole VM or bare-metal instance with a GPU attached** (the EC2 model: one customer per GPU, isolation is the hypervisor's), or a **managed GPU sandbox**:

- **Modal.** gVisor with the proxied NVIDIA driver (not passthrough); a wide GPU range from T4 up to H100, H200 and B200; one GPU reserved per sandbox; not self-hostable.
- **Daytona.** Reportedly VFIO passthrough, one dedicated GPU per ephemeral sandbox VM. Sources conflict on availability, so check its docs.
- **Northflank.** gVisor where nested virtualisation is unavailable; L4 through H200.
- **Fly.io.** L40S machines (single secondary source).
- **E2B.** CPU-only per the sources.

### The leading edge

- **Confidential-computing GPUs.** H100 and Blackwell can encrypt GPU memory and attest the device. NVIDIA's reference architecture runs Kata confidential VMs on AMD SEV-SNP or Intel TDX with VFIO passthrough. This protects tenants from the *host operator*, not just from each other. The cost is performance; recent work on Blackwell confidential computing is about recovering LLM-serving throughput lost to it.
- **A Type-1 hypervisor per workload** (Edera, per a September 2026 comparison): VM-grade isolation while still sharing the card, instead of dedicating a whole GPU to each tenant.
- **Per-sandbox GPUs on cheap isolation.** The commercial push is ephemeral sandboxes that each get a GPU, but only Modal's whole-card approach is consistently documented.

For a GPU SaaS with mutually untrusted tenants: dedicated-GPU VMs with VFIO (Kata or Cloud Hypervisor), plus confidential computing if tenants distrust the operator; MIG where a card must be subdivided; gVisor with `nvproxy` as the cheaper middle option whose boundary is the ioctl surface.

---

## 6. Research and proposals for the next 5 to 10 years

The literature search turned up little peer-reviewed work and mostly vendor blogs, so each item below is marked by where it comes from, and the forecasts at the end are opinion.

### Papers (arXiv, 2026 unless noted)

- **Tyche, composable isolation** ([arXiv:2507.12364](https://arxiv.org/pdf/2507.12364)). A hardware and monitor primitive that unifies enclaves, VMs and containers, so a tenant can carve out its own isolated domain without trusting the layer below. The most direct research answer to "how do you compose isolation layers".
- **Threat model, taxonomy and measurement.** [AI Sandboxes (arXiv:2606.18532)](https://arxiv.org/html/2606.18532v1) and [AI Code Sandboxes: A Comparative Security Study (arXiv:2606.08433)](https://arxiv.org/pdf/2606.08433) cover attack surface, leakage, CVE history and patch cadence. They give shared vocabulary and numbers instead of vendor claims.
- **SandboxEscapeBench** ([arXiv:2603.02277](https://arxiv.org/html/2603.02277v1)). Measures whether frontier LLMs can escape Docker/OCI sandboxes. It makes the attacker side measurable, which is likely to drive the field: a sandbox claim can now be tested against a model.
- **Learned capability governance** ([arXiv:2604.11839](https://arxiv.org/abs/2604.11839)). Learns the smallest tool set each task type needs, motivated by a reported 15x overprovisioning ratio. The paper's naming differs between versions, so read it with care.
- **Mandatory access control for LLM agents** ([arXiv:2601.11893](https://arxiv.org/pdf/2601.11893)). A MAC framework against privilege escalation between agent components.
- **Shrinking the shared kernel from inside.** [Dynamic sandboxing for unprivileged eBPF (arXiv:2308.01983)](https://arxiv.org/pdf/2308.01983) and [compartmentalizing monolithic kernels (arXiv:2404.08716)](https://arxiv.org/pdf/2404.08716), relevant because the shared kernel is the weak point of every tier except VMs.

### Kernel proposals and standards

- **Landlock extensions**, including IPC and unix-socket scoping (see the LWN and kernsec links below). Landlock's default is ambient authority, so every workload still needs an explicit policy.
- **eBPF LSM enforcement** and per-sandbox network policy, for example per-sandbox TAP devices with eBPF rules. Reported as becoming the standard pattern for agent network isolation, though the sources are vendor guides, not papers.
- **WASI and the Component Model.** A component starts with no ambient authority and can only do what the host grants. Best for tools and functions you can compile, not yet a full dev environment. GPU access (`wasi:webgpu`) is a Phase 2 proposal.

### Directions not covered by the search (general knowledge)

- **CHERI** hardware capabilities (Cambridge and ARM Morello) and **seL4**, the verified kernel: capability enforcement in hardware or by proof, instead of by a large trusted kernel.
- **Confidential VMs (AMD SEV-SNP, Intel TDX) and confidential GPUs**, covered above.
- **In-process isolation** with Intel MPK and ARM MTE.
- **Memory-safe VMMs and Rust in the kernel**, which shrink the bug surface beneath every layer.

### Where this seems to be heading (opinion)

1. **The shared kernel is the weak point.** The long-term answers either avoid it (microVMs, confidential VMs) or shrink it (Landlock-style scoping, compartmentalization, memory safety).
2. **Policy will matter as much as mechanism.** Static allow-lists overprovision, so least privilege *per task*, possibly learned, is where the agent-specific papers are going.
3. **Composable isolation looks like the most promising architecture.** Tyche-style designs would let a tenant nest its own boundary instead of trusting the provider's.

Gaps: I found no paper proposing microVM snapshots specifically for agent isolation, and none on seL4- or CHERI-based agent sandboxes.

---

## 7. Why isn't OpenBSD the answer?

*General knowledge, not checked against sources.*

OpenBSD is one of the most security-focused commodity OSes, so it is a fair question. It is a strong answer for the OS-level tier, but it does not change the tiering in section 3.

Two framing points. The tiers are about **where the trust boundary sits**, not only about CPU-level isolation. And OpenBSD is also a **shared-kernel** design, so a kernel bug still breaks every sandbox on the machine.

### What OpenBSD does well

- **`pledge(2)` and `unveil(2)`** are arguably better designed than seccomp and Landlock. Coarse promises such as `stdio rpath inet` are hard to get wrong, where seccomp filters are easy to write badly. `unveil` limits which parts of the filesystem a process can see.
- **Privilege separation** is a core convention in its daemons.
- **Exploit mitigations on by default** (W^X, ASLR, stack protector, removal of old code), a small audited codebase, and a good security track record.

### Why it is not enough for this problem

1. **The shared-kernel limit applies to it too.** A smaller, cleaner kernel makes an exploit less likely, not impossible. For mutually untrusted tenants, hosted platforms want a second kernel, which OpenBSD alone does not give you.
2. **Pledge is cooperative.** The program calls `pledge` on itself. That works for software written or patched for it, as in base OpenBSD, but not for wrapping arbitrary code such as an agent running `pip install` and a shell. You want an external wrapper that confines a process that does not cooperate, which is what bubblewrap and Landlock launchers do. OpenBSD has nothing quite like that.
3. **Missing building blocks.** It has rlimits and `login.conf`, but nothing like cgroups v2 for memory, PIDs and CPU, and no unprivileged user-namespace-style containers. It has no seccomp user-notify equivalent for a supervisor that vets syscalls. Egress control is `pf`, which is good but needs root and is not per-process or per-domain.
4. **Ecosystem and hardware.** Agents, toolchains, Python wheels, Node and Docker images assume Linux, and CUDA does not run on OpenBSD, so GPU workloads are out. Its hypervisor, `vmm(4)`/`vmd`, is much less mature than KVM, and the microVM tooling (Firecracker, gVisor, Kata) and snapshot/restore are all Linux and KVM.
5. **Operations.** Cloud vendors do not offer it the way they offer Linux, so there are few managed options.

### Where it fits

OpenBSD works well as the host or guest for a small, auditable control plane or an egress proxy. For the part that runs untrusted agent code, the tooling is on Linux. For one trusted-ish agent on your own machine, `pledge` and `unveil` are a good fit and arguably simpler than the Linux stack; they just do not scale to the multi-tenant case.

---

## A decision guide

- **Running an agent on your own laptop, your own code?** The OS-level tier (bubblewrap as in Claude Code, or Landlock plus seccomp as in Codex) is proportionate. Add a filtering proxy if the agent has network.
- **Running *your users'* code, multi-tenant?** Do not stop at containers. Use a **microVM** (Firecracker, E2B, Kata) or at least **gVisor**, and treat the VM as the boundary. Put OS-level confinement *inside* it as defence in depth.
- **A narrow, pure-compute tool?** Consider **WASM**: the strongest per-feature boundary and trivially dense.
- **Whatever you pick:** control egress by domain with audit, strip ambient credentials (environment, metadata, mounted sockets, `~/.ssh`), cap resources with cgroups (fork bombs are cheap), and **fail closed**. A sandbox that silently runs unconfined is the worst outcome.

---

## Sources

Point-in-time (checked October 2026); vendor docs and 2026 analyses, so verify before relying on specifics.

- Landscape lists: [awesome-AI-sandbox](https://github.com/webcoyote/awesome-AI-sandbox) · [awesome-ai-coding-sandboxes](https://github.com/fhiltscher/awesome-ai-coding-sandboxes) · [coding agent sandboxes list, 2026-05](https://gist.github.com/wincent/2752d8d97727577050c043e4ff9e386e)
- Papers: [Sandlock: Confining AI Agent Code with Unprivileged Linux Primitives (arXiv:2605.26298)](https://arxiv.org/abs/2605.26298) · [AI Code Sandboxes: A Comparative Security Study (arXiv:2606.08433)](https://arxiv.org/pdf/2606.08433)
- Guides: [Northflank, how to sandbox AI agents](https://northflank.com/blog/how-to-sandbox-ai-agents) · [digitalapplied, 3 isolation patterns](https://www.digitalapplied.com/blog/ai-agent-sandboxing-isolation-patterns-2026) · [Notes on sandboxing untrusted code](https://gist.github.com/mavdol/2c68acb408686f1e038bf89e5705b28c)
- Codex: [OpenAI Codex security](https://developers.openai.com/codex/security) · [Codex sandboxing architecture](https://www.mintlify.com/openai/codex/architecture/sandboxing) · [Simon Willison, Codex sandbox investigation](https://simonwillison.net/2025/Nov/9/codex-sandbox-investigation/)
- Claude Code and Gemini CLI: [Claude Code sandboxing docs](https://code.claude.com/docs/en/sandboxing) · [anthropic sandbox-runtime](https://github.com/Electroid/sandbox-runtime) · [Gemini CLI sandboxing](https://geminicli.com/docs/cli/sandbox/)
- Landlock: [Landlock news and ABI history](https://landlock.io/news/5/) · [LWN, Landlock IPC scoping](https://lwn.net/Articles/989073/) · [LSM pathname unix-socket scope (2026)](https://kernsec.org/pipermail/linux-security-module-archive/2026-February/055149.html)
- Hosted platforms: [E2B vs Daytona vs Modal](https://www.developersdigest.tech/blog/ai-agent-code-sandbox-comparison-2026) · [E2B, Daytona and Firecracker overview](https://www.spheron.network/blog/ai-agent-code-execution-sandbox-e2b-daytona-firecracker/) · [self-hostable comparison](https://bex.co/blog/2026/09/14/ai-agent-sandbox-market-e2b-modal-daytona)
- Kubernetes: [Running Agents with Agent Sandbox](https://kubernetes.io/blog/2026/03/20/running-agents-on-kubernetes-with-agent-sandbox) · [agent-sandbox docs](https://agent-sandbox.sigs.k8s.io/docs/getting_started/overview/) · [Google OSS blog, why Kubernetes needs an agent standard](https://opensource.googleblog.com/2025/11/unleashing-autonomous-ai-agents-why-kubernetes-needs-a-new-standard-for-agent-execution.html)
- AWS: [hosting coding agents on Bedrock AgentCore](https://aws.amazon.com/blogs/machine-learning/its-safe-to-close-your-laptop-now-hosting-coding-agents-on-amazon-bedrock-agentcore/) · [CSA, AgentCore as enterprise attack surface](https://labs.cloudsecurityalliance.org/research/csa-research-note-bedrock-agentcore-enterprise-attack-surfac/)
- GPU isolation: [Northflank, GPU sandboxes](https://northflank.com/blog/gpu-sandboxes) · [GPU isolation fault line: gVisor, Kata, Edera](https://bex.co/blog/2026/09/11/gpu-isolation-fault-line-gvisor-kata-edera) · [NVIDIA Confidential Containers reference architecture](https://docs.nvidia.com/datacenter/cloud-native/confidential-containers/latest/overview.html) · [gVisor GPU support](https://gvisor.dev/docs/user_guide/gpu/) · [Multi-tenant GPU security](https://introl.com/blog/multi-tenant-gpu-security-isolation-strategies-shared-infrastructure-2025) · [Blackwell confidential-computing LLM serving (arXiv:2606.23969)](https://arxiv.org/pdf/2606.23969) · [One GPU per sandbox: Modal vs E2B and Daytona](https://bex.co/blog/2026/09/05/modal-gpu-sandbox-vs-daytona-e2b-cpu-isolation) · [What are GPU sandboxes?](https://www.thundercompute.com/blog/what-are-gpu-sandboxes) · [E2B vs Daytona vs Modal](https://drydock.si/guides/e2b-vs-daytona-vs-modal)
- Research: [Tyche (arXiv:2507.12364)](https://arxiv.org/pdf/2507.12364) · [AI Sandboxes: threat model and taxonomy (arXiv:2606.18532)](https://arxiv.org/html/2606.18532v1) · [SandboxEscapeBench (arXiv:2603.02277)](https://arxiv.org/html/2603.02277v1) · [Learned capability governance (arXiv:2604.11839)](https://arxiv.org/abs/2604.11839) · [MAC for LLM agents (arXiv:2601.11893)](https://arxiv.org/pdf/2601.11893) · [Unprivileged eBPF dynamic sandboxing (arXiv:2308.01983)](https://arxiv.org/pdf/2308.01983) · [Kernel compartmentalization (arXiv:2404.08716)](https://arxiv.org/pdf/2404.08716) · [Cosmonic, choosing an agent sandbox](https://cosmonic.com/ai-sandbox/choosing-an-agent-sandbox/) · [yeet.cx, sandbox an AI coding agent on Linux](https://yeet.cx/topical-takes/sandbox-ai-coding-agent-linux) · [h5i, sandboxing AI agents landscape](https://h5i.dev/blog/sandboxing-ai-agents-landscape/)
