# XDP/eBPF IP-layer firewall in Rust!

One of the option available today to do sub-millisecond packet filtering at scale is to harness the facilities afforded
by XDP, eBPF, Linux kernel and support provided by various NIC manufacturers.

The two (XDP and eBPF) have grown quite rapidly in the 5.x release of the Linux kernel and there is absolutely no reason
you would not want to use it for your low-latency, high-performance use case.

In this post, I will be demonstrating a sample XDP code that performs IP-layer firewall function traditionally done by
Netfilter/IPtables (thanks for all the fish Rusty Russell!) but ran as a generic XDP program by the eBPF VM in the
kernel. The walk-through was thoroughly tested on Ubuntu 20.10 with LLVM version 11.0.0 on QEMU/virtio. LLVM is required
today because it can produce eBPF targets.

According to XDP developers, on a benchmark they conducted, XDP far out-performed traditional kernel network stack on
Linux on all fronts - _tx_, _rx_ and _forward_ (in the order of 12-25x!) when used with a NIC that that supports XDP
natively such as the ones from Intel/Mellanox/Netronome etc.

## Dependencies Installation and Rust setup

Install dependencies:
```
$ sudo apt-get install          \
    build-essential             \    
    libelf-dev                  \
    ca-certificates             \
    ca-certificates-java        \
    zlib1g-dev                  \
    llvm-11-dev                 \
    libclang-11-dev             \
    linux-headers-$(uname -r)
```

Install Rust (single user) using `rustup`
```
$ curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
$ . ~/.bashrc # or logout then login.
$ rustup install nightly
$ rustup default nightly
$ rustc --version
 
```

Install Rust (system-wide) using `rustup`
```
$ sudo -i
$ curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs |       \
    env RUSTUP_HOME=/opt/rust/rustup CARGO_HOME=/opt/rust/cargo     \
    sh -s -- --default-toolchain stable --profile default --no-modify-path -y
$ tee -a /root/.bashrc <<HD
# setup Rust environment
export RUSTUP_HOME=/opt/rust/rustup
export PATH=${PATH}:/opt/rust/cargo/bin
HD
$ . /root/.bashrc # or logout then login.
$ rustup install nightly
$ rustup default nightly
$ rustc --version
```

Install `carfgo-bpf`:
```
$ cargo install cargo-bpf
```

## Walk-through

Create the eBPF project:
```
$ cargo bpf new xdp-ebpf-fw
```

Add a new eBPF program called `fw`:
```
$ cd xdp-ebpf-fw
$ cargo bpf add fw
```

Source for `xdp-ebpf-fw/Cargo.toml`:
```toml
[package]
name = "xdp-ebpf-fw"
version = "0.1.0"
edition = '2018'

[dependencies]
cty = "0.2"
redbpf-macros = "1.3"
redbpf-probes = "1.3"

[build-dependencies]
cargo-bpf = { version = "1.3", default-features = false }

[features]
default = []
probes = []

[lib]
path = "src/lib.rs"

[[bin]]
name = "fw"
path = "src/fw/main.rs"
required-features = ["probes"]
```

Source for `fw/main.rs`:

```rust
#![no_std]
#![no_main]

use core::fmt::Error;
use cty::*;
use redbpf_probes::xdp::prelude::*;

program!(0xFFFFFFFE, "GPL");

const TCP_XDP_DROP: XdpAction = XdpAction::Drop;
const UDP_XDP_DROP: XdpAction = XdpAction::Drop;
const XDP_PASS: XdpAction = XdpAction::Pass;

// XDP/eBPF based IP-layer firewall to drop all UDP packets.
// And, also drop all TCP packets destined to port 80.
#[xdp]
pub fn xdp_ip_firewall(ctx: XdpContext) -> XdpResult {
    if let Ok(ip_protocol) = get_ip_protocol(&ctx) {
        match ip_protocol as u32 {
            IPPROTO_UDP => return Ok(UDP_XDP_DROP), // drop it on the floor
            IPPROTO_TCP => {
                if let Ok(transport) = ctx.transport() {
                    if transport.dest() == 80 {
                        return Ok(TCP_XDP_DROP);  // drop it on the floor
                    }
                }
            }
            _ => return Ok(XDP_PASS), // pass it up the protocol stack
        }
    }
    return Ok(XDP_PASS); // pass it up the protocol stack
}

fn get_ip_protocol(ctx: &XdpContext) -> Result<u32, Error> {
    if let Ok(ip) = ctx.ip() {
        // We need to make raw pointer into a u32 so `unsafe` is required.
        unsafe {
            return Ok((*ip).protocol as u32);
        }
    }
    // Anything above `255` is reserved.
    return Ok(0x10000);
}
```

Build eBPF program:
```
$ cargo bpf build 
```

## Network queues on QEMU/virtio for XDP

On QEMU, we need to add 2*N* queues (where *N* is the number of vCPUs). The following `<driver>` section is required 
inside `<interface>` (use `virsh edit [vmname]`) is required (for 4 vCPUs, allocate 8 queues) as of QEMU version 4.2.1.
```
<interface ...>
[ ... ]
<driver name='vhost' txmode='iothread' ioeventfd='on' event_idx='off' queues='8' rx_queue_size='256' tx_queue_size='256'>
    <host csum='off' gso='off' tso4='off' tso6='off' ecn='off' ufo='off' mrg_rxbuf='off'/>
    <guest csum='off' tso4='off' tso6='off' ecn='off' ufo='off'/>
</driver>
[ ... ]
</interface>
```

## Load the compiled eBPF program!

Load the compiled eBPF program:
```
$ cd xdp-ebpf-fw
$ cargo bpf load -i eth0 target/bpf/programs/fw/fw.elf
```

> Profit!

:boom:

## Interesting resources

- [Rust redbpf crate doc](https://lib.rs/crates/redbpf)
- [redbpf intro](https://ingraind.org/api/cargo_bpf/)
- [Four year-old talk by Linux netdev guru David S. Miller on over-arching principles of XDP](https://www.youtube.com/watch?v=NlMQ0i09HMU)
- [XDP sockets](https://www.youtube.com/watch?v=p61PlC9y62k)
- [cilium XDP/eBPF](https://docs.cilium.io/en/latest/bpf/)
- [Awesome eBPF - keep this under the pillow](https://github.com/zoidbergwill/awesome-ebpf)
- [xdp-newbies mailing list](mailto:majordomo@vger.kernel.org?subject=subscribe xdp-newbies&body=subscribe xdp-newbies)
- [Netronome smart NIC XDP](https://www.youtube.com/watch?v=kFC8Bfk3FuI)
 
