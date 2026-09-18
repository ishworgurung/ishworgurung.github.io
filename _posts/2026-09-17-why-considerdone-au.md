# Why ConsiderDone.au

![ConsiderDone logo]({{ '/posts/considerdone-logo.png' | relative_url }}){: .post-float-image}

Most home-service jobs begin with a small but annoying problem: a leaking tap, a broken appliance, a lockout, or a fault that needs an electrician. The work itself may be simple. Getting it done is not.

The usual process asks the homeowner to search, compare reviews, call several businesses, explain the same problem repeatedly, wait for quotes, coordinate a time, and work out how to pay. That is a lot of effort for something people only want to think about once.

I built [considerdone.au](https://considerdone.au) around a simple question: what if a person could say, “Find someone reliable, book them, and let me approve the price,” then get on with their day?

The aim is not to replace tradespeople. It is to remove the administrative gap between a homeowner who needs help and a local business that can do the work.

## The gap in the current marketplace model

Existing marketplaces are useful discovery tools, but they often stop at the hardest part. A homeowner still has to make the calls and decide what happens next. Many platforms also sell the same lead to several providers, which turns a customer’s problem into a race to respond.

That is frustrating for both sides. Homeowners spend time doing coordination work. Providers pay for leads that may be shared with several competitors and may never become a booking.

considerdone.au takes a different path. It starts with one plain-language request. The system searches for relevant local providers, contacts them by phone, asks about availability and price, and brings the result back to the homeowner for approval.

The important distinction is that the product is designed to finish the workflow, not merely generate a lead.

## What the service is actively solving

The product has three jobs to do well:

1. Find a suitable provider for the task and location.
2. Turn the request into a real booking without making the homeowner chase people.
3. Handle money in a way that is clear, controlled, and fair to both parties.

The first version uses local-search data to find and rank candidates. It then uses an [outbound voice](https://en.wikipedia.org/wiki/Interactive_voice_response) workflow to speak with businesses in the normal channel they already use: the phone. A provider does not need to join a new marketplace or adopt a new [point-of-sale](https://en.wikipedia.org/wiki/Point_of_sale) system before they can take a job.

The homeowner stays in control. Before the system makes calls, it asks for approval. When a real quote comes back, it asks again before charging anything. Those two pauses are intentional. Delegation should reduce effort, not remove consent.

## How a job moves through considerdone.au

![ConsiderDone.au job workflow]({{ '/posts/job-states.svg' | relative_url }}){: .post-full-image}

The homeowner makes the important choices. considerdone.au does the coordination work in between, and the provider stays in control of the work, availability, and completion.

## Engineering for a real-world workflow

The difficult part is not making an AI place a phone call. The difficult part is making the whole workflow dependable when it touches real people, real calendars, and real money.

That has shaped the engineering decisions behind considerdone.au.

### The orchestrator owns the journey

A booking moves through many steps: search, calling, quote collection, approval, payment, provider details, job completion, and payout. One [orchestration](https://en.wikipedia.org/wiki/Orchestration_(computing)) layer coordinates those steps, while each integration stays narrowly focused on its own job.

For example, the calling service does not decide who gets paid, and the payment service does not decide which provider to call next. Keeping those responsibilities separate makes failures easier to understand and changes safer to make.

### Actions are designed to be safe to retry

External systems fail. A server can restart halfway through a task. A network request can time out after the other side has already accepted it. Retrying blindly can create duplicate calls or, worse, duplicate charges.

For that reason, side-effecting operations use persistent [idempotency keys](https://en.wikipedia.org/wiki/Idempotence) and [database constraints](https://en.wikipedia.org/wiki/Database_constraint). The system records its progress and can resume in-flight tasks after a restart instead of treating a restart as a failed job. This is less glamorous than the voice interface, but it is essential infrastructure for a service that makes bookings and moves money.

### Structured results, not AI interpretation after the fact

Phone conversations are messy. The application does not use raw transcripts to make booking decisions. Instead, the call workflow returns specific structured fields such as outcome, quote, time slot, and whether the provider needs a site visit.

That boundary matters. It gives the workflow defined data to act on, makes it testable, and avoids having hidden interpretation drive a payment or state change.

### Payment follows approval, not assumption

For a standard job, the system first places an [authorisation hold](https://en.wikipedia.org/wiki/Authorization_hold) for the homeowner’s agreed spending cap. It only captures the exact quoted amount after the homeowner approves it. If the quote is declined or no provider works out, the hold is not captured.

After the job is complete, the provider submits completion through a secure, time-limited link. The homeowner can release payment, dispute it, or allow the stated review period to expire. The provider is then paid by bank transfer, less a clearly disclosed booking fee. The consumer pays the quote they approved, with no surprise surcharge added on top.

This two-leg payment model reflects the real timing of a service job: booking and charging happen first; provider payout happens only after completion and review.

## Adapting to how trades actually quote

One of the most useful lessons from the build was that not every job can be priced on the phone.

A tap washer or lockout may be straightforward. A hidden leak, electrical fault, or compliance-sensitive job often is not. In many cases, a provider needs to inspect the site before they can responsibly give a price.

Rather than forcing every task into a one-call quote, considerdone.au supports two paths:

- For phone-quotable work, the homeowner can approve a quote and book directly.
- For diagnosis-first work, the system can book a call-out visit first. The provider then submits an on-site price, and the homeowner gets a separate approval decision before the actual job is charged.

This is a deliberate product choice. A new, unknown on-site price is never automatically approved. The call-out visit is treated as its own booking, so the provider is still paid for their time even if the homeowner declines the later job price.

The fee model follows that reality too. The call-out fee has a small pass-through fee, while the actual job carries the main booking fee. It is a more honest model than pretending a visit is free or expecting providers to absorb the cost of diagnosis.

## Trust is a product feature, not a marketing claim

If a system is going to act for someone, it needs strong boundaries.

considerdone.au keeps card numbers out of its servers by using a browser-based [tokenized](https://en.wikipedia.org/wiki/Tokenization_(data_security)) payment component. It keeps an append-only [audit trail](https://en.wikipedia.org/wiki/Audit_trail) of state-changing events while storing event payloads as [cryptographic hashes](https://en.wikipedia.org/wiki/Cryptographic_hash_function) rather than raw data. Provider payout links are random, scoped to one booking, time-limited, and single-use.

The product also has safety screening before a provider is contacted. Normal service requests proceed. Requests that suggest an emergency, harm, or criminal intent are stopped and handled with an appropriate response. The system does not automate reports or make high-stakes decisions from a phone transcript.

There are also areas where the work is intentionally not presented as finished. Provider [ABN](https://en.wikipedia.org/wiki/Australian_Business_Number) and licence verification need a practical, state-by-state rollout plan. Disputes are handled manually in the first version. Preventing off-platform repeat transactions will require a better mix of customer protection, provider incentives, and repeat-booking value than a simple discount can offer.

Naming those gaps is part of building trust. The point is to solve the problems that can be solved now, measure the uncertain ones, and avoid pretending a complex marketplace is complete before it is.

## Building toward a useful local service agent

considerdone.au is being built as a practical assistant for a very ordinary problem: something at home needs fixing, and someone needs to make the booking happen.

The direction is simple. Make the first request easy. Keep the homeowner in control. Respect providers’ existing way of working. Be precise about money. Make the system recover gracefully when real life does not follow the happy path.

The technology matters, but the standard is simpler: when a homeowner asks for help, the experience should leave them able to say, “consider it done.”

The future here is bright. As [x402](https://www.x402.org/) and other [agentic AI](https://en.wikipedia.org/wiki/Agentic_AI) payment rails mature, more of the trusted coordination around a job can happen quietly and safely in the background: matching, permissions, booking, settlement, and the record of what was agreed. That should mean fewer hand-offs and less administrative work for homeowners and providers alike. The human part that matters most remains human: the tradesperson’s judgement, skill, and work on site, while the surrounding workflow gets steadily simpler.
