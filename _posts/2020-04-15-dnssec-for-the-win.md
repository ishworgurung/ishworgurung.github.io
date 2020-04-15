## Fast Intro

DNSSEC uses digital signature to verify the authenticity and integrity of DNS records. In essence, it sets up
a non-spoofable chain of trust right from the root zone down to the authoritative nameserver and further to modern caching
resolvers (e.g., BIND, Unbound etc.). Of course, there's [more](https://youtu.be/_8M_vuFcdZU), 
[on it](https://www.cloudflare.com/learning/dns/dns-records/dnskey-ds-records/) and 
[some more](https://www.internetsociety.org/resources/deploy360/2011/dnssec-rfcs-3/).

### Why DNSSEC

There are many reasons to turn on DNSSEC, some of which some of them are outright detrimental to businesses 
(loss of revenue for instance).

It may surprise you to find a number of _household_ domains do not use DNSSEC.

In general these are some reasons to use DNSSEC:
- DNS Protocol Attacks
- BGP Hijacking Attack
- DNS Hijacking (Credential Theft)
- Domain Theft
- Cache Poisoning

It goes without saying that DNSSEC is not a panacea :pill:

### Turn the secure bits on

To have DNSSEC turned on for a domain, you need three parties working in tandem with each other :revolving_hearts:
1. The Domain Name Registrar (e.g., Namecheap, Godaddy, tucows etc.) of the domain
2. The Authoritative Name Server (e.g., BYO BIND/NSD/PDNS, Route53, Vultr, NS1 etc.) of the domain
3. The "abstracted" Root Name Servers (I say "abstracted" as it will appear almost invisible to us :boom:)

For illustrative purpose, I will use my domain **ishworgurung.com**.

My personal domain **ishworgurung.com** is registered using Namecheap and the authoritative name server is at Vultr.

So, to setup DNSSEC for my domain, I need to generate a fresh copy of *DS Records* (Delegation Signer) from Vultr. 
Of particular use are:
  - Key Tag / Key Type (A unique key per DS record used for lookups) [see here](https://tools.ietf.org/html/rfc3658#section-2.4.1) and [here](https://tools.ietf.org/html/rfc2535#section-4.1.6)
  - [Algorithm](https://en.wikipedia.org/wiki/Domain_Name_System_Security_Extensions#Algorithms) (crypto algorithm)
  - [Digest Type](https://en.wikipedia.org/wiki/Domain_Name_System_Security_Extensions#Algorithms) (hashing algorithm)
  - Digest (hexadecimal representation of the digest)

Vultr by default generates three DS records, copy them to Namecheap's DNSSEC console.

### Handy tools

Some handy tools the _internets_ has to offer :100: 

- https://dnsviz.net 
- https://dnssec-debugger.verisignlabs.com
- Dig from Bind
  - `dig +short ds ishworgurung.com`
  - `dig +short dnskey ishworgurung.com`
  - `dig +short nsec ishworgurung.com`

### Conclusion

Someone on the internet said:

> DNSSEC is a tool, not a religion. Please try to understand how the tool works before criticizing it.

And I agree. DNSSEC is a good thing - let's do more of it; not less.
  
I leave you with Dr. Casey Deccio's [Hello Summer Break](https://casey.byu.edu/media/hello_summer_break.mp3) :sound:.
Dr. Casey is the original author of DNSViz :beers: