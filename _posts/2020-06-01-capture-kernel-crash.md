
## Capturing Linux kernel panic message on QeMU

In this small post, I will cover the following:
- Capture Linux kernel panic message
- Using `softdog` module to set the watchdog to auto-reboot upon Kernel panic.

### Capture the panic

Log into your guest and update `/etc/default/grub` and add `console=tty0 console=ttyS0,9600n8` to `GRUB_CMDLINE_LINUX`; Then run `update-grub`.

To capture a kernel panic message, run the virtual machine like so:
```
$ qemu-system-x86_64 -smp 2,sockets=2,cores=1,threads=1 -m 4096 -nographic -serial mon:stdio ubuntu18.04-1.qcow2
```

You will be greeted with the usual boot messages.

Log in and trigger a kernel panic (either via sysrq or via the faulty kernel module).

Upon kernel panic, a full trace message will appear on your attached console.

```
[  247.009745] BUG: stack guard page was hit at 000000006c1ac1e1 (stack is 00000000487682b5..000000001262eb3a)
[  247.012648] kernel stack overflow (double-fault): 0000 [#1] SMP NOPTI
[  247.012648] Modules linked in: helloworld(POE+) binfmt_misc ppdev kvm_amd kvm irqbypass input_leds serio_raw parport_pc parport sch_fq_codel softy
[  247.012648] CPU: 1 PID: 2102 Comm: insmod Tainted: P           OE    4.15.0-64-generic #73-Ubuntu
[  247.012648] Hardware name: QEMU Standard PC (i440FX + PIIX, 1996), BIOS 1.12.0-1 04/01/2014
[  247.012648] RIP: 0010:_ZN4core3num23_$LT$impl$u20$usize$GT$11checked_mul17h07ae83026124b5eaE+0x10/0x70 [helloworld]
[  247.012648] RSP: 0018:ffffa84b4169ffd0 EFLAGS: 00000282
[  247.012648] RAX: 00000000000000fe RBX: 0000000000000000 RCX: 0000000000000000
[  247.012648] RDX: 0000000000000000 RSI: 0000000000000003 RDI: 0000000000000001
[  247.012648] RBP: ffffa84b416a0020 R08: ffffffffc0690d60 R09: 0000000000000003
[  247.012648] R10: 0000000000000000 R11: 0000000000000000 R12: ffffffffc059edf0
[  247.070679] R13: ffff9c5d78655a00 R14: 0000000000000001 R15: ffff9c5d51aeb240
[  247.070679] FS:  00007f690a2ff540(0000) GS:ffff9c5d7fd00000(0000) knlGS:0000000000000000
[  247.070679] CS:  0010 DS: 0000 ES: 0000 CR0: 0000000080050033
[  247.070679] CR2: ffffa84b4169ffc8 CR3: 0000000137068000 CR4: 00000000000006e0
[  247.070679] Call Trace:
[  247.070679]  ? _ZN4core3num23_$LT$impl$u20$usize$GT$14saturating_mul17hc7be383430829098E+0x15/0x50 [helloworld]
[  247.070679]  ? _ZN4core5slice18from_raw_parts_mut17hc0afd704cde83aefE+0x62/0xd0 [helloworld]
[  247.070679]  ? _ZN99_$LT$core..ops..range..Range$LT$usize$GT$$u20$as$u20$core..slice..SliceIndex$LT$$u5b$T$u5d$$GT$$GT$17get_unchecked_mut17h8+0x]
[  247.070679]  ? _ZN99_$LT$core..ops..range..Range$LT$usize$GT$$u20$as$u20$core..slice..SliceIndex$LT$$u5b$T$u5d$$GT$$GT$9index_mut17h59d846e1fc+0x]
[  247.070679]  ? _ZN4core3cmp6min_by17h6a1a357c03d17732E+0x3d/0x90 [helloworld]
[  247.070679]  ? _ZN4core5slice77_$LT$impl$u20$core..ops..index..IndexMut$LT$I$GT$$u20$for$u20$$u5b$T$u5d$$GT$9index_mut17h6d899aa41763834eE+0x33/0]
[  247.070679]  ? _ZN79_$LT$linux_kernel_module..printk..LogLineWriter$u20$as$u20$core..fmt..Write$GT$9write_str17hb6b9f63c86335f4fE+0x127/0x250 [he]
[  247.070679]  ? _ZN4core3fmt9Formatter12pad_integral17hea95901f585e791cE+0x260/0x8b0 [helloworld]
[  247.070679]  ? _ZN4core3num23_$LT$impl$u20$usize$GT$14saturating_mul17hc7be383430829098E+0x15/0x50 [helloworld]
[  247.070679]  ? _ZN4core5slice14from_raw_parts17hc54a1a170e771755E+0x8f/0xd0 [helloworld]
[  247.070679]  ? _ZN4core3fmt3num3imp7fmt_u6417hb10d5615ab39d4d8E+0x5e6/0x720 [helloworld]
[  247.070679]  ? _ZN4core10intrinsics19copy_nonoverlapping17h66731a07c4e66efbE+0xc2/0xd0 [helloworld]
[  247.070679]  ? _ZN4core3fmt3num3imp51_$LT$impl$u20$core..fmt..Display$u20$for$u20$u8$GT$3fmt17h8a7427ec99f7ed22E+0x80/0xa0 [helloworld]
[  247.070679]  ? _ZN4core3fmt3num49_$LT$impl$u20$core..fmt..Debug$u20$for$u20$u8$GT$3fmt17h9010dd741ac356b3E+0x64/0xa0 [helloworld]
[  247.070679]  ? _ZN42_$LT$$RF$T$u20$as$u20$core..fmt..Debug$GT$3fmt17hce45b733e98582cdE+0x18/0x30 [helloworld]
[  247.070679]  ? _ZN4core3fmt8builders10DebugInner9is_pretty17h61db7b5335d258d0E+0x14/0x30 [helloworld]
[  247.070679]  ? _ZN4core3fmt8builders10DebugInner5entry28_$u7b$$u7b$closure$u7d$$u7d$17h17d35c1353ea2e80E+0x23c/0x250 [helloworld]
[  247.070679]  ? _ZN79_$LT$linux_kernel_module..printk..LogLineWriter$u20$as$u20$core..fmt..Write$GT$9write_str17hb6b9f63c86335f4fE+0x1be/0x250 [he]
[  247.070679]  ? _ZN4core6result19Result$LT$T$C$E$GT$8and_then17hc710b76977389ea0E+0x4e/0x70 [helloworld]
[  247.070679]  ? _ZN4core3fmt8builders10DebugInner5entry17h92ae2868f0df466bE+0x43/0x70 [helloworld]
[  247.070679]  ? _ZN4core3fmt8builders9DebugList5entry17he09db0b952ed03ccE+0x23/0x30 [helloworld]
[  247.070679]  ? _ZN4core3fmt8builders9DebugList7entries17h8eb3996229be728fE+0x88/0xa0 [helloworld]
[  247.070679]  ? _ZN48_$LT$$u5b$T$u5d$$u20$as$u20$core..fmt..Debug$GT$3fmt17h9c57c882f7ac9744E+0x51/0x70 [helloworld]
[  247.070679]  ? _ZN50_$LT$$RF$mut$u20$T$u20$as$u20$core..fmt..Debug$GT$3fmt17hb8d4e0e57dc57deaE+0x2a/0x40 [helloworld]
[  247.070679]  ? _ZN4core3fmt5write17hb916ed05c0beea6fE+0x285/0x640 [helloworld]
[  247.070679]  ? _ZN4core3fmt3num3imp52_$LT$impl$u20$core..fmt..Display$u20$for$u20$u64$GT$3fmt17h67ec8b7f52fe9da3E+0xa0/0xa0 [helloworld]
[  247.070679]  ? _ZN11hello_world4foos17he560009d948fdbe9E+0x189/0x1e0 [helloworld]
[  247.070679]  ? _ZN4core3fmt3num3imp52_$LT$impl$u20$core..fmt..Display$u20$for$u20$u64$GT$3fmt17h67ec8b7f52fe9da3E+0xa0/0xa0 [helloworld]
[  247.070679]  ? _ZN4core3fmt10ArgumentV13new17hf3e64bcfe2a81583E+0x50/0x50 [helloworld]
[  247.070679]  ? _ZN4core3fmt3num3imp52_$LT$impl$u20$core..fmt..Display$u20$for$u20$u64$GT$3fmt17h67ec8b7f52fe9da3E+0xa0/0xa0 [helloworld]
[  247.070679]  ? _ZN4core3fmt10ArgumentV13new17hf3e64bcfe2a81583E+0x50/0x50 [helloworld]
[  247.070679]  ? _ZN4core3fmt3num3imp52_$LT$impl$u20$core..fmt..Display$u20$for$u20$u64$GT$3fmt17h67ec8b7f52fe9da3E+0xa0/0xa0 [helloworld]
[  247.070679]  ? _ZN83_$LT$hello_world..HelloWorldModule$u20$as$u20$linux_kernel_module..KernelModule$GT$4init17hcdf4c87881ba8bf7E+0x55/0xb0 [hello]
[  247.092990]  ? __slab_free+0x14d/0x2c0
[  247.093536]  ? __switch_to_asm+0x35/0x70
[  247.093536]  ? __slab_free+0x14d/0x2c0
[  247.093536]  ? __switch_to_asm+0x35/0x70
[  247.093536]  ? __switch_to_asm+0x41/0x70
[  247.093536]  ? init_module+0x14/0xd0 [helloworld]
[  247.093536]  ? __slab_free+0x14d/0x2c0
[  247.093536]  ? __vunmap+0x8e/0xc0
[  247.093536]  ? kfree+0x165/0x180
[  247.093536]  ? do_one_initcall+0x52/0x19f
[  247.093536]  ? __vunmap+0x8e/0xc0
[  247.093536]  ? _cond_resched+0x19/0x40
[  247.093536]  ? kmem_cache_alloc_trace+0x14e/0x1b0
[  247.093536]  ? do_init_module+0x27/0x209
[  247.093536]  ? do_init_module+0x5f/0x209
[  247.093536]  ? load_module+0x1939/0x1f30
[  247.093536]  ? ima_post_read_file+0x96/0xa0
[  247.093536]  ? SYSC_finit_module+0xfc/0x120
[  247.093536]  ? SYSC_finit_module+0xfc/0x120
[  247.093536]  ? SyS_finit_module+0xe/0x10
[  247.093536]  ? do_syscall_64+0x73/0x130
[  247.093536]  ? entry_SYSCALL_64_after_hwframe+0x3d/0xa2
[  247.093536] Code: eb 08 48 c7 45 d0 00 00 00 00 48 8b 45 d0 48 8b 55 d8 48 83 c4 50 5d c3 00 00 00 55 48 89 e5 48 83 ec 50 48 89 7d e0 48 89 75 e 
[  247.097494] RIP: _ZN4core3num23_$LT$impl$u20$usize$GT$11checked_mul17h07ae83026124b5eaE+0x10/0x70 [helloworld] RSP: ffffa84b4169ffd0
[  247.097494] ---[ end trace b512caf3cbcd6f50 ]---
[  247.097494] Kernel panic - not syncing: corrupted stack end detected inside scheduler
[  247.097494] 
[  247.097494] Kernel Offset: 0x1b400000 from 0xffffffff81000000 (relocation range: 0xffffffff80000000-0xffffffffbfffffff)
[  247.097494] Rebooting in 60 seconds..
```

