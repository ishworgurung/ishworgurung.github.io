## Go self fork/exec in Linux/MacOS and possibly BSD

Go's [`os`](https://golang.org/pkg/os/) package exposes a convenient way to fork and exec.
Since, I found this trick handy, I thought I might share it. For people with UNIX beards, *tldr;* NIH.
What I am trying to achieve is a way to re-execute the same binary image so that the task re-opens configuration files,
re-establishes network connections - whatever it be - when a suitable POSIX signal is delivered to it.

```golang
func main() {
    if err := selfExec(); err != nil {
        // Process err
    }
    // Exit this process
}

func selfExec() error {
    // Setup the binary name/path, any standard/file/socket
    // descriptors and environment variables.
    // Start a new process using os.StartProcess(..)
}
```

Let's now look at how we can now support simple binary restarts using Go's excellent support for POSIX signals.
We will deliver [`SIGHUP`](https://en.wikipedia.org/wiki/Unix_signal#POSIX_signals) to our
`sigch` channel so the binary can re-execute.

```golang
sigch := make(chan os.Signal, 1)
signals.Notify(sigch, syscall.SIGHUP, syscall.SIGTERM)
for {
    // Something something...
    select {
        case sig := <-sigch :
            if sig == syscall.SIGHUP {
                // Re-Execute ourself
            } else {
                // Process other signals
            }
    }
}
```

Since this is a post about Go, we'll keep Bash away but using [`trap`](http://tldp.org/LDP/Bash-Beginners-Guide/html/sect_12_02.html)
in Bash is yet another way to achieve the same thing. UNIX hmm.. let me phrase it as **goat many ways to the skin**.
