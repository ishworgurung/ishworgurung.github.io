# Mini-primer on tcpdump

You are here and that's great! Let's learn to dump 'em packets ;)

Here are some small `tcpdump` tricks that I thought could be helpful to others as well. 
It should work on MacOS, Linux, and any number of *BSDs. The `$` denotes the shell prompt.
The last time I checked Windows (Linux subsystem), it did not support `tcpdump`. Call
your Microsoft rep to get it on Linux subsystem! :)

## General syntax

To keep simple things simple, i'll begin with the format of `tcpdump`

    $ tcpdump [options] [expression]

Options are things like e.g. `-i any -nn -A -v`.
Expressions are things like e.g. `dst port 9999` and should be single quoted e.g. `'host www.example.com'`.

### A word about un-specified interface names

If the interface option is left unspecified (`-i`), then based on the implementation, 
`tcpdump` will choose the default interface available. On Linux and FreeBSD this is usually 
the first available network interface such as `eth0`, `re0`. On macOS, this is a pseudo 
interface `PKTAP` which captures on all available interfaces.

### Simple packet dumping

To trace packets on network interface `eth0` and **not** perform any DNS name resolution `-n` and give super brief info of the packet traces `-q`

    $ tcpdump -i eth0 -nq

I recommend using the `-n` option for packet tracing because the packet dumps are much cleaner
as there would be no name resolution and thus no DNS traffic to pollute the capture.

### Packet dumping with simple filter expressions

To filter on host www.example.com on **all** network interface.

    $ tcpdump -n 'host www.example.com'

The name resolution for `www.example.com` happens once when the `tcpdump` starts. If your
DNS resource record has a short TTL and the answer value changes often whilst debugging,
its important to keep this in mind.

To specify expression to filter on destination host `1.2.3.4` matching all protocols.

    $ tcpdump -n 'dst host 1.2.3.4'

### Gotchas
    
One of the important thing to consider is positioning of options. 
On some `tcpdump` implementations, the network interface and the other options come 
**before** the expression. For e.g.,

    # FreeBSD
    $ tcpdump 'dst host 1.2.3.4' -i em0 -nq
    tcpdump: syntax error
    $ tcpdump -i em0 -nq 'dst host 1.2.3.4'
    tcpdump: verbose output suppressed, use -v or -vv for full protocol decode
    listening on em0, link-type EN10MB (Ethernet), capture size 65535 bytes
    
    #MacOS    
    $ tcpdump 'dst host 1.2.3.4' -i en0 -nq
    12:48:31.736991 IP 172.16.10.5 > 1.2.3.4: ICMP echo request, id 59336, seq 0, length 64
    [...]    


Some `tcpdump` implementations support listening on all interfaces via `-i any`. The default `tcpdump` implementations on macOS and Linux support this feature

    #FreeBSD    
    $ tcpdump -n -i any 'dst host 1.2.3.4'
    tcpdump: any: No such device exists
    (BIOCSETIF failed: Device not configured)
    
    #MacOS    
    $ tcpdump -i any -n 'dst host 1.2.3.4' -nq (macOS)
    tcpdump: data link type PKTAP
    tcpdump: verbose output suppressed, use -v or -vv for full protocol decode
    listening on any, link-type PKTAP (Apple DLT_PKTAP), capture size 262144 bytes    


### A little complex filter expressions (but not that complex :)
  
To filter on source port 9999, protocol `tcp` on network interface `eth0`

    $ tcpdump -n -i eth0 'tcp and src port 9999'

To filter on destination port 9999, protocol udp on netif `eth0`

    $ tcpdump -n -i eth0 'udp and dst port 9999'

To dump `tcp` traffic on port 8080 using `-A` which prints the packets' content in ASCII

    $ tcpdump -n -i eth0 -A 'tcp and dst port 8080'


### Save/Read packet captures

To write out `icmp` packet traces to a `pcap` formatted file (it can get quite large)

    $ tcpdump -w /tmp/icmp-trace.pcap -n -i eth0 icmp

To read in `pcap` packet traces (alternatively, `tshark` or `wireshark` is great too :)

    $ tcpdump -r /tmp/icmp-trace.pcap    

### The mighty-little BPF monster

The `tcpdump` expressions can be viewed as a BPF instructions using the `-d` option
  
    $ tcpdump -d 'dst host 8.8.4.4'
    (000) ldh      [12]
    (001) jeq      #0x800           jt 2	jf 4
    (002) ld       [30]
    (003) jeq      #0x8080404       jt 8	jf 9
    (004) jeq      #0x806           jt 6	jf 5
    (005) jeq      #0x8035          jt 6	jf 9
    (006) ld       [38]
    (007) jeq      #0x8080404       jt 8	jf 9
    (008) ret      #65535
    (009) ret      #0
  
Each line is a BPF instruction that can be executed within a BPF VM.

### More filter expressions :)

To trace all udp packets in a destination port range 50000-65535 (inclusive)

    $ tcpdump -n -i eth0 'udp and dst portrange 50000-65535'

To trace all udp packets not going to host `1.2.3.4` or `5.6.7.8` on network interface `eth0`

    $ tcpdump -n -i eth0 'udp and not dst host (1.2.3.4 or 5.6.7.8)'
  
To trace all IPv6 packets on network interface `eth0`

    $ tcpdump -n -i eth0 ip6
  
To trace all IPv4 packets on network interface `eth0` for network `17.0.0.0/8` (dst/src)

    $ tcpdump -n -i eth0 'net 17.0.0.0/8'

To print all `tcp` packets with just `SYN` flag set

    $ tcpdump -n -i eth0 'tcp[tcpflags] & tcp-syn == 2'

To print the first hundred `tcp` packets to destination port 80 on `eth0`

    $ tcpdump -n -i eth0 -c 100 'tcp and dst port 80'

Capture packets indefinitely and rotate every 10 seconds

    $ tcpdump -i eth0 -G 10 -w dump-%S.pcap 'dst port 80'

## Extracted and adapted from the `tcpdump` man page

The `tcpdump` man page is a gold mine. I have spent a long time reading it and every single time I find something new in it.
Following are some of the handy ones:

### TCP conversation

To print the start and end packets (the SYN and FIN packets) of each TCP conversation that involves a non-local host.

    $ tcpdump -n -i eth0 'tcp[tcpflags] & (tcp-syn|tcp-fin) != 0 and not src and dst net 127.0.0.1'

### Lets do some webops yo!

To print all IPv4 HTTP packets to and from port 80, i.e. print only packets  that  contain  data, not, for example, SYN and FIN packets and ACK-only packets.

    $ tcpdump -n -i eth0 'tcp port 80 and (((ip[2:2] - ((ip[0]&0xf)<<2)) - ((tcp[12]&0xf0)>>2)) != 0)'

### More goodies

To print IP packets longer than 576 bytes sent through gateway snup:

    $ tcpdump -n -i eth0 'gateway snup and ip[2:2] > 576'

### Let there be broad/multi-casts

To print IP broadcast or multi-cast packets that were not sent via  Ethernet broadcast or multicast:

    $ tcpdump -n -i eth0 'ether[0] & 1 = 0 and ip[16] >= 224'

### And let there be ICMP echo req/reply gods

To print all ICMP packets that are not an ICMP echo request/reply (e.g. not ping packets):

    $ tcpdump -n -i eth0 'icmp[icmptype] != icmp-echo and icmp[icmptype] != icmp-echoreply'