Just for your information, you can pipe the kernel panic message to `c++filt` to get the demangled symbols (the kernel module is written in Rust and it does not yet seem to support `[no_mangle]`).
```
$ cat panic | c++filt 
[  247.009745] BUG: stack guard page was hit at 000000006c1ac1e1 (stack is 00000000487682b5..000000001262eb3a)
[  247.012648] kernel stack overflow (double-fault): 0000 [#1] SMP NOPTI
[  247.012648] Modules linked in: helloworld(POE+) binfmt_misc ppdev kvm_amd kvm irqbypass input_leds serio_raw parport_pc parport sch_fq_codel softy
[  247.012648] CPU: 1 PID: 2102 Comm: insmod Tainted: P           OE    4.15.0-64-generic #73-Ubuntu
[  247.012648] Hardware name: QEMU Standard PC (i440FX + PIIX, 1996), BIOS 1.12.0-1 04/01/2014
[  247.012648] RIP: 0010:core::num::<impl usize>::checked_mul::h07ae83026124b5ea+0x10/0x70 [helloworld]
[  247.012648] RSP: 0018:ffffa84b4169ffd0 EFLAGS: 00000282
[  247.012648] RAX: 00000000000000fe RBX: 0000000000000000 RCX: 0000000000000000
[  247.012648] RDX: 0000000000000000 RSI: 0000000000000003 RDI: 0000000000000001
[  247.012648] RBP: ffffa84b416a0020 R08: ffffffffc0690d60 R09: 0000000000000003
[  247.012648] R10: 0000000000000000 R11: 0000000000000000 R12: ffffffffc059edf0
[  247.070679] R13: ffff9c5d78655a00 R14: 0000000000000001 R15: ffff9c5d51aeb240
[  247.070679] FS:  00007f690a2ff540(0000) GS:ffff9c5d7fd00000(0000) knlGS:0000000000000000
[  247.070679] CS:  0010 DS: 0000 ES: 0000 CR0: 0000000080050033
[  247.070679] CR2: ffffa84b4169ffc8 CR3: 0000000137068000 CR4: 00000000000006e0
[  247.070679] Call Trace:
[  247.070679]  ? core::num::<impl usize>::saturating_mul::hc7be383430829098+0x15/0x50 [helloworld]
[  247.070679]  ? core::slice::from_raw_parts_mut::hc0afd704cde83aef+0x62/0xd0 [helloworld]
[  247.070679]  ? _ZN99_$LT$core..ops..range..Range$LT$usize$GT$$u20$as$u20$core..slice..SliceIndex$LT$$u5b$T$u5d$$GT$$GT$17get_unchecked_mut17h8+0x]
[  247.070679]  ? _ZN99_$LT$core..ops..range..Range$LT$usize$GT$$u20$as$u20$core..slice..SliceIndex$LT$$u5b$T$u5d$$GT$$GT$9index_mut17h59d846e1fc+0x]
[  247.070679]  ? core::cmp::min_by::h6a1a357c03d17732+0x3d/0x90 [helloworld]
[  247.070679]  ? core::slice::<impl core::ops::index::IndexMut<I> for [T]>::index_mut::h6d899aa41763834e+0x33/0]
[  247.070679]  ? <linux_kernel_module::printk::LogLineWriter as core::fmt::Write>::write_str::hb6b9f63c86335f4f+0x127/0x250 [he]
[  247.070679]  ? core::fmt::Formatter::pad_integral::hea95901f585e791c+0x260/0x8b0 [helloworld]
[  247.070679]  ? core::num::<impl usize>::saturating_mul::hc7be383430829098+0x15/0x50 [helloworld]
[  247.070679]  ? core::slice::from_raw_parts::hc54a1a170e771755+0x8f/0xd0 [helloworld]
[  247.070679]  ? core::fmt::num::imp::fmt_u64::hb10d5615ab39d4d8+0x5e6/0x720 [helloworld]
[  247.070679]  ? core::intrinsics::copy_nonoverlapping::h66731a07c4e66efb+0xc2/0xd0 [helloworld]
[  247.070679]  ? core::fmt::num::imp::<impl core::fmt::Display for u8>::fmt::h8a7427ec99f7ed22+0x80/0xa0 [helloworld]
[  247.070679]  ? core::fmt::num::<impl core::fmt::Debug for u8>::fmt::h9010dd741ac356b3+0x64/0xa0 [helloworld]
[  247.070679]  ? <&T as core::fmt::Debug>::fmt::hce45b733e98582cd+0x18/0x30 [helloworld]
[  247.070679]  ? core::fmt::builders::DebugInner::is_pretty::h61db7b5335d258d0+0x14/0x30 [helloworld]
[  247.070679]  ? core::fmt::builders::DebugInner::entry::{{closure}}::h17d35c1353ea2e80+0x23c/0x250 [helloworld]
[  247.070679]  ? <linux_kernel_module::printk::LogLineWriter as core::fmt::Write>::write_str::hb6b9f63c86335f4f+0x1be/0x250 [he]
[  247.070679]  ? core::result::Result<T,E>::and_then::hc710b76977389ea0+0x4e/0x70 [helloworld]
[  247.070679]  ? core::fmt::builders::DebugInner::entry::h92ae2868f0df466b+0x43/0x70 [helloworld]
[  247.070679]  ? core::fmt::builders::DebugList::entry::he09db0b952ed03cc+0x23/0x30 [helloworld]
[  247.070679]  ? core::fmt::builders::DebugList::entries::h8eb3996229be728f+0x88/0xa0 [helloworld]
[  247.070679]  ? <[T] as core::fmt::Debug>::fmt::h9c57c882f7ac9744+0x51/0x70 [helloworld]
[  247.070679]  ? <&mut T as core::fmt::Debug>::fmt::hb8d4e0e57dc57dea+0x2a/0x40 [helloworld]
[  247.070679]  ? core::fmt::write::hb916ed05c0beea6f+0x285/0x640 [helloworld]
[  247.070679]  ? core::fmt::num::imp::<impl core::fmt::Display for u64>::fmt::h67ec8b7f52fe9da3+0xa0/0xa0 [helloworld]
[  247.070679]  ? hello_world::foos::he560009d948fdbe9+0x189/0x1e0 [helloworld]
[  247.070679]  ? core::fmt::num::imp::<impl core::fmt::Display for u64>::fmt::h67ec8b7f52fe9da3+0xa0/0xa0 [helloworld]
[  247.070679]  ? core::fmt::ArgumentV1::new::hf3e64bcfe2a81583+0x50/0x50 [helloworld]
[  247.070679]  ? core::fmt::num::imp::<impl core::fmt::Display for u64>::fmt::h67ec8b7f52fe9da3+0xa0/0xa0 [helloworld]
[  247.070679]  ? core::fmt::ArgumentV1::new::hf3e64bcfe2a81583+0x50/0x50 [helloworld]
[  247.070679]  ? core::fmt::num::imp::<impl core::fmt::Display for u64>::fmt::h67ec8b7f52fe9da3+0xa0/0xa0 [helloworld]
[  247.070679]  ? <hello_world::HelloWorldModule as linux_kernel_module::KernelModule>::init::hcdf4c87881ba8bf7+0x55/0xb0 [hello]
[  247.092990]  ? __slab_free+0x14d/0x2c0
[  247.093536]  ? __switch_to_asm+0x35/0x70
[  247.093536]  ? __slab_free+0x14d/0x2c0
[  247.093536]  ? __switch_to_asm+0x35/0x70
[  247.093536]  ? __switch_to_asm+0x41/0x70
[  247.093536]  ? init_module+0x14/0xd0 [helloworld]
[  247.093536]  ? __slab_free+0x14d/0x2c0
[  247.093536]  ? __vunmap+0x8e/0xc0
[  247.093536]  ? kfree+0x165/0x180
[  247.093536]  ? do_one_initcall+0x52/0x19f
[  247.093536]  ? __vunmap+0x8e/0xc0
[  247.093536]  ? _cond_resched+0x19/0x40
[  247.093536]  ? kmem_cache_alloc_trace+0x14e/0x1b0
[  247.093536]  ? do_init_module+0x27/0x209
[  247.093536]  ? do_init_module+0x5f/0x209
[  247.093536]  ? load_module+0x1939/0x1f30
[  247.093536]  ? ima_post_read_file+0x96/0xa0
[  247.093536]  ? SYSC_finit_module+0xfc/0x120
[  247.093536]  ? SYSC_finit_module+0xfc/0x120
[  247.093536]  ? SyS_finit_module+0xe/0x10
[  247.093536]  ? do_syscall_64+0x73/0x130
[  247.093536]  ? entry_SYSCALL_64_after_hwframe+0x3d/0xa2
[  247.093536] Code: eb 08 48 c7 45 d0 00 00 00 00 48 8b 45 d0 48 8b 55 d8 48 83 c4 50 5d c3 00 00 00 55 48 89 e5 48 83 ec 50 48 89 7d e0 48 89 75 e 
[  247.097494] RIP: core::num::<impl usize>::checked_mul::h07ae83026124b5ea+0x10/0x70 [helloworld] RSP: ffffa84b4169ffd0
[  247.097494] ---[ end trace b512caf3cbcd6f50 ]---
[  247.097494] Kernel panic - not syncing: corrupted stack end detected inside scheduler
[  247.097494] 
[  247.097494] Kernel Offset: 0x1b400000 from 0xffffffff81000000 (relocation range: 0xffffffff80000000-0xffffffffbfffffff)
[  247.097494] Rebooting in 60 seconds..

```

