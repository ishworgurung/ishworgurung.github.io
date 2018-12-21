# TCP Packets Debugging on the wire

One of the really handy tool I use to diagnose/measure network path and latencies is `tcptraceroute`. 
The benefit of using it is that unlike `traceroute` which uses `UDP` packets by default, `tcptraceroute` only
focuses on `TCP` layer so it naturally uses `TCP`. With only single flag set `SYN`, if a packet (with a particular IP ID)
sent through `tcptraceroute` gets a reply for that packet which has `SYN/ACK` flag set from the destination host, then it deems
the port on the destination host to be open; The technique *was probably* first pioneered by Fyodor in his `nmap` half-open 
TCP scan technique. From nmap project's documentation:
    
    -sS (TCP SYN scan)
        SYN scan is the default and most popular scan option for good reasons. It can be performed quickly, scanning 
        thousands of ports per second on a fast network not hampered by restrictive firewalls. It is also relatively 
        unobtrusive and stealthy since it never completes TCP connections. SYN scan works against any compliant TCP 
        stack rather than depending on idiosyncrasies of specific platforms as Nmap's FIN/NULL/Xmas, Maimon and idle 
        scans do. It also allows clear, reliable differentiation between the open, closed, and filtered states.
        
        This technique is often referred to as half-open scanning, because you don't open a full TCP connection. 
        You send a SYN packet, as if you are going to open a real connection and then wait for a response. A SYN/ACK
        indicates the port is listening (open), while a RST (reset) is indicative of a non-listener. If no response
        is received after several retransmissions, the port is marked as filtered. The port is also marked filtered
        if an ICMP unreachable error (type 3, code 0, 1, 2, 3, 9, 10, or 13) is received. The port is also considered
        open if a SYN packet (without the ACK flag) is received in response. This can be due to an extremely rare TCP
        feature known as a simultaneous open or split handshake connection (see https://nmap.org/misc/split-handshake.pdf). 

## A simplified one-way conversation packet dump

With `tcptraceroute`, only TCP packets with `SYN` flag set are sent outbound to the target destination from the source. Below is
a network conversation taking place - values removed for clarity. I am tracing the network path to the destination host `10.10.10.1`
on port `80` from the source host `172.16.255.28`.
 
    IP (.. ttl 1, id 34560 .. proto TCP (6) ..)
    172.16.255.28.48535 > 10.10.10.1.80: Flags [S], .. , seq 1708231650 ..
    
    ..
    
    IP (.. ttl 2, id 23532 .. proto TCP (6) ..)
    172.16.255.28.48535 > 10.10.10.1.80: Flags [S], .. , seq 1708231650 ..

    ..
    
    IP (.. ttl 3, id 33807 .. proto TCP (6) ..)
    172.16.255.28.48535 > 10.10.10.1.80: Flags [S], .. , seq 1708231650 ..

As `tcptraceroute` keep sending `TCP` packet with `SYN` flag set to the destination host with incrementing TTL values, it records
all the in-between routers that reply with `ICMP time exceeded in-transit` packet. Those set of routers IP addresses are put into
a internal map of `tcptraceroute`'s already-seen list *until* the packets finally reach (as they have incrementing TTL values) the
destination host on the specified port; at which point the half-open `TCP` connection are teared down using `RST` packets. The
replies from the in-between hops look something like this (values removed for clarity):
    
    IP (.. ttl 64, id 37925 .. proto ICMP (1) ..)
        172.16.255.1 > 172.16.255.28: ICMP time exceeded in-transit, length 48

    ..
    
    IP (.. ttl 63, id 59227 .. proto ICMP (1) ..)
        172.17.100.1 > 172.16.255.28: ICMP time exceeded in-transit, length 48

The final `TCP` connection teardown is then initiated (flag `S` and `R` mean `SYN` and `RST` respectively):
        
    IP (.. ttl 62, .. proto TCP (6) ..)
        10.10.10.1.80 > 172.16.255.28.44169: Flags [S.], .. seq 275990843, ack 1786429734 ..
    
    IP (.. ttl 64, .. proto TCP (6) .. )
        172.16.255.28.44169 > 10.10.10.1.80: Flags [R], .. seq 1786429734 ..   	
    	

## Hmm..
But you might be asking why on earth is `tcptraceroute` useful compared to the traditional `traceroute`? Because, `traceroute`
even supports tracing using `UDP` and `ICMP` on top of `TCP`. The primary reasons are:
  * By default `traceroute` uses `UDP` packets which are nearly always filtered by routers that sit in-between source
    and destination hosts.
  * Using `TCP` tracing is un-intuitive as it is hard to figure out whether the destination port is in `open` or `filtered` 
    state (although, I love the fact that its `TCP` scans are more faster yielding than `tcptraceroute`)
  * Using `ICMP` tracing, a lot of routers filter `ICMP` echo packets leading to unreliable measurements.    

## TL;DR
Traditional `traceroute` today is unreliable and un-intuitive. When debugging `TCP` layer issues, to overcome and reduce 
the noises, one should prefer to use a tool designed for `TCP` as it reduces the noise introduced by other factors such as 
unreliable network and/or network policies that filter `ICMP` echo packets etc.

One important bit - If you run a gateway gear, *do not forget to disable IP ID randomisation on the WAN interface(s)* 
or `tcptraceroute` never sees the packet it sent (consequently all your packets will have been sent to `/dev/null`)!

## Usage
Using `tcptraceroute` is the simplest command one can imagine executing on Linux:

    isg@kingkong:~$ sudo tcptraceroute 10.10.10.1 80
    Selected device eth0, address 172.16.255.28, port 44169 for outgoing packets
    Tracing the path to 10.10.10.1 on TCP port 80 (http), 30 hops max
     1  172.16.255.105  0.739 ms  0.501 ms  0.487 ms
     2  172.17.100.1  1.199 ms  3.220 ms  1.228 ms
     3  10.10.10.1 [open]  5.125 ms  3.501 ms  3.007 ms
     ^  ^           ^       ^RTT1    ^RTT2     ^RTT3
     ^  ^           ^
     ^  ^           ^Target host TCP port state
     ^  ^
     ^  ^IP address found during the hops
     ^
     ^Hop count
     
     RTT = Round-Trip Time of a packet
   
You can also debug the packets as seen by `tcptraceroute` using the `-d` switch.
   
## Other handy tools
There are bazillion other tools in the Web and Network ops realm to cover in this post. 
There are many GUI based ones as well; I prefer cmdline so here are some of the handy tools to use in cmdline:
  
  * nc (telnet is really really shit. don't use it)
  * nmap (with Nmap Scripting Engine)
  * openssl/gnutls
  * hping (generate packets that can flyyyyyyyyyy..)   
  * tcpdump/tshark/wireshark
  * vegeta (http load testing for the win)
  * sslyze/cipherscan
  * mtr
  * ping/ping6
  
If you know others or anything, please feel to ping me via email. More importantly, I also love to see why people do not
like to use `tcptraceroute` :)