---
title: "Hardening a shared Linux host against cache covert channels"
---

The [previous post]({% post_url 2026-10-24-when-sandboxed-agents-talk-through-the-cpu-cache %}) explained how agents in separate microVMs passed secrets to each other through the CPU cache, why no kind of VM stops that on its own, and what a layered defence looks like. It stayed at the level of *what* to do. This post is the *how*: one Linux host running KVM guests (Firecracker or QEMU), taken from the default configuration to one where agents in different trust domains share as little hardware as the machine allows, with the commands, the files they touch, and how to check that each step did something.

Two things up front.

- **This does not get you to zero.** The previous post's [conclusion]({% post_url 2026-10-24-when-sandboxed-agents-talk-through-the-cpu-cache %}#-what-mitigated-means-here) still holds: on shared hardware you lower bandwidth and raise cost, you do not remove the channel. If two agents must *never* communicate (one holds secrets, the other can reach the network), put them on separate physical hosts and stop reading here. Everything below is for agents that have to share a box.
- **Order matters.** The steps run from cheapest and most effective to most fiddly. Removing shared cores closes more channels than any cache partitioning does, and cache partitioning is worth little while two tenants still share a core.

<div class="terms" markdown="1">

**📖 Terms in this post**

- **Trust domain.** A group of workloads allowed to see each other's data. Every step here is about keeping *different* domains apart; agents inside one domain can share freely.
- **SMT sibling.** One of the two hardware threads on a single core (Intel calls SMT Hyper-Threading). Siblings share the L1 and L2 caches, the TLB, branch predictors and execution ports. ([Simultaneous multithreading](https://en.wikipedia.org/wiki/Simultaneous_multithreading))
- **L3 domain.** The set of CPUs that share one last-level cache: usually a socket on Intel, a core complex (CCX) on AMD EPYC. Two VMs in different L3 domains do not share a cache at all.
- **cgroup v2 and cpuset.** Linux control groups put processes into a tree and apply limits to each branch. The cpuset controller limits which CPUs and memory nodes a branch may use. ([Linux cgroup v2](https://docs.kernel.org/admin-guide/cgroup-v2.html))
- **resctrl, CAT, MBA, CMT and MBM.** `resctrl` is the Linux filesystem for the processor's cache and memory-bandwidth controls: Cache Allocation Technology (CAT) reserves cache ways, Memory Bandwidth Allocation (MBA) throttles memory traffic, and Cache Monitoring (CMT) and Memory Bandwidth Monitoring (MBM) report usage per group. AMD exposes the same controls under the same interface. ([Linux resctrl](https://docs.kernel.org/filesystems/resctrl.html))
- **Capacity bitmask (CBM).** A resctrl allocation written as a bitmask, one bit per cache way. `0x0f` means "the lowest four ways".
- **KSM.** Kernel Samepage Merging, which keeps one shared copy of identical memory pages across VMs. ([Linux KSM](https://docs.kernel.org/admin-guide/mm/ksm.html))
- **PMU and RAPL.** The performance monitoring unit counts hardware events such as cache misses; RAPL reports energy use. Both make excellent receivers for a covert channel. ([perf_event_open(2)](https://man7.org/linux/man-pages/man2/perf_event_open.2.html) · [Linux powercap](https://docs.kernel.org/power/powercap/powercap.html))
- **Jailer.** Firecracker's launcher, which drops privileges and places each microVM in its own cgroups, namespaces and chroot before it starts. ([Firecracker jailer](https://github.com/firecracker-microvm/firecracker/blob/main/docs/jailer.md))

</div>

> Point-in-time (late October 2026). Commands assume a recent mainline kernel, cgroup v2, systemd and util-linux 2.40 or later, run as root. Try them on a host you can reboot. Example output is illustrative; your topology will differ.

## 🗺️ Step 0: map the machine

You cannot keep tenants off shared hardware without knowing what is shared. Three questions: which CPUs are SMT siblings, which CPUs share an L3, and which belong to which NUMA node.

```sh
# One line per logical CPU: core, socket, NUMA node, and the cache IDs it uses.
lscpu -e=CPU,CORE,SOCKET,NODE,CACHE

# Which logical CPUs share CPU 0's core, and CPU 0's last-level cache.
cat /sys/devices/system/cpu/cpu0/topology/thread_siblings_list
cat /sys/devices/system/cpu/cpu0/cache/index3/shared_cpu_list

# Every distinct L3 domain on the host.
cat /sys/devices/system/cpu/cpu*/cache/index3/shared_cpu_list | sort -u
```

On a two-socket server you might see two L3 domains, `0-15,32-47` and `16-31,48-63`, where CPU *n* and CPU *n+32* are siblings. On an AMD EPYC part there are many more, one per core complex, often eight cores each. That second case is good news: small L3 domains mean you can give each trust domain its own cache without buying a whole socket per tenant. [hwloc](https://www.open-mpi.org/projects/hwloc/)'s `lstopo` draws the same thing as a picture, which is worth printing and taping to the wall.

Write the result down as a table. Everything else in this post is applying it.

| Domain | L3 domain | Physical cores | Logical CPUs (SMT off) |
|---|---|---|---|
| host housekeeping | 0 | 0–1 | 0–1 |
| tenant A | 0 | 2–7 | 2–7 |
| tenant B | 1 | 16–23 | 16–23 |
| tenant C | 1 | 24–31 | 24–31 |

In this example A has an L3 domain to itself apart from the host, while B and C share one. B and C are the pair that need [step 5](#-step-5-partition-the-last-level-cache-with-resctrl); A mostly does not.

## 🧵 Step 1: stop sharing cores between domains

Two tenants on sibling threads share nearly everything inside the core. This one step removes the L1, L2, TLB, branch-predictor and port-contention channels, and it is the prerequisite for most of what follows ([TLBleed]({% post_url 2026-10-24-when-sandboxed-agents-talk-through-the-cpu-cache %}#-seventeen-years-of-cross-tenant-channels) went straight through a CAT-partitioned cache via the TLB).

The blunt option is to turn SMT off:

```sh
cat /sys/devices/system/cpu/smt/control     # on, off, forceoff, notsupported, notimplemented
echo off > /sys/devices/system/cpu/smt/control
```

To make it permanent, add `nosmt` to the kernel command line, or use `mitigations=auto,nosmt`, which turns on every CPU-bug mitigation and disables SMT whenever the CPU needs that to be fully mitigated.

The cheaper option, if you want to keep SMT's throughput, is **core scheduling**: tasks carry a cookie, and the kernel only lets tasks with the same cookie run on sibling threads at the same time. util-linux ships a `coresched` command for it:

```sh
# Start a microVM with a fresh cookie: its threads may share a core with
# each other, never with anything else.
coresched new -- firecracker --api-sock /run/fc-a.sock

# Give an already running VMM (and all its threads) a new cookie.
coresched new -t tgid --dest "$VMM_PID"

# Check.
coresched get --source "$VMM_PID"
```

Each VM gets its own cookie, so a VM's two vCPUs can sit on one core's siblings, but two different VMs never do. Two limits: the kernel must be built with `CONFIG_SCHED_CORE`, and core scheduling only stops *simultaneous* sharing. Tenants can still take turns on a core, which [step 2](#-step-2-pin-each-domain-to-its-own-cores) removes and [step 4](#-step-4-keep-the-cpu-bug-mitigations-on-and-flush-on-switch) cleans up after. ([Linux core scheduling](https://docs.kernel.org/admin-guide/hw-vuln/core-scheduling.html) · [coresched(1)](https://man7.org/linux/man-pages/man1/coresched.1.html))

## 📌 Step 2: pin each domain to its own cores

Without pinning, the scheduler moves vCPU threads wherever there is room, so over a day every tenant runs on every core and leaves state behind for whoever comes next. Pinning fixes each domain to the cores in your table for the life of the VM, as AWS Nitro does for fixed-performance instances.

With cgroup v2 cpusets, give each domain its own branch of the tree and make it a **partition root**, which means its CPUs are exclusive: no sibling cgroup may use them.

```sh
cd /sys/fs/cgroup
echo +cpuset > cgroup.subtree_control

mkdir tenant-a
echo 2-7 > tenant-a/cpuset.cpus
echo 0   > tenant-a/cpuset.mems
echo root > tenant-a/cpuset.cpus.partition   # or "isolated" to also turn off load balancing
cat tenant-a/cpuset.cpus.partition            # "root"; "root invalid (...)" says why it failed
```

Then move the host's own work off the tenant cores, so system daemons and interrupts do not wander onto them:

```sh
systemctl set-property --runtime system.slice AllowedCPUs=0-1
systemctl set-property --runtime user.slice   AllowedCPUs=0-1
# and on the kernel command line: irqaffinity=0-1
```

Firecracker's jailer can place each microVM in its cgroup before the guest runs a single instruction:

```sh
jailer --id vm-a --exec-file /usr/bin/firecracker --uid 1001 --gid 1001 \
  --cgroup-version 2 --parent-cgroup tenant-a \
  --cgroup cpuset.cpus=2-7 --cgroup cpuset.mems=0 \
  -- --api-sock /run/firecracker.socket
```

For a one-off VM outside the jailer, `systemd-run --scope -p AllowedCPUs=2-7 -p AllowedMemoryNodes=0 -- qemu-system-x86_64 ...` does the same.

If tenants share a domain's cores (several VMs inside tenant A), pin each vCPU thread to its own core with `taskset -pc` so they do not take turns either. Firecracker names its vCPU threads `fc_vcpu 0`, `fc_vcpu 1` and so on, which makes them easy to find under `/proc/<pid>/task/*/comm`.

**On Kubernetes** the kubelet does the per-node part. The static CPU manager policy gives Guaranteed pods with whole-number CPU requests exclusive CPUs; `full-pcpus-only=true` makes it hand out whole physical cores so two pods never share siblings, and `prefer-align-cpus-by-uncorecache` (GA in 1.36) prefers CPUs from a single L3 domain. ([Kubernetes CPU management policies](https://kubernetes.io/docs/tasks/administer-cluster/cpu-management-policies/))

```yaml
# KubeletConfiguration
cpuManagerPolicy: static
cpuManagerPolicyOptions:
  full-pcpus-only: "true"
  prefer-align-cpus-by-uncorecache: "true"
reservedSystemCPUs: "0-1"
```

That keeps pods off each other's cores, not off each other's L3. Pods from different trust domains still need separate nodes, enforced with taints and anti-affinity as in [layer 1]({% post_url 2026-10-24-when-sandboxed-agents-talk-through-the-cpu-cache %}#layer-1-placement-removes-the-hardware-channels) of the previous post.

## 🔁 Step 3: turn off memory deduplication

KSM is what makes Flush+Reload and Flip Feng Shui work across VMs. Turning it off costs memory and nothing else.

```sh
cat /sys/kernel/mm/ksm/run            # 0 stopped, 1 running, 2 stopped and unmerged
echo 2 > /sys/kernel/mm/ksm/run       # stop, and split every page already merged
cat /sys/kernel/mm/ksm/pages_shared   # should fall to 0
```

`echo 0` only stops new merging and leaves existing shared pages shared, so use `2`. Make it stick across reboots with a tmpfiles rule, and disable any tuning daemon that would turn it back on:

```sh
echo 'w /sys/kernel/mm/ksm/run - - - - 2' > /etc/tmpfiles.d/ksm-off.conf
systemctl disable --now ksmtuned.service 2>/dev/null
```

KSM only merges memory a process has marked as mergeable. QEMU marks guest memory that way by default, and `-machine mem-merge=off` stops it. Firecracker's [production host guide](https://github.com/firecracker-microvm/firecracker/blob/main/docs/prod-host-setup.md) still asks you to turn KSM off host-wide, and it is the safer rule: it does not depend on every process on the host behaving.

## 🧹 Step 4: keep the CPU-bug mitigations on, and flush on switch

This step is about the *transient-execution* bugs (Spectre, MDS, L1TF and the rest) rather than plain cache sharing, but the two travel together: a covert channel between cooperating agents uses the same receivers, and an unmitigated bug turns a covert channel into a side channel against an agent that is not cooperating.

Start by seeing what the kernel thinks of this CPU:

```sh
grep -r . /sys/devices/system/cpu/vulnerabilities/
```

Anything reading `Vulnerable`, or `SMT vulnerable` while SMT is on, needs attention. On recent kernels the `old_microcode` file says whether the microcode is behind the version the kernel knows to be current; update it before anything else.

Recent kernels group the mitigations by **attack vector** so you can say what the machine is for instead of listing bugs. The defaults already cover guest-to-guest and guest-to-host; what you add for a multi-tenant agent host is full cross-thread protection:

```sh
# kernel command line
mitigations=auto,nosmt
```

Do not use `no_guest_guest` or `no_cross_thread` on a host that runs more than one tenant. ([Attack vector controls](https://docs.kernel.org/admin-guide/hw-vuln/attack_vector_controls.html))

Then the flushes for cores that are shared in time:

- `spectre_v2_user=on` issues an indirect branch prediction barrier (IBPB) on every switch between user tasks, so the next tenant does not inherit what the predictor learned from the last one. The default, `auto`, only does this for tasks that ask.
- `kvm-intel.vmentry_l1d_flush=always` empties the L1 data cache on every entry into a guest, on Intel CPUs affected by L1TF. The default, `cond`, skips the flush when it judges nothing sensitive ran in between. ([Linux: L1TF](https://docs.kernel.org/admin-guide/hw-vuln/l1tf.html))
- `l1d_flush=on` lets individual processes ask for an L1D flush when they are switched out, through `prctl(PR_SET_SPECULATION_CTRL, PR_SPEC_L1D_FLUSH, ...)`. Useful for a VMM or broker that handles secrets. ([Linux: L1D flushing](https://docs.kernel.org/admin-guide/hw-vuln/l1d_flush.html))

With steps 1 and 2 in place, tenants rarely share a core at all, so these flushes are cheap insurance rather than a hot path.

## 🧱 Step 5: partition the last-level cache with resctrl

Tenants B and C from the table still share an L3. CAT lets you give each of them its own cache ways, so one can only evict its own lines. Prime+Probe across the boundary stops working, because the sender can no longer push the receiver's lines out.

Check the CPU supports it, then mount the filesystem:

```sh
grep -o -w 'rdt_a\|cat_l3\|cdp_l3\|mba\|cqm_llc\|cqm_mbm_total' /proc/cpuinfo | sort -u
mount -t resctrl resctrl /sys/fs/resctrl

cat /sys/fs/resctrl/info/L3/cbm_mask      # all ways, e.g. 7ff = 11 ways
cat /sys/fs/resctrl/info/L3/num_closids   # how many groups you can have, often 16 or fewer
cat /sys/fs/resctrl/info/L3/min_cbm_bits
cat /sys/fs/resctrl/info/L3/bit_usage     # who uses which ways today
cat /sys/fs/resctrl/info/L3/sparse_masks  # 0 means each mask must be one contiguous run
```

`bit_usage` deserves a careful look. Ways marked `H` are used by hardware: on many Intel servers that is DDIO, where network cards write incoming packets straight into the cache, the mechanism [NetCAT]({% post_url 2026-10-24-when-sandboxed-agents-talk-through-the-cpu-cache %}#-seventeen-years-of-cross-tenant-channels) abused. Keep tenants off those ways and leave them to the host.

Every task starts in the root group, which by default owns every way. Shrink it first, or exclusive groups cannot be created. With an 11-way cache (`7ff`) and two ways (`600`) used by hardware, one possible split for L3 domain 1 is:

```sh
cd /sys/fs/resctrl

# Root group: the host keeps the two hardware ways plus one more.
echo "L3:0=7ff;1=700" > schemata

mkdir tenant-b tenant-c
echo "L3:0=7ff;1=00f" > tenant-b/schemata    # ways 0-3
echo "L3:0=7ff;1=0f0" > tenant-c/schemata    # ways 4-7
cat */schemata schemata                      # check: no two masks overlap on domain 1
```

Every group has a mask for every L3 instance, so the `0=7ff` entries are there only because each group has to have *some* mask on domain 0. Neither tenant runs there, so it does not matter. It does stop you using resctrl's `exclusive` mode, which makes the kernel refuse overlapping masks but checks every instance at once: to use it, partition domain 0 the same way, so no two groups overlap anywhere. Either way, what keeps B and C apart is that their masks on domain 1 share no bits.

Then put the tenants in their groups. Since step 2 pinned each tenant to fixed cores, the simplest way is by CPU: a task that is still in the root group uses the allocation of the group that owns the CPU it is running on.

```sh
echo 16-23 > tenant-b/cpus_list
echo 24-31 > tenant-c/cpus_list
```

The other way is by task, writing each thread ID to the group's `tasks` file one at a time. That moves one *thread*, not a whole process, and threads created later inherit the group of the thread that created them. A VMM started inside the group is covered; one moved in after it started needs every existing thread moved.

Memory bandwidth is the next shared thing down, and MBA can throttle it in the same schemata file (`MB:1=40` caps a group at about 40% on domain 1). Treat it as lowering the bandwidth of a memory-bus channel, not closing it: MBA is approximate throttling, not isolation.

Know the limits before relying on this:

- **Not persistent.** resctrl starts empty at every boot. Put the setup in a systemd unit that runs before your VMs start.
- **Few groups, few ways.** Sixteen groups and eleven to fifteen ways is typical, so CAT separates a handful of trust domains per L3, not hundreds of tenants. That is another reason to use the L3 domain table from step 0 first.
- **The L3 only.** CAT does nothing for the coherence directory, DRAM banks, the interconnect or frequency. Colouring those ([Marghera]({% post_url 2026-10-24-when-sandboxed-agents-talk-through-the-cpu-cache %}#layer-2-harden-hosts-that-must-be-shared)) is not available in mainline Linux.

## 🔋 Step 6: take away the free receivers

A covert channel needs a receiver that can measure something. Some measurements are much easier with help from the host, so do not hand it out.

- **Energy counters.** Since the [PLATYPUS](https://platypusattack.com/) fix in late 2020 (CVE-2020-8694), the RAPL `energy_uj` files are readable by root only. Check that nothing on your host loosens that, and do not pass power or energy MSRs through to guests.

  ```sh
  ls -l /sys/class/powercap/intel-rapl:*/energy_uj   # expect -r-------- root
  ```

- **Performance counters in guests.** A virtual PMU gives a guest exact cache-miss counts, a far better receiver than timing loads. Unless guests need profiling, turn it off: host-wide with `kvm.enable_pmu=0`, or per VM in QEMU with `-cpu host,pmu=off`. Check from inside a guest: `perf stat -e cache-misses true` should report the event as not supported.
- **Performance counters on the host.** Keep `kernel.perf_event_paranoid` at 2 or higher so unprivileged host processes (a VMM after it drops privileges, an agent's helper) cannot read system-wide counters.

Do not bother trapping `rdtsc`. It is slow, and a counting thread rebuilds a fine-grained clock anyway ([Fantastic Timers](https://gruss.cc/files/fantastictimers.pdf)).

## ⚖️ Step 7: fixed quotas for what is still shared

The CPU-contention and storage channels in OpenAI's report did not need a shared cache at all: one agent's load changed the other's speed. Hard caps make each tenant's performance independent of its neighbours.

```sh
echo "600000 100000" > /sys/fs/cgroup/tenant-a/cpu.max   # 6 CPUs' worth, in every 100 ms window
echo "259:0 rbps=200000000 wbps=100000000 riops=20000 wiops=10000" \
  > /sys/fs/cgroup/tenant-a/io.max                       # per disk, by major:minor
```

With step 2's exclusive cores, `cpu.max` mostly matters inside a domain. `io.max` matters more: the "acoustic modem" channel in the report was bursts of writes to shared storage. Better still, give each tenant its own disk or volume, and its own instances of every shared service (DNS resolver, HTTP proxy, package mirror, TLS cache), as in [layer 3]({% post_url 2026-10-24-when-sandboxed-agents-talk-through-the-cpu-cache %}#layer-3-remove-shared-software-state).

## 🔬 Step 8: check that it worked

Configuration that nobody checks drifts. Three kinds of check, from cheapest to most convincing.

### Audit the configuration

A short script that prints the state of every step, suitable for a cron job or a node health check:

```sh
#!/bin/sh
# Report the covert-channel hardening state of this host.
echo "smt:          $(cat /sys/devices/system/cpu/smt/control)"
echo "ksm run:      $(cat /sys/kernel/mm/ksm/run)  shared pages: $(cat /sys/kernel/mm/ksm/pages_shared)"
echo "cmdline:      $(tr ' ' '\n' < /proc/cmdline | grep -E '^(mitigations|nosmt|spectre_v2_user|l1d_flush|kvm|irqaffinity)' | tr '\n' ' ')"
echo "perf paranoid: $(cat /proc/sys/kernel/perf_event_paranoid)"
grep -l -r 'Vulnerable' /sys/devices/system/cpu/vulnerabilities/ 2>/dev/null | sed 's/^/VULNERABLE:   /'
for g in /sys/fs/cgroup/tenant-*; do
  [ -d "$g" ] && echo "$(basename "$g"): cpus=$(cat "$g/cpuset.cpus.effective") partition=$(cat "$g/cpuset.cpus.partition")"
done
if [ -d /sys/fs/resctrl/info ]; then
  echo "L3 bit usage: $(cat /sys/fs/resctrl/info/L3/bit_usage)"
else
  echo "resctrl:      not mounted"
fi
```

### Attack your own host

The only convincing test is a channel that worked before and does not work after. Use published research code between two of your own test VMs, placed the way real tenants would be:

- [Mastik](https://github.com/0xADE1A1DE/Mastik), Yuval Yarom's toolkit, implements Prime+Probe on L1 and L3 and Flush+Reload, and is the standard starting point.
- [CJAG](https://github.com/IAIK/CJAG), from the [Hello from the Other Side]({% post_url 2026-10-24-when-sandboxed-agents-talk-through-the-cpu-cache %}#-seventeen-years-of-cross-tenant-channels) authors, is a cross-VM LLC covert channel that finds its own eviction sets and synchronises sender and receiver without help.

Measure the bit error rate and bits per second before you start, then after each step. What you should expect to see:

| After | L1 / SMT channel | LLC Prime+Probe | Flush+Reload | Memory bus |
|---|---|---|---|---|
| default host | works | works | works if KSM merged a page | works |
| step 1 (SMT off or core scheduling) | gone between domains | works | works | works |
| step 3 (KSM off) | gone | works | gone | works |
| step 5 (CAT, separate ways) | gone | mostly noise | gone | works, slower with MBA |
| separate L3 domains | gone | gone | gone | still possible |

If a row does not match, the step is not doing what you think: a thread outside the cpuset, a resctrl group missing a CPU, a QEMU guest still marked mergeable. That is the point of running it.

### Watch for it in production

The same resctrl filesystem reports per-group cache occupancy and memory traffic, with no performance counters needed:

```sh
mkdir -p /sys/fs/resctrl/tenant-b/mon_groups/watch
cat /sys/fs/resctrl/tenant-b/mon_data/mon_L3_01/llc_occupancy    # bytes of L3 the group holds
cat /sys/fs/resctrl/tenant-b/mon_data/mon_L3_01/mbm_total_bytes  # memory traffic so far
```

Or per cgroup with `perf`:

```sh
perf stat -a -G tenant-b -e LLC-loads,LLC-load-misses -I 10
```

A covert channel looks like a *regular* signal: cache misses or memory traffic switching on and off at a fixed period, or a small working set with a miss rate that ordinary code of that size never has. Sample every few milliseconds and look for strong periodicity (an autocorrelation peak, or a sharp line in a Fourier transform). Treat it as a tripwire, as [layer 5]({% post_url 2026-10-24-when-sandboxed-agents-talk-through-the-cpu-cache %}#layer-5-detect-and-respond) of the previous post did: a patient sender can add jitter and hide in noise, and detectors trained on known channels miss new ones.

## 🔒 What is closed

"Closed" here means closed *between trust domains*, once the step is in place and the audit in step 8 says it still is. Each holds only while the steps before it do: cache partitioning means little if two tenants still share a core.

- 🧵 **L1 and L2 caches, the TLB, branch predictors and execution ports**, by steps 1 and 2. No two domains run on one core at the same time, or one after the other, so none of the core-private state is shared. This is the largest class of channels, and the fastest: it covers TLBleed, port contention and most of the MDS family.
- 🧹 **State left behind on a shared core**, by step 4. Where a core is still shared in time, the predictor barrier and L1 flush stop the next tenant reading what the last one left. Current microcode and `mitigations=auto,nosmt` keep the known transient-execution bugs from turning a covert channel into a side channel against an agent that is not cooperating.
- 🔁 **Flush+Reload and Flip Feng Shui across VMs**, by step 3. Both need a physical page shared between tenants. With KSM off there is none.
- 🧱 **Last-level cache Prime+Probe**, by step 5 for domains that share an L3, and completely by step 0's placement for domains that do not. A sender can only evict lines in its own ways, so it can no longer push the receiver's lines out. Leaving the hardware ways to the host also keeps tenants away from the cache that DDIO, and so NetCAT, reaches.
- 🔋 **The free receivers**, by step 6. Guests have no performance counters and no energy readings, so PLATYPUS-style power channels and exact miss counts are gone, and a receiver is left with timing loops, which are slower and noisier.
- ⚖️ **CPU-time and disk contention between domains**, by step 7. With fixed quotas and separate disks, one tenant's load no longer changes another's speed, which was the basis of the CPU and "acoustic modem" storage channels in OpenAI's report.

Together these remove every channel the [previous post's table]({% post_url 2026-10-24-when-sandboxed-agents-talk-through-the-cpu-cache %}#-why-a-vm-even-firecracker-does-not-stop-this) marks as needing a shared core, a shared page, or shared cache ways. What remains is the package-wide and off-chip part of that table.

## 🧾 What is still open

After every step above, two tenants on one host still share:

- 🚌 **Memory controllers, the bus and DRAM banks.** MBA lowers the bandwidth; nothing in mainline Linux colours DRAM banks.
- 🌡️ **Frequency, power and temperature.** These are package-wide. [Hertzbleed]({% post_url 2026-10-24-when-sandboxed-agents-talk-through-the-cpu-cache %}#-seventeen-years-of-cross-tenant-channels) needs no shared cache at all. Pinning the frequency (turning off turbo and setting a fixed governor) narrows it, at a real performance cost.
- 🕸️ **The on-die interconnect and coherence directory**, unless the tenants are in different L3 domains, and even then the interconnect may be shared.
- 🎮 **The GPU**, if they share one, MIG or not.
- 🗄️ **Every service both can reach**: storage, logging, metrics, the model-serving cluster.

Each of these is slower and noisier than an L1 or LLC channel, and each still works for a patient sender with error correction. That is why the steps above are a way of *lowering the bandwidth* between agents of the same trust level, and why agents of different trust levels belong on different hosts.

## ✅ The runbook on one page

1. Map siblings, L3 domains and NUMA nodes; write the placement table.
2. SMT off (`nosmt`), or core scheduling with one cookie per VM.
3. One exclusive cpuset partition per domain; host work and interrupts on their own cores; pin vCPUs.
4. KSM off (`echo 2`), persisted; `mem-merge=off` for QEMU.
5. `mitigations=auto,nosmt`, current microcode, `spectre_v2_user=on`, `kvm-intel.vmentry_l1d_flush=always` where it applies.
6. Domains that share an L3: resctrl groups with non-overlapping masks, hardware ways left to the host, MBA caps, set up at boot.
7. No vPMU or energy counters for guests; `perf_event_paranoid` at 2 or higher.
8. Hard `cpu.max` and `io.max`; per-tenant disks and service instances.
9. Audit nightly; re-run Mastik and CJAG after every kernel, microcode or hardware change; watch per-group cache and memory traffic for periodic signals.
10. For agents that must never talk: none of the above. Separate hosts.

## 📚 Sources

Point-in-time (checked October 2026).

- Previous posts: [When sandboxed agents talk through the CPU cache]({% post_url 2026-10-24-when-sandboxed-agents-talk-through-the-cpu-cache %}) · [Sandboxing untrusted AI agents on Linux]({% post_url 2026-10-21-sandboxing-untrusted-ai-agents-on-linux %})
- Kernel: [cgroup v2 and cpuset partitions](https://docs.kernel.org/admin-guide/cgroup-v2.html) · [resctrl](https://docs.kernel.org/filesystems/resctrl.html) · [core scheduling](https://docs.kernel.org/admin-guide/hw-vuln/core-scheduling.html) · [attack vector controls](https://docs.kernel.org/admin-guide/hw-vuln/attack_vector_controls.html) · [L1TF](https://docs.kernel.org/admin-guide/hw-vuln/l1tf.html) · [L1D flushing](https://docs.kernel.org/admin-guide/hw-vuln/l1d_flush.html) · [KSM](https://docs.kernel.org/admin-guide/mm/ksm.html) · [kernel parameters](https://docs.kernel.org/admin-guide/kernel-parameters.html) · [powercap](https://docs.kernel.org/power/powercap/powercap.html)
- Tools: [coresched(1)](https://man7.org/linux/man-pages/man1/coresched.1.html) · [hwloc](https://www.open-mpi.org/projects/hwloc/) · [systemd resource control](https://www.freedesktop.org/software/systemd/man/latest/systemd.resource-control.html) · [Firecracker jailer](https://github.com/firecracker-microvm/firecracker/blob/main/docs/jailer.md) · [Firecracker production host setup](https://github.com/firecracker-microvm/firecracker/blob/main/docs/prod-host-setup.md) · [Kubernetes CPU management policies](https://kubernetes.io/docs/tasks/administer-cluster/cpu-management-policies/)
- Testing: [Mastik](https://github.com/0xADE1A1DE/Mastik) · [CJAG](https://github.com/IAIK/CJAG) · [Hello from the Other Side (NDSS 2017)](https://www.ndss-symposium.org/ndss2017/ndss-2017-programme/hello-other-side-ssh-over-robust-cache-covert-channels-cloud/)
- Attacks referred to: [PLATYPUS](https://platypusattack.com/) and [CVE-2020-8694](https://nvd.nist.gov/vuln/detail/CVE-2020-8694) · [Fantastic Timers (2017)](https://gruss.cc/files/fantastictimers.pdf) · [NetCAT](https://www.vusec.net/projects/netcat/) · [TLBleed](https://vusec.net/projects/tlbleed)
