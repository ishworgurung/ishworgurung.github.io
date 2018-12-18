## OpenBSD doas (or how I use sudo)

*Note: I wrote this post in July 2015 on the System Administrator Appreciation Day. I got a lot of web search hits on this page at the 
time so I am resurrecting it from my archive in the hope that it might help others*

There is a new `sudo` replacement in town and it's called `doas` which I use on OpenBSD 5.8 (snapshot). Ted Unangst(tedu) developed
it as a replacement to sudo(without all bells and whistles) to support the use case for a simple, small sudo-like replacement 
for OpenBSD. Long live sudo, no more sudo :)

By the way *happy sysadmin day to all the awesome system administrators who fight fires every day*.

Starting OpenBSD 5.8, `doas` comes pre-installed as part of base set. To use it is super simple; 
Create a configuration file `/etc/doas.conf` with the following configuration (depending on your needs):

### Super relaxed permission 

    permit nopass keepenv { ENV PS1 SSH_AUTH_SOCK } :wheel
    
Permit users in the `wheel` group to execute commands as `root` user (defaults to `root` user if not specified).
Allow running everything *without* requiring password and preserve the environment variables ENV, PS1 and SSH_AUTH_SOCK
when the elevation occurs.

### Do prompt the user for a valid password (`nopass` is not present)
    
    permit keepenv {ENV PS1 SSH_AUTH_SOCK} :wheel
    
### Allow the user bob to run /bin/sh as fred 

    permit bob as fred cmd /bin/sh
    
### Disallow users in wheel group to do anything:
    
    deny :wheel

### Note

The rules in `doas.conf` are read top-down. So, if you have a `deny :wheel` followed by `permit nopass :wheel` on the next line, 
then the `permit` rule will take effective precedence.