I triggered the above Linux kernel panic while I was trying to understand how the Rust LKM worked; In this case, I allocated large kernel stack which was caught by the stack guard which caused an immediate Kernel panic.
If you are into Rust and Linux kernel, I definitely recommend checking out [linux-kernel-module-rust](https://github.com/fishinabarrel/linux-kernel-module-rust).

### Auto-reboot upon Linux kernel panic

If you often get kernel panic (while developing/debugging kernel module or what not) or want to ensure system uptime in the face of Kernel instabilities, you could consider enabling `softdog` in-tree linux kernel module.
This LKM runs a watchdog timer with a periodic heartbeat. Upon heartbeat failure, the timer associated with the heartbeat expires due to a kernel panic upon which, the system is rebooted. 
For this to work, a kernel parameter needs to be added to GRUB - `GRUB_CMDLINE_LINUX="panic=60"` in `/etc/default/grub` and then `update-grub` (for Ubuntu-like distro) needs to be run; Then the system needs to be rebooted.

Ubuntu has commented out the automatic loading of `softdog` kernel module, so it needs to be added back in. Remove `softdog` module from files that reside in `/lib/modprobe.d/*.conf` and then add it to auto-load in `/etc/modules-load.d`.
Then run the following:
```
$ sudo update-initramfs -u
$ sudo depmod -a
$ sudo systemctl reboot
```

Feel free to drop a comment if anything. As usual, until next time - Adios!
