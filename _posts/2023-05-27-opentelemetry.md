# OpenTelemetry Report

I recently went on a couple of months long migration to [OpenTelemetry](https://opentelemetry.io) from DataDog, and 
here are some thoughts specific to [OTLP](https://opentelemetry.io/docs/specs/otlp/) that may be of interest to you.

### TL;DR

Emitting all three signals (metrics, traces and logging) in concert and expecting to be able to easily correlate them 
in the telemetry backend is not straight forward path (also it highly depends on which telemetry backend you choose).

### Metrics

For OpenTelemetry's OTLP metrics, you can be assured that for a long-running service, this is pretty stable.
You can choose to ingest with OTLP and fan-out to other vendors like DataDog; there are no surprises involved.

For FaaS workloads (AWS Lambda), it's a different story. The OpenTelemetry [Collector](https://github.com/open-telemetry/opentelemetry-lambda)-based,
metrics in a FaaS environment is not reliable. I hope it will eventually get there, but exactly when that will happen is
unknown. It depends on some [key features being implemented in Lambda runtime](https://github.com/open-telemetry/opentelemetry-lambda/blob/main/docs/design_proposal.md#2-technical-challenges) to mitigate issues involved with the 
'freeze' and 'thaw' of containers.

### Traces
                                                  
OTLP-based traces are pretty stable in the long-running service world. Again, you can choose to ingest 
with OTLP and fan-out to other vendors like DataDog, and there are no surprises involved.

However, for FaaS workloads such as AWS Lambda, due to the aforementioned freeze & thaw interaction within the extensions'
environment, is yet to materialize fully.

### Logs

For OTLP-based logs are a complicated story. It varies on the log sink involved, execution environment, and other constraints.
In general, your mileage will vary. OTLP-based log pipelines are not yet widely adopted and are not production ready. 
So, this is a case of **YMMV**.

### Continuous Profiling

OTLP-based continuous profiling is unheard of; it currently exists in the _proposals'_ basket.

### Observations

OpenTelemetry's list of dirty laundry is long, and it will take a while to get it widely adopted. But here are a few 
key ones I have observed:
- Contributing vendors have many self-driven interests and agendas that do not necessarily benefit the OpenTelemetry's
  open ecosystem.
- OpenTelemetry working groups often fail to come to consensus thus impacting deliveries caused by countless number of
  mundane arguments on the technical merits of a given implementation and design, in addition to lack of leadership (sure,
  I understand large opensource efforts are not trivial, but it does not take 2+ years to deliver *a* feature).
- OpenTelemetry development is _actually_ siloed; I probably need not say more.

All of this brings me to the following conclusion:
> Closed vendors like DataDog can charge $65 million dollars to *one* customer (just like a raging bull) because their
> o11y stack is fully baked (all four signals - metrics, traces, logs and profiling) and production ready.

However, all is not lost. OpenTelemetry has a lot of good things going for it, and I am excited to see where it goes.
Here are some of the good things I _love_ about OpenTelemetry:
- Wide number of telemetry integrations with _you name it vendor_
- An opportunity to shape the Observability landscape for the foreseeable future
- Wide variety of language support, telemetry receivers, processors and exporters to choose from
- A very active and responsive core team that is willing to help and contribute
- Extreme momentum in the community relating to releasing features and bug fixes
- Many future enhancements are shaping as we speak, such as using eBPF, client-side metrics aggregations, 
  exemplars, and many Rust-based :) telemetry components are in the works, and many more. 
