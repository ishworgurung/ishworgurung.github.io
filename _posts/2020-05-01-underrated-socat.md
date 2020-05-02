# Socat

Socat is one of the most underrated software in Linux. It is a tool to help in debugging and applying network 
interops in ways the original author of a software probably had not anticipated. The author of `socat` describes it as
_multipurpose relay_ software (socket cat). People lovingly synonymize it as _like `cat` but for sockets_. I first came 
across `socat` when I was working as a pentester back in the day (I have worn many hats in the past) whilst 
trying to work my way through protocol debugging.
  
TL;DR? Refer to the [commands](##socat the swiss-army knife) instead.

## The socat story

So, why would you need socat? Follow through on the fictionalised story below <sup>1</sup>.

Let's pretend that we want to have a TCP client sitting locally to be able to connect to a TCP server sitting
elsewhere on port 3450; i.e., a TCP network clients connect to a TCP socket on the server at port 3450. 
This is the trivial part and software libraries have evolved to abstract almost 99% of this game so engineers can have
a good sleep.

Now, here's the catch - say that *Bob the sysadmin* appeared on the deck of this ship and said that clients can only connect
to TCP sockets on the server on port 80 and 443 <sup>2</sup>

You can use many tools in Linux and *BSDs (and that's the beauty of it - each to their own) to achieve the precise outcome 
(HAProxy, Nginx, iptables DNATs, SSH port forwards, IPsec tunnels, sshuttle, Wireguard etc..) but in this instance I
would like to focus only on `socat`.

So, how could `socat` be of help here for a quick win? The TCP client will now connect to the server on port `80`. 
That is, the TCP endpoint to the client will look like `server.ip.address:80`.

On the server, Bob, the sysadmin will spin up `socat` and run a TCP relay from the listening TCP port `80` to the local
loopback address' TCP port `3450`. Thus, Bob, the sysadmin will run this on the server:
```bash
$ socat -v tcp-listen:80,reuseaddr,fork tcp-connect:127.0.0.1:3450
```

This will relay all TCP packets that connect to the server on port `80` to be sent to `127.0.0.1` on port `3450`. As
`socat` accepts a TCP client connection on port `80`, it will fork a new child process, set up a bi-directional socket
pairs on the child process and forward all incoming and outgoing TCP packets via these descriptors. The parent process will
continue to service new TCP connections.

Until a permanent solution is in place<sup>2</sup>, Bob can now proceed to block non-standard TCP port to ingress the
server.

## socat the swiss-army knife

An exhaustive list of `socat` capabilities is documented in the manual page for `socat(1)` and it is 
still the authoritative source. Below are some common ones one might need.

### Relay TCP to TCP
```bash
$ socat -v tcp-listen:80,reuseaddr,fork tcp-connect:172.16.2.10:8080
```

### Relay TCP to UDP
```bash
$ socat -v tcp-listen:80,reuseaddr,fork udp-connect:172.16.2.10:8080
```

### Relay UDP to UDP
```bash
$ socat -v udp-listen:80,reuseaddr,fork udp-connect:172.16.2.10:8080
```

### Relay UDP to TCP
```bash
$ socat -v udp-listen:80,reuseaddr,fork tcp-connect:172.16.2.10:8080
```

### Relay TCP to Unix Domain Sockets
```bash
$ socat -v tcp-listen:80,reuseaddr,fork unix-client:/var/run/uds.sock
```

### Relay Unix Domain Sockets to TCP
```bash
$ socat -v -v unix-listen:/var/run/uds.sock,reuseaddr,fork tcp-connect:172.16.2.10:80
```

### Relay UDP to Unix Domain Sockets
```bash
$ socat -v udp-listen:80,reuseaddr,fork unix-client:/var/run/uds.sock
```

### Relay Unix Domain Sockets to UDP
```bash
$ socat -v -v unix-listen:/var/run/uds.sock,reuseaddr,fork udp-connect:172.16.2.10:80
```

### Relay SCTP to Unix Domain Sockets
```bash
$ socat -v sctp-listen:80,reuseaddr,fork unix-client:/var/run/uds.sock
```

### Relay Unix Domain Sockets to SCTP
```bash
$ socat -v -v unix-listen:/var/run/uds.sock,reuseaddr,fork sctp-connect:172.16.2.10:80
```

### Tunnel Unix Domain Socket packets inside TLS relay
Please avoid setting `verify=0` on production if you can.
```bash
$ socat -v                                          \
    unix-listen:/var/run/uds.sock,reuseaddr,fork    \
    openssl:server.domain.name:443,certificate=cert.pem,cafile=cert.pem,verify=1,key=key.pem,commonname=server.domain.name
```

### Relay TLS packets to Unix Domain Socket (aka virtual patching)
```bash
$ socat -v                                                                                             \
    openssl-listen:443,reuseaddr,pf=ip4,fork,key=key.pem,cafile=cert.pem,cert=cert.pem,method=TLS1.2   \
    unix-client:/var/run/uds.sock
```

<sup>1</sup> Everything in this story is fictional and has been trivialised for the purpose of simplicity. I am a big
fan of KISS philosophy although I haven't had the time to listen to the band KISS at all :smile:.

<sup>2</sup> Let's pretend that there is a forcing function here.