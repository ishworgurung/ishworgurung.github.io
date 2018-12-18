- [Hashicorp Nomad; the missing distributed job scheduler](#hashicorp-nomad-the-missing-distributed-job-scheduler)
  - [What's Nomad](#whats-nomad)
  - [Jobs](#jobs)
    - [Job Example](#job-example)
    - [Job Constraint](#job-constraint)
  - [Scheduler Types](#scheduler-types)
  - [Nomad ecosystem](#nomad-ecosystem)

**Disclaimer: I do not work for Hashicorp**

## Hashicorp Nomad; the missing distributed job scheduler

Today, the world is a different place compared to five years ago. Distributed job schedulers are a common thing and in particular, the world has fallen in love
with Kubernetes - the winner of today's distributed cluster scheduler war. Kubernetes and its software infrastructure ecosystem is evolving at an enormous pace; 
I doubt there will be another scheduler to replace Kubernetes for the near future. If you would like to learn more about Kubernetes, I recommend downloading 
[minikube](https://github.com/kubernetes/minikube#installation) and giving it a whirl; There's a lot to love about Kubernetes and the basis of its model Borg. 
In this post, I would like to switch the context to something a little different as I feel the container scheduler market is a bit unevenly distributed and 
if I may hazard a guess, many of my fellow engineers are probably not aware of other tools in this space. So, let's talk about Nomad; a really well thought out
piece of cluster scheduler from Hashicorp.

I have spoken to few folks that describe any particular piece of software from Hashicorp as being *but-i-need-to-buy-into-the-entire-Hashistack-ecosystem* to get
the benefits; I think their concern is *warranted*. It's quite true that a lot of the Hashicorp products (enterprise or otherwise) works extremely well when used
in concert. However, their open-source offering can also be used as a standalone tool without a need to integrate with the rest of their stacks. Many shops today
already use Terraform for infrastructure deployment, Consul as a generic service discovery layer and Packer for provisioning VM images. They all work quite well
*independently* as well.

### What's Nomad
As with many other cluster schedulers, Nomad is a single binary cluster orchestrator/scheduler with support for many different types of `driver` backend. There
are two operating modes in the `nomad` binary - a master and a worker. Cluster can scale up to support lots of workers on a scale-out basis with each of these
node allocated jobs by the master node.

When Nomad service is brought up, it fingerprints the host it is running on - to gather system details such as the number of cores, size of memory available, 
disk space and network speed. It then later uses these fingerprinted data amongst others to make an informed decision on how to *allocate* resources for tasks
on the worker nodes.

Here are few of the things that Nomad is really good at. Nomad aims to cater for a subset of what Kubernetes provides - the deployment scheduler with an excellent
bin-packing of workload on the cluster; But, where it differentiates itself from other schedulers in the market is its fucktillion number of support for different 
`driver` backend. It can run not only `Docker` containers but anything from single `Fork/Raw Exec` binaries, `Java` applications, `QeMU` VM images, `rkt` containers,
`LXC` containers and more (they aim to make it extensible for any driver backend). The driver backend `LXC` is still experimental as of version `0.8` but you can 
clearly see the number of available options. Nomad gives users the opportunity to deploy in many different format and runtime.

### Jobs
A unit of deployment in Nomad is described declaratively using `job` which comprises of `group`(s) and `task`(s) stanza. A jobspec is developed using 
[Hashicorp Configuration Language](https://github.com/hashicorp/hcl); a rather easy to comprehend moving piece. Jobs defined using jobspec can be planned, created,
auto-scaled, rolling updated, canary deployed and destroyed with trivial amount of work. 

#### Job Example
To give a bit more context, below is a simple [jobspec](https://www.nomadproject.io/docs/job-specification/index.html) for [Fabio](https://fabiolb.net).

```
# Based off https://github.com/clstokes/example-nomad-nginx-secrets/blob/master/fabio.nomad
job "fabio" {
  region = "au"
  datacenters = ["dc1"]
  type = "system"
  group "fabio" {
    count = 1
    task "fabio" {
      driver = "raw_exec"
      artifact {
        source = "https://github.com/fabiolb/fabio/releases/download/v1.5.9/fabio-1.5.9-go1.10.2-linux_amd64"
      }
      config {
        command = "fabio-1.5.9-go1.10.2-linux_amd64"
      }
      resources {
        cpu    = 500 # 500 MHz
        memory = 256 # 256MB
        network {
          mbits = 10
          port "http" {
            static = 9999
          }
          port "admin" {
            static = 9998
          }
        }
      }
    }
  }
}
```

#### Job Constraint
Nomad supports job constraints out of the box. When jobs are allocated but yet to be scheduled to a node, Nomad tries to match the constraints provided in
the jobspec to a worker node. If it can be satisfied, the job is scheduled for deployment and go operational on the node. Below is a simple job constraint definition:
```
job "apache-ts" {
  # This will constrain this job to only run on Intel 64-bit hosts.
  constraint {
    attribute = "${attr.cpu.arch}"
    value     = "amd64"
  }
  # This will restrict the job to only run on clients with 8 or more cores.  
  constraint {
    attribute = "${cpu.numcores}"
    operator  = ">="
    value     = "8"
  }
  # Only run this job on a nitro-based instances
  constraint {
    attribute = "${attr.platform.aws.instance-type}"
    value     = "m5.16xlarge"
  }
  # Only run this job on linux
  constraint {
    attribute = "${attr.kernel.name}"
    value     = "linux"
  }

  [ ... ]
}
```


### Scheduler Types

Nomad provides different guarantees around the type of schedulers used. As of version `0.8`, it has three types of schedulers:
  - `system` - a scheduler type provided for jobs that needs to run on all worker nodes for e.g. a metric forwarder/aggregator
  - `service` - a scheduler type provided for long running job for e.g. a µservice
  - `batch` - a scheduler type provided for one shot job for e.g. a report generator

*TODO*

### Nomad ecosystem

*TODO - Vault + Nomad*

