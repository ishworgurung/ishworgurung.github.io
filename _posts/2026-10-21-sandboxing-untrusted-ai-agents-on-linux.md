---
title: "Sandboxing untrusted AI agents on Linux"
---

An AI coding agent runs code before any human has reviewed it: shell commands, generated scripts, `pip` and `npm` installs, tool plugins. It can be steered by [prompt injection](https://genai.owasp.org/llmrisk/llm01-prompt-injection/) hidden in a web page or a dependency, and even a well-meaning agent can `rm -rf` the wrong tree. AI review agents exist, but they mostly read the diff *after* the code has already run, and they are LLMs that the same prompt injection can fool, so they complement a sandbox rather than replace it. So what does a sandbox for that code actually have to do on Linux, and why is "minimal" so hard?

## 📝 TL;DR

A Linux sandbox is a **stack of partial mechanisms that all share one host kernel**. Each layer stops one class of thing and nothing else, and there is no single switch. The strongest boundary is a *second kernel*, which means a virtual machine. That is why the serious hosted products are microVMs, and why the OS-level tools ([Landlock](https://docs.kernel.org/userspace-api/landlock.html), seccomp, [bubblewrap](https://github.com/containers/bubblewrap)) are best kept for code you mostly trust on a machine you control.

The mechanisms involved, in the order a launcher typically applies them. They are not ranked: each answers a different question.

| Layer | Question it answers | What it does **not** stop |
|---|---|---|
| **[cgroup v2](https://docs.kernel.org/admin-guide/cgroup-v2.html)** | how *much*? | anything within quota; not a security boundary |
| **[user namespace](https://man7.org/linux/man-pages/man7/user_namespaces.7.html)** | *who* am I? | kernel bugs reachable by unprivileged users |
| **[pid/net/ipc/uts namespaces](https://man7.org/linux/man-pages/man7/namespaces.7.html)** | what can I *see*? | the shared kernel behind every view |
| **mount namespace + [`pivot_root`](https://man7.org/linux/man-pages/man2/pivot_root.2.html)** | what *filesystem*? | files under the roots you granted |
| **[capabilities](https://man7.org/linux/man-pages/man7/capabilities.7.html) + [`no_new_privs`](https://docs.kernel.org/userspace-api/no_new_privs.html)** | can I *re-privilege*? | syscalls that need no privilege |
| **Landlock** | which *paths*, TCP/UDP ports, unix sockets, signals? | anything outside the rights it handles; most syscalls |
| **[seccomp-bpf](https://docs.kernel.org/userspace-api/seccomp_filter.html)** | which *syscalls*? | anything an allowed syscall can reach |

> Everything here is point-in-time (late October 2026). Details of products and papers move monthly, so verify specifics before relying on them.

---

## 🚧 1. The current challenges

📚 **One shared kernel is the whole problem.** Namespaces, cgroups, capabilities, seccomp and Landlock all run *in* the host kernel. A single kernel vulnerability reachable from the sandbox is a full escape. The Linux syscall surface is enormous (hundreds of syscalls, each with many argument shapes), and features like [io_uring](https://man7.org/linux/man-pages/man7/io_uring.7.html) *add* surface. Enabling unprivileged user namespaces, which you need to sandbox without root, itself exposes more kernel code to untrusted callers and has been a recurring source of local privilege-escalation CVEs.

🎮 **Agents need capability, which fights confinement.** A file-only agent is easy to box. A *useful* coding agent wants to install packages (network), spawn compilers and test runners (exec and many syscalls), read large parts of the filesystem, and sometimes use GPUs. Every capability you grant is attack surface you re-open. The art is *least privilege per task*, which is exactly what is hard to specify up front.

🧱 **Network egress is the real prize, and the hardest to get right.** The damaging outcomes are network actions: exfiltrating secrets, reaching internal services, hitting the cloud metadata endpoint ([`169.254.169.254`](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/instancedata-data-retrieval.html)), pulling a malicious payload. A binary on/off switch (blocking `AF_INET` sockets in seccomp) is too coarse for an agent that must reach a package registry. A *filtering proxy* is the right tool, but it needs TLS interception or a domain allow-list, plus care that the agent can't just talk to `localhost` services or use DNS as a covert channel.

🗒️ **Secrets and ambient authority leak in surprising ways.** Environment variables, inherited file descriptors, cloud instance-metadata credentials, `~/.aws`, `~/.ssh`, a mounted Docker socket, a `GITHUB_TOKEN` in the environment: none of these are "files the agent opened", so a filesystem sandbox alone misses them. A 2026 security note on AWS Bedrock AgentCore argued that its code-interpreter microVM still exposes execution-role credentials via the metadata service; AWS considers that by design. Whoever is right, the lesson stands: *isolation of the compute does not imply isolation of the credentials*.

🐳 **Views leak the host.** Inside a container, `/proc/cpuinfo`, `/proc/meminfo` and `/proc/stat` show the *host's* numbers unless something virtualises them ([`lxcfs`](https://github.com/lxc/lxcfs)). That is the same reason `top` in a container shows host CPU and steal time. Information disclosure is a weaker threat than escape, but it feeds fingerprinting and side channels.

📦 **Correctness is a sequencing minefield.** The layers have prerequisite chains and failure modes. `no_new_privs` must be set before an unprivileged seccomp filter. A gid map needs `setgroups=deny`. A bind mount can't go read-only in one step on older kernels. Landlock rights must be masked to the running ABI or `restrict_self` fails. Seccomp goes in last, so your own setup syscalls aren't filtered. Each is a place to silently under-confine, and **a half-applied sandbox is worse than none**, because you think you're protected. A good sandbox aborts on any layer that fails rather than running the agent half-confined.

🐧 **Deny-lists have traps.** A syscall deny-list is deceptively easy to under-build:

- 🧱 **io_uring.** It can perform socket, connect and `openat` operations *as ring operations*, without issuing those syscalls, so a naive seccomp network block is sidestepped by an agent that opens a ring and connects through it. Any deny-list that ignores io_uring is porous.
- 🔑 **The [x32 ABI](https://lwn.net/Articles/456731/).** On x86-64, x32 syscalls carry the same `AUDIT_ARCH_X86_64` token but OR `0x40000000` into the number. A filter that only compares plain numbers lets the x32 variant of every denied call through.
- 📦 **[`ioctl(TIOCSTI)`](https://man7.org/linux/man-pages/man2/TIOCSTI.2const.html).** A process sharing the controlling terminal can push bytes into the terminal's input queue, and the parent shell runs them after the sandbox exits. That is a full escape that touches no file and opens no socket. Since Linux 6.2 the host can switch it off with `sysctl dev.tty.legacy_tiocsti=0`, and several distributions ship it off, but a sandbox should still call [`setsid()`](https://man7.org/linux/man-pages/man2/setsid.2.html) and filter the ioctl itself.
- 🔹 **Arch confusion.** A 32-bit (`i386`) calling convention uses different numbers for different calls, so a filter must check the architecture first.

Each hole is invisible if you reason about syscalls by name. This is why serious sandboxes invert to **deny-by-default** and lean on audited, maintained profiles instead of a hand-rolled list.

📝 **Portability and kernel-version drift.** Landlock needs Linux 5.13 or newer and grows new abilities per ABI: TCP bind and connect by port (ABI 4, Linux 6.7), device ioctls (ABI 5), abstract-unix-socket and signal scoping (ABI 6, Linux 6.12), audit logging (ABI 7), pathname unix sockets (ABI 9) and UDP (ABI 10). A sandbox written for ABI 10 quietly gets less on a 6.6 LTS kernel unless it checks. Seccomp syscall numbers are per-architecture. Unprivileged user namespaces are disabled on some hardened distributions, and from Ubuntu 24.04 [AppArmor](https://ubuntu.com/blog/ubuntu-23-10-restricted-unprivileged-user-namespaces) restricts them (`kernel.apparmor_restrict_unprivileged_userns=1`), which breaks bubblewrap unless a profile grants it `userns`. A sandbox that works on your machine may fail open elsewhere.

🔥 **Performance and density.** Hosted agent platforms run *many* sandboxes and want sub-second cold starts and snapshot/restore. OS-level sandboxes are cheap (microseconds to milliseconds) but weak. VMs are strong but were historically slow to boot, which is the gap Firecracker plus snapshotting closed, and why microVMs became viable for this at all.

---

## 🔮 2. Where the future is moving

- 🔥 **MicroVMs are becoming the default for *untrusted* code, not the exception.** [Firecracker](https://firecracker-microvm.github.io/)-style microVMs give each sandbox its own kernel at roughly 100 to 150 ms cold start, and snapshot/restore (lazy page-fault-driven restore via [`userfaultfd`](https://docs.kernel.org/admin-guide/mm/userfaultfd.html)) makes per-task or per-step forking cheap. The hosted market (E2B, Vercel Sandbox, AWS AgentCore) has largely standardised on this.

- 📝 **A tiered "right-sized isolation" model is winning over one-size-fits-all.** Guidance is converging across 2026 write-ups: OS-level confinement (Landlock, seccomp, bubblewrap) for *trusted* code on *trusted* machines; [gVisor](https://gvisor.dev/docs/) as a middle tier; microVMs and [Kata](https://katacontainers.io/) for *untrusted, multi-tenant* code. The interesting engineering is in *choosing* and *composing* tiers per workload, not in one perfect sandbox.

- 📦 **Landlock is maturing into a real agent primitive.** It began filesystem-only (Linux 5.13). ABI 4 (Linux 6.7) added TCP bind and connect rules, ABI 6 (Linux 6.12) added abstract-unix-socket and signal *scoping*, and ABIs 9 and 10 added pathname unix sockets and UDP. That turns Landlock from "restrict files" into "restrict a process tree's whole resource reach", unprivileged and self-applied, which is ideal for a CLI agent that sandboxes itself.

- 🛂 **[seccomp-notify](https://man7.org/linux/man-pages/man2/seccomp_unotify.2.html) supervisors put user-space policy in the loop.** Instead of a static allow/deny BPF program, the kernel can *forward* a syscall to a supervisor process that decides at runtime and can even virtualise the effect. **Sandlock** (Wang and Zheng, [arXiv:2605.26298](https://arxiv.org/abs/2605.26298)), a 2026 research prototype that is now an [open-source project](https://github.com/multikernel/sandlock) (section 4), combines Landlock and seccomp with a seccomp-notification supervisor to get dynamic network decisions, HTTP-level access control, and [TOCTOU](https://cwe.mitre.org/data/definitions/367.html)-safe inspection of `execve` arguments, all unprivileged, with about 5 ms startup overhead. "Static policy compiled into the kernel, plus a narrow supervisor for the hard cases" is likely where lightweight agent sandboxes head. NVIDIA's OpenShell (section 4) now ships this shape as a product.

- ☸️ **Orchestration is standardising.** The Kubernetes SIG's **agent-sandbox** (a `Sandbox` [CRD](https://kubernetes.io/docs/concepts/extend-kubernetes/api-extension/custom-resources/) with warm pools, delegating isolation to gVisor or Kata via [`RuntimeClass`](https://kubernetes.io/docs/concepts/containers/runtime-class/)) signals that "a sandbox" is becoming a first-class, schedulable object with stable identity, persistent storage and a sub-second claim from a pre-warmed pool, rather than an ad-hoc `docker run`.

- 🧊 **Snapshotting is a product feature, not just a speed trick.** Pause/resume, fork-a-running-state, and "close your laptop, the agent keeps going" (AWS AgentCore) are becoming table stakes. That pushes toward VM-level isolation, because snapshotting a whole guest is cleaner than checkpointing a process tree ([CRIU](https://criu.org/Main_Page) is fragile).

- 🔌 **Egress control moves up the stack.** The trend is away from "block all sockets" toward *identity-aware filtering proxies* with per-domain allow-lists and audit. Agents must reach *some* network, and the useful policy is about *where*, not *whether*.

---

## 💡 3. Contenders vs the status quo

The status quo for running arbitrary code has been **[OCI](https://github.com/opencontainers/runtime-spec) containers** (Docker and [`runc`](https://github.com/opencontainers/runc)): namespaces, cgroups, a default seccomp profile and dropped capabilities. They have good ergonomics and a huge ecosystem, but they share a kernel, so they are insufficient for genuinely untrusted, multi-tenant code. The contenders differ mainly in **where the trust boundary sits**.

| Approach | Boundary | Isolation strength | Start | Cost / density | Best fit for agents |
|---|---|---|---|---|---|
| `chroot` | path resolution only | ~none (escapable) | instant | free | not a sandbox |
| **bwrap / [nsjail](https://github.com/google/nsjail) / Landlock launchers (e.g. Sandlock)** | namespaces, shared kernel | low to moderate | ~ms | very high | trusted code; per-call confinement |
| **OCI container** (`runc`) | namespaces + seccomp, shared kernel | moderate | ~100 ms | very high | semi-trusted; the status quo |
| **gVisor** | user-space kernel intercepts syscalls | high (small host surface) | ~100 to 300 ms | high | untrusted code without a VM; some compatibility cost |
| **[Incus](https://linuxcontainers.org/incus/introduction/) container** (system container) | namespaces + seccomp + LSM, shared kernel | moderate | ~1 ms to 1 s | very high | semi-trusted agents that want a whole persistent OS; self-hosted dev and CI |
| **Kata / Firecracker / [Cloud Hypervisor](https://www.cloudhypervisor.org/)** | separate guest kernel (KVM) | highest (on Linux) | ~100 to 150 ms, faster from snapshot | moderate | untrusted, multi-tenant: the serious default |
| **[WASM](https://webassembly.org/) runtime** | capability-based VM, no syscalls | high for *what it supports* | ~ms | very high | narrow, pure-compute tools |

Moving down the table trades **density and compatibility** for **isolation strength**. Containers sit in the middle and are fine for code you mostly trust. The direction of travel for *untrusted* agent code is toward gVisor and especially microVMs, with OS-level tools relegated to the innermost layer or to trusted single-user setups.

A few nuances the table flattens:

- 🖥️ **gVisor vs microVM** isn't strictly "weaker vs stronger". gVisor shrinks the *host* syscall surface to a few dozen but adds its own (smaller) kernel's surface and some workload incompatibility. A microVM gives a full, familiar kernel per guest, but a larger in-guest surface, and the KVM/[virtio](https://docs.oasis-open.org/virtio/virtio/v1.3/virtio-v1.3.html) boundary is the thing to trust.
- 📦 **WASM** is the strongest *per-feature* boundary (no ambient syscalls at all), but it can only run what has been compiled to it and wired to explicit host capabilities. It is great for a sandboxed function, not for "run this arbitrary repo's test suite".
- 🐳 **Composition beats any single row.** Real systems stack them: OS-level confinement *inside* a container *inside* a microVM, with a filtering proxy on egress. Each layer catches what the one inside it missed.

---

## 📦 4. How leading systems sandbox untrusted AI agents

Two families, by where they run.

### 🤖 Local coding-agent CLIs (the OS-level tier)

- 📝 **[OpenAI Codex CLI](https://developers.openai.com/codex/security).** On Linux it uses **Landlock and seccomp**: Landlock restricts the filesystem to user-approved directories, and seccomp blocks outbound network by default. A newer path vendoring **bubblewrap** sits behind a feature flag. On macOS it uses **Seatbelt** (`sandbox-exec`). Its docs warn that inside Docker the needed APIs may be unavailable and sandboxing can fail, which is the portability problem from section 1 made concrete.
- 📝 **[Claude Code](https://code.claude.com/docs/en/sandboxing).** Anthropic's **sandbox-runtime** uses **bubblewrap** on Linux for filesystem isolation and an empty network namespace. The only way out is an **HTTP proxy** (HTTP and HTTPS) and a **[SOCKS5](https://datatracker.ietf.org/doc/html/rfc1928) proxy** (other TCP) on the host, reached through unix sockets bind-mounted into the sandbox and bridged by `socat`, which gives domain-level egress control. A seccomp filter blocks other unix sockets on x86-64 and arm64; without it, unix sockets stay open with a warning. On macOS it uses `sandbox-exec`. By default it warns and runs unsandboxed if dependencies are missing, with a `failIfUnavailable` hard-fail mode for managed deployments. That is the "fail open vs fail closed" decision made visible.
- 🐳 **[Gemini CLI](https://geminicli.com/docs/cli/sandbox/).** The sandbox is **opt-in** (off by default) and pluggable: macOS Seatbelt, or Docker, Podman, **gVisor** or LXC containers. It mainly limits the filesystem to the project directory.

These share a fundamental limit that several guides state: bubblewrap and Seatbelt run on the **same kernel** as the host, so they offer little against kernel exploits. They are suitable mainly for *trusted* code on *trusted* machines, the right tool for a developer running an agent on their own laptop and not for a multi-tenant service executing strangers' code.

### 🧊 Hosted execution platforms (VM or user-space-kernel tier)

- 🔥 **[E2B](https://e2b.dev/docs).** Each sandbox is a **Firecracker microVM** with its own kernel. The core is Apache-2.0 and self-hostable, with roughly 150 ms cold start from snapshot, and snapshot-based pause/resume is central. It is widely treated as the reference open option.
- 🔥 **[Vercel Sandbox](https://vercel.com/docs/vercel-sandbox).** **Firecracker microVMs**, with snapshots and time-limited sessions.
- 🎮 **[Modal](https://modal.com/docs/guide/sandbox).** Sandboxes default to **gVisor**, with a VM runtime (own kernel) added for stronger isolation, and filesystem-snapshot persistence. A standout for **GPU** inside the sandbox.
- 🧊 **[AWS Bedrock AgentCore Code Interpreter](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-interpreter-tool.html).** A per-session **isolated Linux microVM** with a persistent workspace and "keep running while your laptop is closed" semantics (see the credential-exposure critique in section 1).
- 🐳 **[Cloudflare Sandbox SDK](https://developers.cloudflare.com/sandbox/).** Built on Cloudflare **Containers**, one sandbox per VM. Its docs recommend per-user sandboxes because everything in one sandbox shares resources. Third parties dispute the exact mechanism, and it is pre-1.0.
- 🐳 **[Daytona](https://www.daytona.io/docs/).** Fast-create persistent workspaces with snapshots and forks. Default isolation is reported as containers on the host kernel, with optional **Kata** or Sysbox for stronger isolation. Licensing and status were in flux in 2026, so verify before relying on it.
- ☸️ **[Kubernetes `agent-sandbox`](https://agent-sandbox.sigs.k8s.io/docs/getting_started/overview/).** Not an isolator itself: a `Sandbox` CRD plus controller that schedules pods onto **gVisor or Kata** via `RuntimeClass`, with **warm pools** for sub-second starts. It is the orchestration story for self-hosting agent sandboxes at scale.
- 🏠 **[Incus](https://linuxcontainers.org/incus/introduction/).** The community fork of LXD (Apache-2.0, written in Go). Not agent-specific, but the most credible *self-hosted* way to hand an agent a whole machine. One REST API and CLI manage **system containers** (shared kernel, unprivileged by default) and **QEMU virtual machines** (own kernel) side by side, with images, snapshots, copy-on-write clones, **projects** to partition tenants, network ACLs for egress, and lifecycle events you can subscribe to for audit. The isolation depends on the instance type you pick: a container is the shared-kernel tier, an Incus VM is the separate-kernel tier with QEMU's larger device surface than Firecracker's. It is a manager, not a sandbox primitive, so you still put the agent's tool calls behind your own broker and an egress proxy.

### 🐚 NVIDIA OpenShell: the supervisor pattern, productised

[OpenShell](https://github.com/NVIDIA/OpenShell) is NVIDIA's answer to agent sandboxing. It was [announced at GTC on 16 March 2026](https://investor.nvidia.com/news/press-release-details/2026/NVIDIA-Ignites-the-Next-Industrial-Revolution-in-Knowledge-Work-With-Open-Agent-Development-Platform/default.aspx) as part of the NVIDIA Agent Toolkit, released under Apache-2.0, and is at version 0.1.x as of October 2026. It sits *between* the two families above: it runs on a laptop like the local CLIs, but it is built as a control plane for *fleets* of agents, like the hosted platforms. It does not replace an agent CLI. It wraps one: the docs and NVIDIA's own write-ups list Claude Code, Codex, OpenCode and GitHub Copilot CLI as workloads.

🦀 **Three components.** The [architecture](https://docs.nvidia.com/openshell/latest/about/architecture) splits trust three ways:

- The **gateway** is the control plane. It manages sandbox lifecycle, authenticates users, stores state, delivers policy and attaches credentials ("providers"). It is the only component that signs credentials, and each credential is bound to one sandbox and one run.
- The **supervisor** is the trusted side of the boundary. It checks every request against policy, resolves DNS, adds credentials, and opens approved connections itself. It "makes the decisions".
- The **sandbox** shares the boundary with the untrusted agent. It launches the agent as a child process, identifies which program is making each call, and forwards TCP and DNS to the supervisor. It "never makes policy decisions".

The supervisor and sandbox talk over one mutually authenticated HTTP/2 connection, carried over a unix socket (Docker, Podman), TCP (Kubernetes) or [vsock](https://man7.org/linux/man-pages/man7/vsock.7.html) (microVM).

📦 **The kernel mechanisms are the ones in this post.** Per the [support matrix](https://docs.nvidia.com/openshell/latest/about/support-matrix), launching a sandbox requires:

- 🧱 **Landlock ABI 3 or newer** (Linux 6.2) for the filesystem policy.
- 🔑 **seccomp user notification**, including nested filters and [`SECCOMP_IOCTL_NOTIF_ADDFD`](https://man7.org/linux/man-pages/man2/seccomp_unotify.2.html) with `SECCOMP_ADDFD_FLAG_SEND`, used to intercept TCP opens and DNS queries. `ADDFD` is how a supervisor installs a file descriptor it opened into the confined process, the same fd-delegation idea as Capsicum's broker in section 7.
- 🐧 **Reading the child's memory** with [`process_vm_readv`](https://man7.org/linux/man-pages/man2/process_vm_readv.2.html) or `/proc/<pid>/mem`, so the supervisor can inspect syscall arguments.
- 🔌 **[`SO_BINDTODEVICE`](https://man7.org/linux/man-pages/man7/socket.7.html)** to bind workload sockets to loopback.

The agent runs as one non-root user with no Linux capabilities. If any requirement is missing, launch **fails closed**. If the supervisor connection drops, the sandbox *freezes* the agent, and only the same supervisor process can resume it. That is exactly the "static policy compiled into the kernel, plus a narrow supervisor for the hard cases" shape that section 2 predicted from the Sandlock research, shipped by a major vendor.

🧱 **An outer fence, so the supervisor is the only way out.** Seccomp interception alone is porous (section 1's io_uring trap), so each runtime also removes direct network access using its own tools:

| Runtime driver | Where the supervisor runs | How direct egress is blocked | Kernel |
|---|---|---|---|
| Docker | its own container | workload container has `network=none` | shared with host |
| Podman (rootless) | its own container | workload container has networking off | shared with host |
| Kubernetes | its own pod | `NetworkPolicy` allows only the supervisor; the CNI must enforce it | shared, unless the pod uses a Kata `RuntimeClass` |
| MicroVM ([libkrun](https://github.com/containers/libkrun)) | host process | guest has no network device | its own, via KVM or Apple Hypervisor.framework |

This maps one-to-one onto section 3's tiers. The container drivers are the shared-kernel tier with a better egress design, and the microVM driver is the second-kernel tier. The microVM driver is opt-in, never auto-detected, and the docs do not recommend one driver for untrusted code, so for strangers' code choose the VM driver (or Kata on Kubernetes) deliberately. On macOS the Linux kernel controls run inside Docker Desktop's VM. The Kubernetes driver schedules pods through the same [Agent Sandbox](https://agent-sandbox.sigs.k8s.io/docs/getting_started/overview/) controller described above.

📦 **Policy: one YAML file, deny by default.** A [policy](https://docs.nvidia.com/openshell/latest/how-it-works/policies/overview) has up to five sections: `filesystem_policy` (read-only and read-write paths, enforced by Landlock), `landlock`, `process` (the user and group), `network_policies` and `network_middlewares`. Filesystem, Landlock and process settings are fixed at startup; network rules can change while the sandbox runs. Every outbound connection is denied unless a rule allows it. [Network rules](https://docs.nvidia.com/openshell/latest/how-it-works/policies/network-rules) go well past a domain allow-list:

- 🎯 **Per binary.** A rule names the executables allowed to use it, matched by the real path the kernel reports. OpenShell hashes each executable the first time it connects and denies later connections if the file changes. Child processes of a listed binary inherit the rule.
- 🔏 **Per HTTP method and path.** With `protocol: rest`, rules match method, path and query, with presets such as `access: read-only` (`GET`, `HEAD`, `OPTIONS`). To see inside HTTPS, the supervisor **terminates TLS** unless an endpoint sets `tls: skip`.
- 📦 **DNS through the supervisor.** The sandbox gets placeholder addresses with short TTLs and no search domains, which closes the DNS covert channel from section 1.
- 🔗 **SSRF guard rails.** Private addresses are blocked by default, and loopback, link-local and unspecified destinations, including the metadata endpoint `169.254.169.254`, are never authorised.

For example, read-only GitHub API access for `curl` and nothing else:

```yaml
github_readonly:
  endpoints:
    - host: api.github.com
      port: 443
      protocol: rest
      enforcement: enforce
      access: read-only
  binaries:
    - path: /usr/bin/curl
```

📦 **Credentials never enter the sandbox.** [Providers](https://docs.nvidia.com/openshell/latest/how-it-works/providers/overview) map a service to a stored credential, and the supervisor adds it only to requests bound for approved endpoints. The sandbox holds no gateway key, gateway token or provider secret. This is the credential brokering recommended in section 8.

📜 **Policy review with a solver.** Two features turn section 6's "policy matters as much as mechanism" into tooling:

- The **[policy advisor](https://docs.nvidia.com/openshell/latest/how-it-works/policies/advisor)**. When a request is denied, the agent gets an explanation and can propose a narrow rule (host, port, binary, method, path). A proposal never changes policy on its own: a human approves or rejects it from the CLI, and a rejection reason goes back to the agent so it can propose something narrower. An opt-in `auto` mode exists.
- The **[policy prover](https://docs.nvidia.com/openshell/latest/how-it-works/policies/prover)**, which uses an [SMT solver](https://smt-lib.org/) to check that a candidate policy stays within a boundary policy you write, and that a proposed rule adds no risky reach. It reports findings such as `link_local_reach`, `credential_reach_expansion` and `l7_bypass_credentialed` (a credential reachable by traffic the supervisor cannot inspect). Any finding forces human review, even in `auto` mode. The prover answers `unsupported` rather than guessing for GraphQL, MCP, WebSocket and JSON-RPC, and a pass means only "within the boundary in the checked areas", not "safe".

📝 **Sentry: a monitor the host cannot reach.** On 28 September 2026 NVIDIA wrapped OpenShell into an "Open Agent Safety Platform" with **Sentry**, a monitoring and enforcement layer that runs on [BlueField-4](https://www.nvidia.com/en-us/networking/products/data-processing-unit/) DPUs instead of on the machine running the agent. The premise is that "an agent that deviates from its intended task cannot be relied upon to govern itself": if the agent escapes the shared kernel, a monitor on the network card is still in the path. It is an answer to this post's core problem (one shared kernel), but it needs NVIDIA data-centre hardware, is not open source, and the adoption claims around it come from NVIDIA and its partners.

🛠️ **How it measures against this post.**

| Theme in this post | OpenShell's answer |
|---|---|
| Shared kernel (section 1) | Unchanged for the container drivers; solved by the opt-in microVM driver or Kata. Sentry adds out-of-band monitoring on DPU hardware. |
| Egress is the real prize (section 1) | Supervisor-only egress, deny by default, per-binary and per-method rules, TLS termination, supervisor-side DNS, metadata always blocked. The strongest part of the design. |
| Exfiltration through allowed channels (section 8) | Partly: read-only REST rules stop pushes to `github.com`, but only for traffic it can inspect (`tls: skip` and non-HTTP protocols bypass L7 rules). |
| Credential brokering (section 8) | Yes, by design. |
| Fail closed (decision guide) | Yes at launch and on supervisor loss; check the `landlock` section's `compatibility` setting, where only `hard_requirement` aborts startup when Landlock rules cannot be applied. |
| Least privilege per task (section 6) | Advisor proposals plus prover checks plus human approval. |
| Persistence after exit (section 8) | Not addressed: the workspace persists across stop and start, so protect hooks and editor configs yourself. |
| The model as an exfiltration channel (section 8) | Not addressed by the sandbox; no sandbox can see what the model writes. |
| GPUs (section 5) | `--gpu` via NVIDIA [CDI](https://github.com/cncf-tags/container-device-interface) devices on the container drivers (the shared host driver), one GPU on the microVM driver. |

⚠️ **Caveats worth knowing before relying on it:**

- 📈 **REST rules default to audit.** An endpoint's `enforcement` defaults to `audit`, which *logs* method and path violations and lets them through. Set `enforcement: enforce` for the read-only rules to mean anything. Host, port and binary matching is still deny by default.
- 🔑 **Binary identity is path plus hash, not intent.** A rule for `/usr/bin/python3` or `/bin/bash` covers *any* script that interpreter runs, and children inherit the rule. Keep interpreters out of rules that carry credentials.
- 🦀 **TLS termination puts the supervisor in the trust path.** That is what makes L7 rules possible, and it also makes the supervisor a high-value target.
- 🧱 **It is 0.1 software.** The docs change quickly and several details (Landlock compatibility defaults, global policies) are not fully documented yet.

### 🔐 Sandlock: the supervisor pattern without containers or root

[Sandlock](https://github.com/multikernel/sandlock) started as the research prototype mentioned in section 2 ([arXiv:2605.26298](https://arxiv.org/abs/2605.26298), a preliminary paper for the Agentic OS workshop at ASPLOS 2026) and is now an open-source project from Multikernel Technologies: Rust, Apache-2.0, at [v0.9.0](https://github.com/multikernel/sandlock/releases/tag/v0.9.0) as of 13 October 2026, after releases every two to three weeks since March. Where OpenShell wraps the supervisor pattern in containers or microVMs, Sandlock strips everything else away: **no root, no namespaces, no cgroups, no image**. It confines an ordinary child process with Landlock, seccomp-bpf and a seccomp-notification supervisor, and nothing more. That puts it squarely in section 3's shared-kernel tier, next to bubblewrap, but with a far richer policy than a list of bind mounts.

```console
$ sandlock run -w /tmp -r /usr -r /lib -m 512M -- python3 untrusted.py
```

It ships as a CLI, a Rust library, Python and Go SDKs over a C ABI, and an OCI runtime shim.

🪜 **How confinement is applied.** The [architecture](https://github.com/multikernel/sandlock/blob/main/docs/architecture.md) is a fixed sequence after `fork()`. The child sets `no_new_privs`, applies Landlock (filesystem, TCP ports, IPC scoping), and installs a seccomp filter that denies some syscalls outright and routes others to a listener. It passes the listener's file descriptor to the parent, waits for the go-ahead, closes inherited descriptors and calls `exec`. The parent runs an async supervisor on that listener. The policy is therefore in force before the untrusted program runs its first instruction. What the supervisor handles:

| Intercepted syscalls | What the supervisor does |
|---|---|
| `clone`, `fork`, `vfork` | caps the number of processes |
| `mmap`, `munmap`, `brk`, `mremap`, `mprotect` | tracks memory against the limit |
| `connect`, `sendto`, `sendmsg` | checks the destination, performs the call on the child's behalf, redirects HTTP to the filtering proxy |
| `bind`, `getsockname` | binds on the child's behalf, with per-sandbox port virtualisation |
| `openat`, `getdents64` | virtualises `/proc`, redirects reads and writes for the copy-on-write workdir |
| `execve`, `execveat` | holds the call for an optional policy callback |
| `getrandom`, timers | can inject deterministic randomness and freeze time |

🧱 **Kernel floor, and failing closed.** By default it needs **Linux 6.12** (Landlock ABI 6, which added scoping for abstract unix sockets and signals) and refuses to start if a protection is unavailable. Callers can [opt out per protection](https://github.com/multikernel/sandlock/blob/main/docs/sandbox-reference.md#protection-opt-out): `allow_degraded` enforces a protection where the kernel supports it and silently skips it where it does not, and `disable` never enforces it. Strict is the right default, but many long-term-support distributions ship older kernels (Debian 12 has 6.1; RHEL 9 is based on 5.14), so a mixed fleet will tempt you towards `allow_degraded`, which quietly gives up exactly the protections section 1 worries about. Check what `sandlock check` reports instead of assuming.

🔌 **TOCTOU: act on the child's behalf.** The classic weakness of a seccomp-notify supervisor is that when it answers "continue", the kernel re-reads pointer arguments from the child's memory, and another thread can change them in between. Sandlock never continues a mediated network call. It copies the `sockaddr` once, checks the copy, takes the socket with [`pidfd_getfd`](https://man7.org/linux/man-pages/man2/pidfd_getfd.2.html), and performs `connect` itself, the same fd-delegation idea as OpenShell's `ADDFD` and Capsicum's broker. For `execve` arguments it freezes sibling threads and any process sharing the child's memory while it reads, and denies with `EPERM` when it cannot freeze them (for example when [Yama](https://docs.kernel.org/admin-guide/LSM/Yama.html) blocks `ptrace`). The paper is explicit that matching on arguments is an observation signal, not a containment boundary: containment comes from Landlock, seccomp and the network rules.

🌐 **Network: deny by default, two enforcement paths.** With no rules, Landlock denies every TCP `connect` and seccomp blocks creating UDP, ICMP and raw sockets. Rules name protocol and destination (`--net-allow api.openai.com:443`, `udp://…`, `icmp://…`), a deny list wins any overlap, and raw ICMP is never exposed. The [network model](https://github.com/multikernel/sandlock/blob/main/docs/network.md) has two paths:

- ⚡ **Direct.** A policy made only of TCP ports is enforced by Landlock in the kernel, with no per-call cost.
- 🔀 **On-behalf.** Any rule naming a host, IP or CIDR, any UDP or ICMP rule, and any HTTP rule sends the call through the supervisor. The paper measured the median round trip rising from 20 µs to 55 µs.

Hostnames are resolved once at start and pinned in a synthetic `/etc/hosts`, and wildcard hostnames (`*.example.com`) are not supported. With no UDP rule the sandbox cannot send DNS queries at all, which closes section 1's DNS covert channel. Two consequences follow from checking by address. A service that changes IPs mid-run breaks. And allowing a CDN-fronted host admits every other site on those addresses, unless an HTTP rule also checks the host name.

🔏 **HTTP rules and credentials.** `--http-allow "POST api.openai.com/v1/chat/completions"` and `--http-deny "* */admin/*"` send matching traffic through a transparent proxy that checks method, host and path. For HTTPS the proxy must terminate TLS. `--http-inject-ca` generates a throwaway CA, keeps its private key in memory, and splices its certificate into the trust bundles you name when they are opened. Runtimes with their own certificate store, such as Node, need `NODE_EXTRA_CA_CERTS` pointed at it. Without this, `--net-allow host:443` allows raw TLS with no inspection, the same gap as OpenShell's `tls: skip`. **Credential injection** keeps a secret in the supervisor and adds it in the proxy *after* the rule check, so the agent never holds it:

```console
$ sandlock run \
    --http-allow "POST api.openai.com/v1/*" \
    --http-inject-ca /etc/ssl/certs/ca-certificates.crt \
    --credential openai=env:OPENAI_API_KEY \
    --http-auth "POST api.openai.com/* bearer openai" \
    -r /usr -r /lib -r /etc -- python3 agent.py
```

That is section 8's credential brokering, without a separate gateway.

📂 **Filesystem: Landlock plus a copy-on-write workdir.** Landlock grants the read and write paths. With `--workdir`, the supervisor also stages writes in an upper directory (reads resolve upper first, then lower), with no mount or user namespace. On exit it commits, aborts on error, or, with deferred handling, leaves the changes for a trusted caller to inspect and then commit or abort. `--dry-run` shows what a command would change, then throws it away. This is the most direct answer in this post to section 8's *persistence after the sandbox exits*: an injected edit to `.git/hooks` inside the workdir can be reviewed before it lands. The limits: only regular files, directories and symlinks are staged (FIFOs, sockets and device nodes go straight to the kernel and are never reverted), writes outside the workdir are not staged, and network effects are never rolled back.

📉 **Resource limits without cgroups, and their weakness.** Memory is capped by counting address-space requests (`mmap`, `brk`, `mremap`, `shmget`), not resident pages, and stack growth is not counted. Processes are capped by refusing `clone` with `EAGAIN`, CPU is throttled with `SIGSTOP`/`SIGCONT` duty cycles, and file descriptors use `RLIMIT_NOFILE`. The paper calls these limits cooperative and says cgroups remain stronger against adversarial workloads. They stop a runaway build, not a determined fork-and-allocate attack.

👀 **Virtualised views.** Because `openat` is intercepted, the supervisor can rewrite what `/proc` shows. The docs detail `/proc/net`: a loopback-only topology, and socket tables that list only sockets held by sandbox tasks. That is section 1's "views leak the host", handled for the network tables.

🧩 **Composition: pipelines and planner/executor.** [Pipelines](https://github.com/multikernel/sandlock/blob/main/docs/pipelines.md) give each stage its own sandbox, joined by kernel pipes (`planner.cmd(...) | executor.cmd(...)`). The **execute-only agent** pattern splits an agent in two: the planner can reach the model but cannot read the data; the executor can read the data but has no network. That is a structural answer to the lethal trifecta from section 8, because no single process holds private data, untrusted content and a way out. The [prompt-injection guide](https://github.com/multikernel/sandlock/blob/main/docs/prompt_injection.md) is candid about the limits: the split bounds *capabilities*, not what flows through the pipe, and the executor's output can still carry sensitive data. A related **COW fork** initialises a process once and forks sandboxed clones from it, about 530 µs each.

📜 **Least privilege by observation.** [`sandlock learn`](https://github.com/multikernel/sandlock/blob/main/docs/learn.md) runs a workload under observation and writes a profile of the paths, connections, HTTP methods and paths, and resource peaks it used, ready for `sandlock run -p`. It is a practical start on section 6's least privilege per task. Review the result: a profile learned from a run that an injected agent influenced records whatever that agent did.

🐳 **Namespace-less containers.** [`sandlock-oci`](https://github.com/multikernel/sandlock/blob/main/crates/sandlock-oci/README.md) implements the OCI runtime interface, so containerd, CRI-O and Kubernetes can run workloads under Sandlock unprivileged, with checkpoint and restore. The isolation is Landlock and seccomp, not namespaces, so treat it as the shared-kernel tier, not as a stronger `runc`.

🪆 **Nesting costs features.** The kernel allows one seccomp listener per task, so a Sandlock inside another Sandlock must run `no_supervisor`: Landlock plus a kernel-only deny filter, with no IP allow-list, resource limits, copy-on-write, `/proc` virtualisation or custom handlers.

📏 **The numbers.** On the paper's workstation (Ryzen 5 5500U, Linux 6.18), Sandlock adds about 5 ms to startup, Redis throughput and p99 latency are within noise of bare metal, and the on-behalf network path adds about 35 µs per round trip. Rootful Docker is the only other system the paper measures; its figures for bubblewrap, gVisor and Firecracker are approximate, not measured.

🛠️ **How it measures against this post.**

| Theme in this post | Sandlock's answer |
|---|---|
| Shared kernel (section 1) | Unchanged, by design. Kernel bugs and side channels are out of scope, and the authors say adversarial multi-tenant workloads still need a microVM. |
| Egress is the real prize (section 1) | Deny by default, a Landlock fast path, supervisor-mediated destinations, HTTP method and path rules, pinned DNS. |
| Exfiltration through allowed channels (section 8) | Partly: HTTP rules limit methods and paths when TLS is intercepted. Raw TLS to an allowed host is not inspected, and an allowed endpoint can still receive data. |
| Credential brokering (section 8) | Yes: injected in the proxy after the rule check. |
| Fail closed (decision guide) | Yes by default; `allow_degraded` and `disable` weaken it per protection. |
| Persistence after exit (section 8) | The strongest answer in this post: a copy-on-write workdir with dry-run and deferred review. Writes outside the workdir are not covered. |
| Least privilege per task (section 6) | `sandlock learn` profiles, plus a separate sandbox per pipeline stage. |
| Resource exhaustion (section 8) | Cooperative limits without cgroups; weaker than cgroups. |
| The model as an exfiltration channel (section 8) | Not addressed by the sandbox. The planner/executor split reduces what the model sees. |

**OpenShell or Sandlock?** They implement the same idea at different scales. OpenShell is a control plane for fleets: containers or microVMs as an outer fence, per-binary rules, a policy prover. Sandlock is one unprivileged process wrapper with about 5 ms of overhead, a copy-on-write workdir and composable pipelines. On a laptop, Sandlock is the lighter fit; for strangers' code, either one belongs inside a VM.

⚠️ **Caveats worth knowing before relying on it:**

- 🧪 **It is pre-1.0 and moves fast,** with a release every few weeks.
- 🔬 **The evidence is early.** The paper is a preliminary workshop paper; its effectiveness check is ten deterministic allow/deny tests, the compatibility study covers four tools (`python3`, `make`, `node`, `pytest`), and I found no independent audit.
- 🦀 **The supervisor is in the trust path.** It mediates connections and, with HTTPS inspection, terminates TLS, which makes it a high-value target.
- 🐧 **Linux 6.12 or newer,** unless you opt out of protections.

### 🔎 The pattern across all of them

1. **Tiered by trust.** Local CLIs accept the shared-kernel tier because the code is semi-trusted and the machine is the user's own. Hosted platforms running *arbitrary* users' code almost universally reach for a **second kernel** (Firecracker) or a **user-space kernel** (gVisor).
2. **Egress is a filtering proxy, not a toggle.** The serious systems control *which* domains, with audit, because agents need package registries and APIs.
3. **Snapshot/restore is a first-class feature**, which itself pushes toward VM isolation.
4. **Least privilege per task**, increasingly expressed declaratively (Landlock rulesets, Kubernetes CRDs, per-call policy) rather than one static container configuration.

---

## 🎮 5. Why Firecracker rather than QEMU, and what about GPUs?

### 🔥 Could plain QEMU do the job of Firecracker?

Yes. Both put the guest behind hardware virtualisation with its own kernel, so the *kind* of boundary is the same. The difference is what it costs to get it:

- 🔥 **Tiny device model.** QEMU emulates a very wide range of hardware (legacy devices, USB, many NICs and disk controllers, graphics). Firecracker exposes a handful of virtio devices, a serial port and a minimal keyboard controller. Less emulation code reachable from the guest means less attack surface, and many past QEMU escapes came from obscure emulated devices.
- 🖥️ **Boot time and footprint.** About 100 to 150 ms and a small per-VM memory overhead, against a slower start for a stock QEMU machine type with firmware. Agent workloads create thousands of short-lived sandboxes, so this matters.
- 🧊 **Density.** Low overhead per VM lets a host pack far more sandboxes.
- 📦 **Snapshots.** Snapshot/restore is a core feature, and it is what "resume a warm sandbox" products build on.
- 🧱 **Built for multi-tenancy.** Written by AWS for Lambda and Fargate in Rust, and run under a *[jailer](https://github.com/firecracker-microvm/firecracker/blob/main/docs/jailer.md)* (seccomp, namespaces, cgroups).

QEMU is the better choice when you need hardware Firecracker lacks (GPU passthrough, USB, other CPU architectures, Windows or macOS guests) or you want the most mature, widely supported tool. QEMU's [`microvm` machine type](https://www.qemu.org/docs/master/system/i386/microvm.html) with no firmware and a stripped config gets most of Firecracker's benefits, and Cloud Hypervisor and [crosvm](https://crosvm.dev/book/) are other minimal VMMs. Firecracker is not the only way; it is the one managed platforms standardised on.

### 🎮 Firecracker and GPUs

Stock Firecracker cannot give a guest a GPU. Its minimal device model has no PCI bus, which rules out PCIe passthrough, and that is a consequence of the design, not an oversight. (Firecracker's PCI story has been changing; check the current release notes.) For GPU workloads, sources point to QEMU or Cloud Hypervisor instead. The options in use:

| Model | Boundary | Catch |
|---|---|---|
| **[VFIO](https://docs.kernel.org/driver-api/vfio.html) passthrough into a VM** (QEMU, Cloud Hypervisor, Kata) | Hypervisor, with exclusive device ownership | One GPU per tenant. Naive passthrough can re-open the boundary through GPU DMA, so it needs an IOMMU and care. |
| **gVisor + [`nvproxy`](https://gvisor.dev/docs/user_guide/gpu/)** | Filtered NVIDIA ioctls forwarded to the host driver | Weaker than a VM: the boundary is the driver's ioctl surface. Supports only selected driver versions and CUDA commands. |
| **[NVIDIA MIG](https://docs.nvidia.com/datacenter/tesla/mig-user-guide/)** | Hardware-level partitions of one card | Supported data-centre GPUs only (for example A100, H100, H200, B200). Each partition can go to a different VM. |
| **Time-slicing / [vGPU](https://docs.nvidia.com/vgpu/index.html)** | Little (time-slicing); licensed vendor driver (vGPU) | Time-slicing suits only low-sensitivity workloads. |
| **Plain container + [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/index.html)** | Shared host kernel and driver | Fine for trusted code, poor for untrusted. |
| **No GPU in the sandbox** | n/a | Run agent glue code in a microVM and call inference over an API. Often enough. |

Why it is hard: GPU drivers are large and complex, and passing a device through means the guest drives real hardware over DMA. That widens exactly the surface a microVM was chosen to shrink, and it makes cheap snapshot and migration much harder. The shared-kernel tier has the mirror-image property: a GPU is just `/dev/nvidia*` files you allow through Landlock, which is simple but leaves the driver reachable from the sandboxed process.

### 🎮 What vendors sell for GPU isolation

Either a **whole VM or bare-metal instance with a GPU attached** (the EC2 model: one customer per GPU, isolation is the hypervisor's), or a **managed GPU sandbox**:

- 🚀 **Modal.** gVisor with the proxied NVIDIA driver (not passthrough); a wide GPU range from T4 up to H100, H200 and B200; one GPU reserved per sandbox; not self-hostable.
- 📚 **Daytona.** Reportedly VFIO passthrough, one dedicated GPU per ephemeral sandbox VM. Sources conflict on availability, so check its docs.
- 🧊 **Northflank.** gVisor where nested virtualisation is unavailable; L4 through H200.
- 📚 **Fly.io.** L40S machines (single secondary source).
- 📚 **E2B.** CPU-only per the sources.

### 🧭 The leading edge

- 📚 **Confidential-computing GPUs.** H100 and Blackwell can attest the device and run in a confidential mode. On H100 the on-package HBM is **not** encrypted, because NVIDIA treats the package as the trust boundary. What is encrypted is CPU-to-GPU traffic, through encrypted bounce buffers over PCIe,<sup id="ref-bounce-buffer"><a href="#note-bounce-buffer">1</a></sup> and that is where most of the overhead comes from. Sources disagree on how much more Blackwell encrypts (HBM, NVLink), so check NVIDIA's own documentation. NVIDIA's [reference architecture](https://docs.nvidia.com/datacenter/cloud-native/confidential-containers/latest/overview.html) runs Kata confidential VMs on [AMD SEV-SNP](https://www.amd.com/en/developer/sev.html) or [Intel TDX](https://www.intel.com/content/www/us/en/developer/tools/trust-domain-extensions/overview.html) with VFIO passthrough. This protects tenants from the *host operator*, not just from each other. The cost is performance; recent work on Blackwell confidential computing is about recovering LLM-serving throughput lost to it.
- 🎮 **A Type-1 hypervisor per workload** ([Edera](https://edera.dev/), per a September 2026 comparison): VM-grade isolation while still sharing the card, instead of dedicating a whole GPU to each tenant.
- 🎮 **Per-sandbox GPUs on cheap isolation.** The commercial push is ephemeral sandboxes that each get a GPU, but only Modal's whole-card approach is consistently documented.

For a GPU SaaS with mutually untrusted tenants: dedicated-GPU VMs with VFIO (Kata or Cloud Hypervisor), plus confidential computing if tenants distrust the operator; MIG where a card must be subdivided; gVisor with `nvproxy` as the cheaper middle option whose boundary is the ioctl surface.

---

## 🔬 6. Research and proposals for the next 5 to 10 years

### 🔬 Papers (arXiv, 2026 unless noted)

- 🐳 **Tyche, composable isolation** ([arXiv:2507.12364](https://arxiv.org/pdf/2507.12364)). A hardware and monitor primitive that unifies enclaves, VMs and containers, so a tenant can carve out its own isolated domain without trusting the layer below. The most direct research answer to "how do you compose isolation layers".
- 📦 **Threat model, taxonomy and measurement.** [AI Sandboxes (arXiv:2606.18532)](https://arxiv.org/html/2606.18532v1) and [AI Code Sandboxes: A Comparative Security Study (arXiv:2606.08433)](https://arxiv.org/pdf/2606.08433) cover attack surface, leakage, CVE history and patch cadence. They give shared vocabulary and numbers instead of vendor claims.
- 🐳 **SandboxEscapeBench** ([arXiv:2603.02277](https://arxiv.org/html/2603.02277v1)). Measures whether frontier LLMs can escape Docker/OCI sandboxes. It makes the attacker side measurable, which is likely to drive the field: a sandbox claim can now be tested against a model.
- 🧱 **Learned capability governance** ([arXiv:2604.11839](https://arxiv.org/abs/2604.11839)). Learns the smallest tool set each task type needs, motivated by a reported 15x overprovisioning ratio. The paper's naming differs between versions, so read it with care.
- 🤖 **Mandatory access control for LLM agents** ([arXiv:2601.11893](https://arxiv.org/pdf/2601.11893)). A MAC framework against privilege escalation between agent components.
- 🧊 **Shrinking the shared kernel from inside.** [Dynamic sandboxing for unprivileged eBPF (arXiv:2308.01983)](https://arxiv.org/pdf/2308.01983) and [compartmentalizing monolithic kernels (arXiv:2404.08716)](https://arxiv.org/pdf/2404.08716), relevant because the shared kernel is the weak point of every tier except VMs.

### 🐧 Kernel proposals and standards

- 🧱 **Landlock extensions.** Much of this has now landed: abstract-socket and signal scoping in ABI 6, pathname unix sockets in ABI 9 and UDP in ABI 10 (see the kernel docs, LWN and kernsec links below). Landlock's default is ambient authority, so every workload still needs an explicit policy.
- 📚 **[eBPF LSM](https://docs.kernel.org/bpf/prog_lsm.html) enforcement** and per-sandbox network policy, for example per-sandbox [TAP devices](https://docs.kernel.org/networking/tuntap.html) with eBPF rules. Reported as becoming the standard pattern for agent network isolation, though the sources are vendor guides, not papers.
- 🎮 **[WASI and the Component Model](https://component-model.bytecodealliance.org/).** A component starts with no ambient authority and can only do what the host grants. Best for tools and functions you can compile, not yet a full dev environment. GPU access ([`wasi:webgpu`](https://github.com/WebAssembly/wasi-webgpu)) is a Phase 2 proposal.

### 🔬 Other research directions

- 🧱 **[CHERI](https://www.cl.cam.ac.uk/research/security/ctsrd/cheri/)** hardware capabilities (Cambridge and ARM Morello) and **[seL4](https://sel4.systems/)**, the verified kernel: capability enforcement in hardware or by proof, instead of by a large trusted kernel.
- 🎮 **Confidential VMs (AMD SEV-SNP, Intel TDX) and confidential GPUs**, covered above.
- 🔹 **In-process isolation** with [Intel MPK](https://man7.org/linux/man-pages/man7/pkeys.7.html) and [ARM MTE](https://docs.kernel.org/arch/arm64/memory-tagging-extension.html).
- 🦀 **Memory-safe VMMs and Rust in the kernel**, which shrink the bug surface beneath every layer.

### 🔮 Where this seems to be heading (opinion)

1. **The shared kernel is the weak point.** The long-term answers either avoid it (microVMs, confidential VMs) or shrink it (Landlock-style scoping, compartmentalization, memory safety).
2. **Policy will matter as much as mechanism.** Static allow-lists overprovision, so least privilege *per task*, possibly learned, is where the agent-specific papers are going.
3. **Composable isolation is the most interesting *research* direction, not a shipping one.** Tyche-style designs would let a tenant nest its own boundary instead of trusting the provider's, but Tyche itself is academic, and no production system offers recursive, tenant-controlled nesting with attestation of the whole stack. What ships today are fixed, one-level versions of the idea, each a small trusted layer that the layer below cannot see into:
   - 📚 **Confidential-VM paravisors.** Microsoft's open-source [OpenHCL](https://openvmm.dev/guide/user_guide/openhcl.html) runs inside Azure confidential VMs at a higher privilege level than the guest OS, on AMD SEV-SNP and Intel TDX, out of the host's reach. Microsoft uses it for confidential VMs and Trusted Launch VMs (with a virtual TPM) on Azure.
   - 🧊 **SEV-SNP privilege levels.** [VMPLs](https://www.amd.com/content/dam/amd/en/documents/epyc-business-docs/white-papers/SEV-SNP-strengthening-vm-isolation-with-integrity-protection-and-more.pdf) split a confidential VM into up to four hardware privilege levels, so a small service module such as [COCONUT-SVSM](https://github.com/coconut-svsm/svsm) can provide services like a virtual TPM, isolated from the guest OS. COCONUT-SVSM has published no releases yet.
   - 🧊 **TDX partitioning.** One [Intel TDX](https://www.intel.com/content/www/us/en/developer/tools/trust-domain-extensions/overview.html) confidential VM can host nested VMs while the host stays outside the trust boundary. In practice cloud providers use it for their own paravisors rather than exposing it to tenants.
   - 🖥️ **[AWS Nitro Enclaves](https://docs.aws.amazon.com/enclaves/latest/user/nitro-enclave.html).** A tenant carves an isolated, attested enclave out of its own instance, and the parent instance cannot see inside. AWS's Nitro hypervisor is still trusted, and there is only one level.
   - 🖥️ **[Android pKVM](https://source.android.com/docs/core/virtualization/architecture).** A small hypervisor runs below a *deprivileged* host kernel, so protected VMs are safe from the host OS. The platform defines the domains, not the tenant.
   - 🐳 **[Confidential Containers](https://confidentialcontainers.org/).** Kata pods inside confidential VMs, so a pod need not trust the node. It composes existing pieces rather than offering a unified primitive.

   [Arm CCA](https://www.arm.com/architecture/security-features/arm-confidential-compute-architecture) brings "realms" with the same aim to Arm and is the next place to watch.

Gaps: I found no paper proposing microVM snapshots specifically for agent isolation, and none on seL4- or CHERI-based agent sandboxes.

---

## 🐡 7. Why isn't OpenBSD the answer?

OpenBSD is one of the most security-focused commodity OSes, so it is a fair question. It is a strong answer for the OS-level tier, but it does not change the tiering in section 3.

Two framing points. The tiers are about **where the trust boundary sits**, not only about CPU-level isolation. And OpenBSD is also a **shared-kernel** design, so a kernel bug still breaks every sandbox on the machine.

### 🐡 What OpenBSD does well

- 🧱 **[`pledge(2)`](https://man.openbsd.org/pledge.2) and [`unveil(2)`](https://man.openbsd.org/unveil.2)** are arguably better designed than seccomp and Landlock. Coarse promises such as `stdio rpath inet` are hard to get wrong, where seccomp filters are easy to write badly. `unveil` limits which parts of the filesystem a process can see.
- 🔹 **Privilege separation** is a core convention in its daemons.
- 🔒 **Exploit mitigations on by default** (W^X, ASLR, stack protector, removal of old code), a small audited codebase, and a good security track record.

### 🚧 Why it is not enough for this problem

1. **The shared-kernel limit applies to it too.** A smaller, cleaner kernel makes an exploit less likely, not impossible. For mutually untrusted tenants, hosted platforms want a second kernel, which OpenBSD alone does not give you.
2. **Only half of it works from outside.** A wrapper *can* confine a program that never calls `pledge`: the second argument, [`execpromises`](https://man.openbsd.org/pledge.2), sets the promises the next `execve` starts with. But `unveil` does not survive `execve` ("the new program starts running without any unveils"), so there is no external way to limit which *files* an arbitrary binary, such as an agent's `pip install` and shell, can see. On Linux, bubblewrap and Landlock launchers do both from outside.
3. **Missing building blocks.** It has rlimits and [`login.conf`](https://man.openbsd.org/login.conf.5), but nothing like cgroups v2 for memory, PIDs and CPU, and no unprivileged user-namespace-style containers. It has no seccomp user-notify equivalent for a supervisor that vets syscalls. Egress control is [`pf`](https://man.openbsd.org/pf.4), which is good but needs root and is not per-process or per-domain.
4. **Ecosystem and hardware.** Agents, toolchains, Python wheels, Node and Docker images assume Linux, and CUDA does not run on OpenBSD, so GPU workloads are out. Its hypervisor, [`vmm(4)`/`vmd`](https://man.openbsd.org/vmm.4), is much less mature than KVM, and the microVM tooling (Firecracker, gVisor, Kata) and snapshot/restore are all Linux and KVM.
5. **Operations.** Cloud vendors do not offer it the way they offer Linux, so there are few managed options.

### ✨ Where it fits

OpenBSD works well as the host or guest for a small, auditable control plane or an egress proxy. For the part that runs untrusted agent code, the tooling is on Linux. For one trusted-ish agent on your own machine, `pledge` and `unveil` are a good fit and arguably simpler than the Linux stack; they just do not scale to the multi-tenant case.

### 🔑 FreeBSD's Capsicum: the capability model Linux never adopted

The other BSD answer is worth knowing because it is a *different model*, not just a cleaner syscall filter. Linux confines a process by subtracting authority with a pile of independent mechanisms: namespaces, seccomp, Landlock, and the confusingly named POSIX capabilities, which are privilege *bits*, not object capabilities. [**Capsicum**](https://man.freebsd.org/capsicum(4)) (FreeBSD 9.0, 2012, from the University of Cambridge and Google) instead gives a process authority *only* through the file descriptors it already holds. It has two primitives:

- 🧱 [**`cap_enter(2)`**, capability mode](https://man.freebsd.org/cap_enter(2)). An irreversible, inherited switch that cuts the process off from every **global namespace**: no `open()` by absolute path, no PIDs, no `sysctl` by name, no mount table. From then on it can only act on descriptors it was handed, and new files come via `openat()` relative to a *directory descriptor* it was delegated.
- 🔑 [**`cap_rights_limit(2)`**](https://man.freebsd.org/cap_rights_limit(2)). Narrows each descriptor to specific rights (`CAP_READ`, `CAP_WRITE`, `CAP_SEEK` and so on), so a descriptor becomes an unforgeable token for exactly the operations you granted.

This is **deny-by-default expressed as a coherent object-capability model**: the same shape the research in section 6 (learned capability governance, MAC for agents) keeps reaching for, shipped in a production OS over a decade ago. Because a process in capability mode cannot resolve DNS or open files by name, Capsicum pairs it with [**Casper**](https://man.freebsd.org/libcasper(3)), a helper process that performs those actions on the sandbox's behalf, vetted by policy. That **broker pattern** is the seccomp-notify supervisor from section 2, the filtering proxy from section 4 and the credential brokering from section 8. Capsicum got there first.

Why it still does not change the tiering:

1. **Shared kernel**, the same as OpenBSD and Linux. A coherent model lowers the odds of a *policy* mistake, not of a kernel bug.
2. **Cooperative, like `pledge`, `unveil` and Landlock self-restriction.** A program must be *refactored* to call `cap_enter` and to receive its resources as descriptors. That is excellent for compartmentalising a program you control, such as a broker or an agent *runtime*, and poor at confining an arbitrary untrusted binary from the outside: an agent's `pip install` and shell expect to open new paths by name, which is the one thing capability mode forbids. FreeBSD's answer for untrusted code is the same two-tier story as Linux: [**jails**](https://man.freebsd.org/jail(8)) and [**bhyve**](https://man.freebsd.org/bhyve(8)) VMs.
3. **Ecosystem and hardware.** The Linux-assumption and CUDA problems from section 5 apply to FreeBSD too.

Its influence outlived its reach. [Capsicum for Linux](https://github.com/google/capsicum-linux) (Google, around 2015) never merged into mainline, and **Landlock is the closest Linux has**, but Landlock is *path*-based self-restriction, not a true descriptor-capability model. If you are building the *broker* in front of an agent sandbox, Capsicum is the cleanest template in a shipping OS. It is not a drop-in confiner for the untrusted code itself.

---

## 🚧 8. What the stack above still misses

Sections 1 to 7 are about *confining the process*. Checked against a real agent deployment, they leave gaps that no layer in the table closes, because the damage happens *outside* the box or *through* a channel the box is meant to allow.

📦 **Persistence after the sandbox exits.** The agent may write only inside the project, but the project is full of things that later run *unsandboxed*: `.git/hooks/*`, `.git/config` ([`core.fsmonitor`](https://git-scm.com/docs/git-config#Documentation/git-config.txt-corefsmonitor), `core.sshCommand`), `.envrc` for [direnv](https://direnv.net/), `.vscode/tasks.json` and `settings.json`, the `Makefile`, `package.json` scripts, and `.bashrc` if `$HOME` is writable. The confinement is perfect, and the payload runs the next time *you* type `git commit` or open the editor. Deny writes to these paths (Landlock rules or read-only bind mounts over them) and review the diff before running anything outside the sandbox.

🔒 **Exfiltration through allowed channels.** A domain allow-list that contains `github.com` also allows pushing your code to an attacker's repo or a gist, and `pypi.org` allows uploading a package. Policy has to be per *destination identity* (this org, this repo, read-only methods), not per domain.

📦 **The model is an exfiltration channel the sandbox cannot see.** Data the agent reads goes into the model's context, and a prompt-injected agent can leak it in its output (for example through a rendered Markdown image URL) without a single syscall from inside the sandbox. Simon Willison's [lethal trifecta](https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/) is the frame: private data, untrusted content and a way to communicate out. Remove one leg, because no sandbox removes it for you.

📦 **Credential brokering instead of credential stripping.** Stripping secrets is the minimum. The stronger pattern is that secrets never enter the sandbox: the egress proxy *injects* a short-lived, narrowly scoped token on the way out, so a compromised agent can only use the credential for what the proxy allows, and cannot copy it.

🐳 **Host-side session sockets.** [D-Bus](https://dbus.freedesktop.org/doc/dbus-specification.html), `ssh-agent`, `gpg-agent`, X11 and Wayland, PulseAudio, and the Docker or Podman socket. X11 alone allows keystroke injection into other windows. A fresh network namespace hides *abstract* unix sockets, because they are per network namespace, but any *pathname* socket you bind-mount in is a door. Landlock ABI 9 can gate those.

📝 **Host kernel knobs.** Every tier except the VM shares the kernel, so turn off what agents do not need: [`kernel.unprivileged_bpf_disabled=1`](https://docs.kernel.org/admin-guide/sysctl/kernel.html), [`kernel.io_uring_disabled=2`](https://docs.kernel.org/admin-guide/sysctl/kernel.html), [`vm.unprivileged_userfaultfd=0`](https://docs.kernel.org/admin-guide/sysctl/vm.html), `dev.tty.legacy_tiocsti=0`, a stricter [`kernel.yama.ptrace_scope`](https://docs.kernel.org/admin-guide/LSM/Yama.html), and [`kernel.perf_event_paranoid=3`](https://docs.kernel.org/admin-guide/sysctl/kernel.html) where the distribution supports it. These are cheaper than any seccomp filter, and they cover processes you forgot to wrap.

🤖 **Resource exhaustion beyond memory and PIDs.** Disk fill (a `tmpfs` with `size=`, or project quotas), inodes, I/O bandwidth ([`io.max`](https://docs.kernel.org/admin-guide/cgroup-v2.html)), CPU ([`cpu.max`](https://docs.kernel.org/admin-guide/cgroup-v2.html)) and wall-clock time. An agent stuck in a loop is the common case, not the exotic one.

🧊 **Lifecycle and reuse.** Sandboxes should be ephemeral and never reused across tenants or tasks, and a warm pool must hand out *clean* snapshots. Reusing a sandbox turns one task's prompt injection into the next task's compromise. Cloned snapshots also share RNG state and ASLR layout unless the guest reseeds ([VM generation ID](https://github.com/firecracker-microvm/firecracker/blob/main/docs/snapshotting/random-for-clones.md)), a known microVM snapshot pitfall.

🧱 **Audit and approval.** You need a record of what the agent did: [Landlock audit](https://docs.kernel.org/admin-guide/LSM/landlock.html) (ABI 7), seccomp [`SECCOMP_RET_LOG`](https://man7.org/linux/man-pages/man2/seccomp.2.html), the proxy's request log, and human approval for irreversible steps such as push, deploy and delete. Without a log you cannot tell an escape from a bug.

📦 **Testing the sandbox itself.** Run escape tests in CI (the x32, io_uring and `TIOCSTI` cases from section 1, plus something like SandboxEscapeBench from section 6) on every kernel and distribution you ship on, because the same sandbox can fail open elsewhere.

🧊 **Side channels and physical access.** [Spectre-class](https://docs.kernel.org/admin-guide/hw-vuln/spectre.html) leaks, SMT sharing and [Rowhammer](https://users.ece.cmu.edu/~yoonguk/papers/kim-isca14.pdf) cross every software boundary, the VM one included. The mitigations are scheduling (no SMT sharing between tenants, [core scheduling](https://docs.kernel.org/admin-guide/hw-vuln/core-scheduling.html)) and hardware. Physical attacks on the bus are out of scope for every tier here. OpenAI has since shown agents in separate microVMs on one host passing secrets through the CPU cache; see [When sandboxed agents talk through the CPU cache]({% post_url 2026-10-24-when-sandboxed-agents-talk-through-the-cpu-cache %}) for that report and a layered defence.

### 🌀 Could quantum help?

Not with isolation. Every boundary in this post is enforced by page tables, privilege levels, the kernel or the hypervisor, and none of them relies on a hard maths problem, so nothing labelled "quantum" makes them stronger or weaker. Quantum does touch agent sandboxing in a few narrower places:

| Quantum technology | Does it help? | Why |
|---|---|---|
| **Quantum computers** ([Shor's algorithm](https://arxiv.org/abs/quant-ph/9508027)) | No, it is a threat | It breaks the RSA and elliptic-curve cryptography that the trust *around* a sandbox depends on. |
| **Post-quantum cryptography** ([ML-KEM, ML-DSA](https://csrc.nist.gov/projects/post-quantum-cryptography)) | Yes, indirectly | Classical algorithms that keep that trust intact once quantum computers arrive. |
| **Quantum random number generators** | No | The kernel's CSPRNG is not the weak point. Cloned snapshots are, and a QRNG does not fix them. |
| **Quantum key distribution** (QKD) | No | It needs dedicated optical links between two sites and says nothing about code on one host. [The NSA](https://www.nsa.gov/Cybersecurity/Quantum-Key-Distribution-QKD-and-Quantum-Cryptography-QC/) and the UK NCSC recommend post-quantum cryptography instead. |
| **Cloud quantum computers** | It is a *new* sandboxing problem | Tenants sharing one quantum processor leak to each other through crosstalk. |

⚛️ **What a quantum computer would break.** It would break the cryptography that lets you *trust* the sandbox, not the sandbox itself:

- 🙋 **Attestation.** SEV-SNP and TDX reports, and NVIDIA's GPU attestation, are signed with ECDSA today. Anyone who can forge them can present a fake confidential VM or GPU, which defeats the "protect tenants from the host operator" model in section 5.
- 🔏 **The egress path.** TLS from the agent to the proxy and from the proxy to the registry, plus SSH to git hosts.
- 🐳 **Supply-chain signatures.** Container images, snapshots, packages and git commits. [Sigstore](https://docs.sigstore.dev/cosign/key_management/overview/)'s default, for example, is ECDSA P-256.

Symmetric cryptography such as AES-256 and SHA-256 stays safe. [Grover's algorithm](https://arxiv.org/abs/quant-ph/9605043) only halves its effective strength.

💭 **The two halves migrate on different clocks.**

1. **Key exchange is urgent now**, because of *[harvest now, decrypt later](https://www.ncsc.gov.uk/whitepaper/next-steps-preparing-for-post-quantum-cryptography)*: traffic recorded today can be decrypted once a large quantum computer exists. Source code and secrets that cross the egress proxy stay sensitive for years. The fix is mostly an upgrade: OpenSSH 10.0 uses the hybrid [`mlkem768x25519-sha256`](https://www.openssh.com/txt/release-10.0) by default, and OpenSSL 3.5 offers [`X25519MLKEM768`](https://datatracker.ietf.org/doc/draft-ietf-tls-ecdhe-mlkem/) by default. A TLS-intercepting proxy has *two* TLS legs, so check both.
2. **Signatures can wait, but take longest to move.** A signature cannot be forged after the fact, so it only matters once a quantum computer exists. But attestation keys are rooted in silicon, in CPU and GPU firmware and vendor PKI, so post-quantum attestation needs new hardware generations and cannot be patched in. NIST's draft transition plan ([IR 8547](https://csrc.nist.gov/pubs/ir/8547/ipd)) deprecates 112-bit RSA and ECC after 2030 and disallows quantum-vulnerable algorithms after 2035. Hardware bought for a sandbox fleet today may still be in service by then, so ask vendors about their post-quantum attestation roadmap.

🧊 **Randomness: the real problem is not where a QRNG would help.** The RNG risk in this post is the snapshot pitfall from earlier in this section: clones of one microVM snapshot start with the same RNG state. Better entropy hardware does not fix that. Reseeding on restore does, via the VM generation ID.

⚛️ **The other direction: sandboxing quantum computers.** If agents start submitting circuits to cloud quantum processors, the isolation problem comes back in new hardware. [Crosstalk side channels in multi-tenant quantum computers](https://arxiv.org/html/2412.10507v1) (NDSS 2025) can identify which algorithm a co-located tenant is running, and the [SWAP attack](https://arxiv.org/html/2502.10115v1) can both spy on a neighbouring circuit and corrupt its results. The proposed defences look familiar: do not place tenants next to each other, the way core scheduling keeps tenants off sibling SMT threads. The classical job-submission stack in front of the processor is still sandboxed with everything in this post.

---

## 📜 A decision guide

- 📝 **Running an agent on your own laptop, your own code?** The OS-level tier (bubblewrap as in Claude Code, Landlock plus seccomp as in Codex, or Sandlock on Linux 6.12 or newer) is proportionate. Add a filtering proxy if the agent has network; Sandlock builds one in, along with a copy-on-write workdir you can review before changes land.
- 🔥 **Running *your users'* code, multi-tenant?** Do not stop at containers. Use a **microVM** (Firecracker, E2B, Kata) or at least **gVisor**, and treat the VM as the boundary. Put OS-level confinement *inside* it as defence in depth.
- 🛠️ **A narrow, pure-compute tool?** Consider **WASM**: the strongest per-feature boundary and trivially dense.
- 📦 **Whatever you pick:** control egress by domain with audit, strip ambient credentials (environment, metadata, mounted sockets, `~/.ssh`), cap resources with cgroups (fork bombs are cheap), protect the files that run *after* the sandbox exits (git hooks, editor tasks, `.envrc`; see section 8), and **fail closed**. A sandbox that silently runs unconfined is the worst outcome.

---

## 📚 Sources

Point-in-time (checked October 2026); vendor docs and 2026 analyses, so verify before relying on specifics.

- Landscape lists: [awesome-AI-sandbox](https://github.com/webcoyote/awesome-AI-sandbox) · [awesome-ai-coding-sandboxes](https://github.com/fhiltscher/awesome-ai-coding-sandboxes) · [coding agent sandboxes list, 2026-05](https://gist.github.com/wincent/2752d8d97727577050c043e4ff9e386e)
- Papers: [Sandlock: Confining AI Agent Code with Unprivileged Linux Primitives (arXiv:2605.26298)](https://arxiv.org/abs/2605.26298) · [AI Code Sandboxes: A Comparative Security Study (arXiv:2606.08433)](https://arxiv.org/pdf/2606.08433)
- Guides: [Northflank, how to sandbox AI agents](https://northflank.com/blog/how-to-sandbox-ai-agents) · [digitalapplied, 3 isolation patterns](https://www.digitalapplied.com/blog/ai-agent-sandboxing-isolation-patterns-2026) · [Notes on sandboxing untrusted code](https://gist.github.com/mavdol/2c68acb408686f1e038bf89e5705b28c)
- Codex: [OpenAI Codex security](https://developers.openai.com/codex/security) · [Codex sandboxing architecture](https://www.mintlify.com/openai/codex/architecture/sandboxing) · [Simon Willison, Codex sandbox investigation](https://simonwillison.net/2025/Nov/9/codex-sandbox-investigation/)
- Claude Code and Gemini CLI: [Claude Code sandboxing docs](https://code.claude.com/docs/en/sandboxing) · [anthropic sandbox-runtime](https://github.com/anthropics/sandbox-runtime) · [Gemini CLI sandboxing](https://geminicli.com/docs/cli/sandbox/)
- Landlock: [Landlock kernel docs (ABI list)](https://docs.kernel.org/userspace-api/landlock.html) · [Landlock news and ABI history](https://landlock.io/news/5/) · [LWN, Landlock IPC scoping](https://lwn.net/Articles/989073/) · [LSM pathname unix-socket scope (2026)](https://kernsec.org/pipermail/linux-security-module-archive/2026-February/055149.html)
- Hosted platforms: [E2B vs Daytona vs Modal](https://www.developersdigest.tech/blog/ai-agent-code-sandbox-comparison-2026) · [E2B, Daytona and Firecracker overview](https://www.spheron.network/blog/ai-agent-code-execution-sandbox-e2b-daytona-firecracker/) · [self-hostable comparison](https://bex.co/blog/2026/09/14/ai-agent-sandbox-market-e2b-modal-daytona)
- Kubernetes: [Running Agents with Agent Sandbox](https://kubernetes.io/blog/2026/03/20/running-agents-on-kubernetes-with-agent-sandbox) · [agent-sandbox docs](https://agent-sandbox.sigs.k8s.io/docs/getting_started/overview/) · [Google OSS blog, why Kubernetes needs an agent standard](https://opensource.googleblog.com/2025/11/unleashing-autonomous-ai-agents-why-kubernetes-needs-a-new-standard-for-agent-execution.html)
- AWS: [hosting coding agents on Bedrock AgentCore](https://aws.amazon.com/blogs/machine-learning/its-safe-to-close-your-laptop-now-hosting-coding-agents-on-amazon-bedrock-agentcore/) · [CSA, AgentCore as enterprise attack surface](https://labs.cloudsecurityalliance.org/research/csa-research-note-bedrock-agentcore-enterprise-attack-surfac/)
- GPU isolation: [Northflank, GPU sandboxes](https://northflank.com/blog/gpu-sandboxes) · [GPU isolation fault line: gVisor, Kata, Edera](https://bex.co/blog/2026/09/11/gpu-isolation-fault-line-gvisor-kata-edera) · [NVIDIA Confidential Containers reference architecture](https://docs.nvidia.com/datacenter/cloud-native/confidential-containers/latest/overview.html) · [gVisor GPU support](https://gvisor.dev/docs/user_guide/gpu/) · [Multi-tenant GPU security](https://introl.com/blog/multi-tenant-gpu-security-isolation-strategies-shared-infrastructure-2025) · [Blackwell confidential-computing LLM serving (arXiv:2606.23969)](https://arxiv.org/pdf/2606.23969) · [One GPU per sandbox: Modal vs E2B and Daytona](https://bex.co/blog/2026/09/05/modal-gpu-sandbox-vs-daytona-e2b-cpu-isolation) · [What are GPU sandboxes?](https://www.thundercompute.com/blog/what-are-gpu-sandboxes) · [E2B vs Daytona vs Modal](https://drydock.si/guides/e2b-vs-daytona-vs-modal)
- Research: [Tyche (arXiv:2507.12364)](https://arxiv.org/pdf/2507.12364) · [AI Sandboxes: threat model and taxonomy (arXiv:2606.18532)](https://arxiv.org/html/2606.18532v1) · [SandboxEscapeBench (arXiv:2603.02277)](https://arxiv.org/html/2603.02277v1) · [Learned capability governance (arXiv:2604.11839)](https://arxiv.org/abs/2604.11839) · [MAC for LLM agents (arXiv:2601.11893)](https://arxiv.org/pdf/2601.11893) · [Unprivileged eBPF dynamic sandboxing (arXiv:2308.01983)](https://arxiv.org/pdf/2308.01983) · [Kernel compartmentalization (arXiv:2404.08716)](https://arxiv.org/pdf/2404.08716) · [Cosmonic, choosing an agent sandbox](https://cosmonic.com/ai-sandbox/choosing-an-agent-sandbox/) · [yeet.cx, sandbox an AI coding agent on Linux](https://yeet.cx/topical-takes/sandbox-ai-coding-agent-linux) · [h5i, sandboxing AI agents landscape](https://h5i.dev/blog/sandboxing-ai-agents-landscape/)
- Sandlock: [repository](https://github.com/multikernel/sandlock) · [architecture](https://github.com/multikernel/sandlock/blob/main/docs/architecture.md) · [network model](https://github.com/multikernel/sandlock/blob/main/docs/network.md) · [protection opt-out](https://github.com/multikernel/sandlock/blob/main/docs/sandbox-reference.md#protection-opt-out) · [prompt-injection defenses](https://github.com/multikernel/sandlock/blob/main/docs/prompt_injection.md) · [sandlock-oci](https://github.com/multikernel/sandlock/blob/main/crates/sandlock-oci/README.md) · [paper (arXiv:2605.26298)](https://arxiv.org/html/2605.26298v1)
- NVIDIA OpenShell: [repository](https://github.com/NVIDIA/OpenShell) · [architecture](https://docs.nvidia.com/openshell/latest/about/architecture) · [support matrix](https://docs.nvidia.com/openshell/latest/about/support-matrix) · [sandbox runtimes](https://docs.nvidia.com/openshell/latest/how-it-works/sandboxes/runtimes) · [policies](https://docs.nvidia.com/openshell/latest/how-it-works/policies/overview) · [network rules](https://docs.nvidia.com/openshell/latest/how-it-works/policies/network-rules) · [policy advisor](https://docs.nvidia.com/openshell/latest/how-it-works/policies/advisor) · [policy prover](https://docs.nvidia.com/openshell/latest/how-it-works/policies/prover) · [NVIDIA press release, Agent Toolkit and OpenShell (16 March 2026)](https://investor.nvidia.com/news/press-release-details/2026/NVIDIA-Ignites-the-Next-Industrial-Revolution-in-Knowledge-Work-With-Open-Agent-Development-Platform/default.aspx) · [Let's Data Science, Open Agent Safety Platform and Sentry](https://letsdatascience.com/news/nvidia-launches-hardware-backed-ai-agent-safety-platform-7ff43d11) · [NVIDIA, OpenShell works with Claude Code](https://perspectives.nvidia.com/nvidia-openshell/agent-sandbox-works-claude-code-out-of-box/)
- Production approximations of composable isolation: [OpenHCL](https://openvmm.dev/guide/user_guide/openhcl.html) · [OpenVMM repository](https://github.com/microsoft/openvmm) · [AMD SEV-SNP white paper (VMPLs)](https://www.amd.com/content/dam/amd/en/documents/epyc-business-docs/white-papers/SEV-SNP-strengthening-vm-isolation-with-integrity-protection-and-more.pdf) · [COCONUT-SVSM](https://github.com/coconut-svsm/svsm) · [Azure confidential VMs](https://learn.microsoft.com/en-us/azure/confidential-computing/confidential-vm-overview) · [AWS Nitro Enclaves](https://docs.aws.amazon.com/enclaves/latest/user/nitro-enclave.html) · [Android pKVM architecture](https://source.android.com/docs/core/virtualization/architecture) · [Confidential Containers](https://confidentialcontainers.org/) · [Arm CCA](https://www.arm.com/architecture/security-features/arm-confidential-compute-architecture)
- Capsicum: [capsicum(4)](https://man.freebsd.org/capsicum(4)) · [cap_enter(2)](https://man.freebsd.org/cap_enter(2)) · [cap_rights_limit(2)](https://man.freebsd.org/cap_rights_limit(2)) · [libcasper(3)](https://man.freebsd.org/libcasper(3)) · [Capsicum: practical capabilities for UNIX (USENIX Security 2010)](https://www.cl.cam.ac.uk/research/security/capsicum/papers/2010usenix-security-capsicum-website.pdf) · [Capsicum for Linux](https://github.com/google/capsicum-linux)
- Corrections and section 8: [OpenBSD pledge(2)](https://man.openbsd.org/pledge.2) · [OpenBSD unveil(2)](https://man.openbsd.org/unveil.2) · [NVIDIA, confidential computing on H100](https://developer.nvidia.com/blog/confidential-computing-on-h100-gpus-for-secure-and-trustworthy-ai/) · [Confidential LLM inference across CPU and GPU TEEs (arXiv:2509.18886)](https://arxiv.org/pdf/2509.18886) · [Simon Willison, the lethal trifecta](https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/) · [NIST FIPS 203 (ML-KEM)](https://csrc.nist.gov/pubs/fips/203/final) · [NIST FIPS 204 (ML-DSA)](https://csrc.nist.gov/pubs/fips/204/final) · [NIST IR 8547 (draft)](https://csrc.nist.gov/pubs/ir/8547/ipd) · [OpenSSH 10.0 release notes](https://www.openssh.com/txt/release-10.0) · [OpenSSL 3.5 PQC](https://www.helpnetsecurity.com/2025/04/09/openssl-3-5-0-released/) · [Crosstalk side channels in multi-tenant NISQ computers (NDSS 2025)](https://arxiv.org/html/2412.10507v1) · [SWAP attack (arXiv:2502.10115)](https://arxiv.org/html/2502.10115v1)

## 📒 Notes

<a id="note-bounce-buffer"></a>1. **Encrypted bounce buffers.** A confidential VM's memory is encrypted by the CPU with a key only the CPU holds, so the GPU cannot DMA into it directly: it would read ciphertext. Instead, the driver inside the VM encrypts the data itself, with a session key agreed with the GPU during attestation, and copies it into a separate, *shared* region of ordinary system memory: the bounce buffer. The GPU fetches it from there over PCIe and decrypts it on the chip, and results come back the same way in reverse. The host, the hypervisor and anyone probing the PCIe bus only ever see ciphertext. The price is an extra copy plus a CPU-side encrypt or decrypt on every transfer, which hurts most for workloads that move a lot of data relative to the compute they do. The longer-term fix is PCIe link encryption (IDE) with TEE-I/O and TDISP, which would let a trusted device DMA straight into the VM's private memory and remove the bounce. <a href="#ref-bounce-buffer">↩</a>
