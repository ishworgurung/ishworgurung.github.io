---
title: "Gradually, then suddenly: AI and the 10× attacker"
---

<div class="quote-with-photo" markdown="1">

<div class="quote-row" markdown="1">

<figure class="quote-photo">
  <img src="/assets/img/posts/2026-11-03-ernest-hemingway.png" alt="Black-and-white photograph of Ernest Hemingway, grey-bearded and wearing glasses, writing with a pen in a notebook at a wooden table inside a tent." width="750" height="419">
</figure>

> "How did you go bankrupt?" Bill asked.
> "Two ways," Mike said. "Gradually and then suddenly."
>
> — Ernest Hemingway, *The Sun Also Rises* (1926)

</div>

<p class="quote-credit">Hemingway writing at his campsite in Kenya, 1953. Photo: <a href="https://commons.wikimedia.org/wiki/File:Ernest_Hemingway_Writing_at_Campsite_in_Kenya_-_NARA_-_192655.jpg">Look Magazine, JFK Library via the US National Archives</a> (public domain).</p>

</div>

A breachpocalypse can arrive the same way. For years the security backlog grows only slightly faster than teams can clear it, and each year that looks manageable, because it is. Then the conditions change underneath it, and the growth stops being slight.

{% include cve-monthly-chart.html %}

For most of a decade the number of newly published vulnerabilities (CVEs) climbed steadily, and security teams scaled their patching to keep up, more or less. In 2026 the curve turned upward: more CVEs were published in the first ten months than in 2024 and 2025 combined. A CVE is not a breach. It is a bug someone has disclosed, an item in the defender's queue. The queue is where the "suddenly" starts, and the rest of this post is about what is filling it.

The queue matters because it is now the main way in. Verizon's 2026 Data Breach Investigations Report found that exploiting a vulnerability was the most common first step in a breach, at 31%, overtaking stolen credentials for the first time in the report's nineteen years. Over the same period the median time organisations took to fix a known-exploited vulnerability *rose*, from 32 days to 43. ([Verizon](https://www.verizon.com/about/news/breach-industry-wide-dbir-finds) · [TechTarget](https://www.techtarget.com/news/Verizon-2026-DBIR-6-key-takeaways-for-CISOs/836215/)) More bugs, more of them used, fixed more slowly. That is the "gradually".

Let's be clear: the defender's job was never easy. You have to be right every time, across every asset, every patch window and every tired employee reading email at 4:55pm on a Friday. The attacker has to be right once. That asymmetry is older than most of us in this industry.

What changed in the last two years is the attacker's side of the ledger. The tempting way to say it is "the attacker's job just became *x* times easier because of AI", and then pick a dramatic *x*. Vendors say 100×. Sceptics say 1×, "it's just autocomplete". Both are wrong, and the gap between them is where the useful answer is. This post tries to put a number on *x* from measurements rather than vibes, and to be honest about where the number breaks down. I'll call that number the **attacker's multiplier**: how many times cheaper AI has made the same attack, counting money, elapsed time or skilled hours. A multiplier of 10× means the attack now costs a tenth of what it did; 1× means AI changed nothing.

The short version: **the multiplier is not one number. For an ordinary operation against an ordinary target in late 2026, it is about 10×: between 5× and 10× by the most direct measure, and rising. It is close to 1× on technique, between 10× and 50× on phishing economics, and effectively unbounded for a low-skill actor who previously could not do the job at all.** In 2024 the same calculation gave about 3×. On the defender's side, the best controlled measurements of AI help show analysts working about a quarter faster, nearer 1.3× than 10×. That gap is the subject of the second half of this post.

<div class="terms" markdown="1">

**📖 Terms in this post**

- **Attacker's multiplier.** This post's measure: what an attack cost without AI ÷ what the same attack costs with AI, in money, time or skilled hours. 10× means a tenth of the cost. Written *x* where it stands for the unknown in "*x* times easier".
- **Uplift.** How much more harm an actor causes *with* AI than *without* it. Anthropic splits it into speed, scale and depth. ([Anthropic, September 2026](https://www.anthropic.com/threat-intelligence-report-september-2026))
- **GTG.** Generative Threat Group: Anthropic's internal tracking name for an actor it caught misusing its models, such as GTG-1002 or GTG-50014. It works like Microsoft's "Storm-" or Mandiant's "UNC" numbers: a label for a cluster of activity, not a confirmed identity. Other vendors track the same actors, where they track them at all, under their own names. ([Anthropic, September 2026](https://www.anthropic.com/threat-intelligence-report-september-2026))
- **N-day.** A vulnerability that is publicly disclosed, usually with a patch available, but not yet patched on the target.
- **Zero-day.** A vulnerability the vendor does not know about, so no patch exists.
- **KEV.** CISA's [Known Exploited Vulnerabilities](https://www.cisa.gov/known-exploited-vulnerabilities-catalog) catalogue: CVEs with evidence of exploitation in the wild. The closest thing the industry has to a "patch these first" list.
- **Time-to-exploit (TTE).** Mandiant's average of the days between a patch's release and the vulnerability's first observed exploitation, across every vulnerability it saw exploited that year. A zero-day is exploited *before* its patch, so it counts as a negative number, and the average can go below zero. ([Mandiant on TTE](https://cloud.google.com/blog/topics/threat-intelligence/time-to-exploit-trends-2023) · [M-Trends 2026](https://www.resilientcyber.io/p/m-trends-2026-what-450000-hours-of))
- **Breakout time.** CrowdStrike's measure of how long an intruder takes to move from the first compromised host to another host on the network.
- **Open-weight model.** A model whose weights anyone can download and run, which means safeguards can be removed and nobody sees the prompts.
- **Phishing-resistant MFA.** Multi-factor authentication that a fake login page cannot relay, because the credential is bound to the real site. In practice that means FIDO2/WebAuthn (passkeys, security keys) or smart cards. ([CISA](https://www.cisa.gov/sites/default/files/publications/fact-sheet-implementing-phishing-resistant-mfa-508c.pdf))
- **Amdahl's law.** The speed-up of a whole job is limited by the part you did not speed up. Used below to turn per-stage multipliers into one number. ([Amdahl's law](https://en.wikipedia.org/wiki/Amdahl%27s_law))

</div>

> Point-in-time (early November 2026). Every number below comes from a named report, paper or dataset, linked in [Sources](#-sources). They come from five kinds of source: academic studies, government agencies, breach datasets, security vendors and AI labs. The last two each have a reason to make the problem look large *or* their own product look effective. I flag where that matters, and I prefer the first three where they exist.

## 🧩 Why one multiplier is the wrong question

An attack is a pipeline: reconnaissance, initial access, exploitation, lateral movement, collection, exfiltration, monetisation. AI does not speed up each stage by the same amount, and which stage it speeds up depends on who is attacking.

- A **top-tier state team** already had the skills. AI mostly saves them labour, so for them it is a staffing multiplier.
- A **mid-tier criminal crew** gets labour savings and fills in some skill gaps, such as exploit writing, malware in an unfamiliar language, or a fluent lure in a language they do not speak.
- A **low-skill actor** gets a capability they did not have. Dividing by roughly zero gives a meaningless multiplier, which is the honest answer.

AI is not confined to one stage, either. When Verizon's researchers worked with Anthropic to map how threat actors used AI onto the MITRE ATT&CK framework, they found it across 15 techniques, with some actors using it for 40 or 50. ([TechTarget on DBIR 2026](https://www.techtarget.com/news/Verizon-2026-DBIR-6-key-takeaways-for-CISOs/836215/)) Anthropic's own September 2026 report reaches the same conclusion from the other side: "every layer of offensive operations has been uplifted". ([Anthropic, September 2026](https://www.anthropic.com/threat-intelligence-report-september-2026))

So the right question is *a multiplier for whom, at which stage, measured how?* Here is what the evidence says, stage by stage.

## 🪝 Phishing and social engineering: 10× to 50×

This is the best-measured stage, and the one where uplift is largest and least disputed.

Heiding, Schneier, Vishwanath and colleagues sent spear-phishing emails to 101 human subjects. Generic phishing got about 12% click-through. Emails written by human experts got 54%. Emails written end to end by an AI pipeline, including the target research, also got 54%. With a human in the loop it was 56%. ([Heiding et al.](https://arxiv.org/abs/2412.00586))

So the AI matched the experts on quality, and it did so at about 92% lower cost, which is roughly **12× cheaper per target**. The paper's economic model puts the gain in *profitability* at **up to 50×** for large campaigns. It also found AI spear phishing beats human-crafted spear phishing on profit for audiences as small as about 5,000 people, so a mid-sized company is now worth personalising for.

Email is only the channel that has been measured carefully. The others are moving the same way:

- **Voice.** CrowdStrike counted a 442% rise in voice phishing ("vishing") between the first and second halves of 2024, as crews phoned help desks posing as employees to get passwords and MFA reset. ([CrowdStrike 2025](https://www.crowdstrike.com/en-us/press-releases/crowdstrike-releases-2025-global-threat-report/))
- **Mobile.** Verizon's 2026 report found social engineering on mobile succeeding about 40% more often than email phishing. ([Verizon](https://www.verizon.com/about/news/breach-industry-wide-dbir-finds))
- **Video.** In January 2024 a finance employee in Arup's Hong Kong office was persuaded to make 15 transfers totalling about US$25 million after a video call with what appeared to be the company's CFO and colleagues. All of them were fakes. Hong Kong's government later told its legislature that police believed the video was pre-recorded from public clips rather than generated live, which is a useful reminder that the trick does not need to be sophisticated to work. ([CNN](https://www.cnn.com/2024/05/16/tech/arup-deepfake-scam-loss-hong-kong-intl-hnk))

**Calibrated multiplier for phishing: 10× to 50×**, depending on campaign size. Quality did not go up; cost per target fell by an order of magnitude. Spear phishing used to be reserved for high-value targets. Now it is the default.

## ⏱️ Exploiting known vulnerabilities: from 3× to "weeks into hours"

In April 2024, Fang, Bindu, Gupta and Kang gave a GPT-4 agent 15 real one-day vulnerabilities along with their CVE descriptions. It exploited 87% of them, while every other model and scanner they tested got 0%. Without the CVE text it got 7%. They put the cost at $8.80 per successful exploit against $25 for a human expert, or **2.8× cheaper**, and noted that the agent scales and the human does not. ([Fang et al.](https://arxiv.org/abs/2404.08144))

2.8× is a good figure to anchor on, because it is small and it is old. It measured a weak agent on easy web bugs. Two years later:

- Claude Mythos Preview wrote a Linux N-day privilege escalation for **under $1,000 in about half a day**, and a chained kernel privilege escalation for **under $2,000 in under a day**. Expert penetration testers said some exploits it wrote in hours would have taken them weeks. ([Anthropic, April 2026](https://www.anthropic.com/research/mythos-preview))
- GLM-5.3, an open-weight model, produced a chained exploit for a known Chrome flaw from **20 minutes of human attention and about eight hours of model time, about $20 at API prices**. ([Anthropic, September 2026](https://anthropic.com/research/glm-5-3-and-the-spread-of-advanced-cyber-capabilities))
- OpenAI's own evaluations show the same slope over a shorter window: success on its capture-the-flag challenges went from 27% for GPT-5 in August 2025 to 76% for GPT-5.1-Codex-Max three months later. ([OpenAI](https://openai.com/index/strengthening-cyber-resilience/))

"Weeks to hours" is a 10× to 50× reduction in elapsed time, and the dollar cost is now trivial compared with a professional exploit developer's time. The defender's patch window has been shrinking for years:

| Period | Mandiant mean time-to-exploit |
|---|---|
| 2018–2019 | 63 days |
| 2021–2022 | 32 days |
| 2023 | 5 days (outlier-adjusted; 47 with outliers) |
| 2024 | about −1 day |
| 2025 | about −7 days |

Mandiant measures each exploited vulnerability from the day its patch shipped. An N-day exploited ten days after the patch scores +10. A zero-day exploited thirty days *before* any patch existed scores −30. The table is the average of both kinds together, and zero-days are now the majority: of the 138 vulnerabilities Mandiant tracked as exploited in 2023, 97 (70%) were zero-days. ([Mandiant](https://cloud.google.com/blog/topics/threat-intelligence/time-to-exploit-trends-2023)) Once enough negative zero-day scores go into the mean, it drops below zero.

So "−7 days" does not mean a typical N-day is exploited a week before its patch. It means the exploited population is dominated by bugs that had no patch to apply at all, and that the N-days in the mix are exploited quickly enough not to pull the average back up. Both halves are bad news for a defender whose main control is patching.

Put the attacker's clock next to the defender's and the problem is plain. Verizon's 2025 report found that organisations fully fixed only about 54% of the edge-device vulnerabilities it tracked, and took a median of 32 days to do it, while edge devices and VPNs went from 3% to 22% of exploitation breaches in a year. ([SecurityWeek on DBIR 2025](https://www.securityweek.com/verizon-dbir-flags-major-patch-delays-on-vpns-edge-appliances/)) In the 2026 report, the share of known-exploited vulnerabilities organisations fully fixed fell from 38% to 26%. ([TechTarget on DBIR 2026](https://www.techtarget.com/news/Verizon-2026-DBIR-6-key-takeaways-for-CISOs/836215/)) A defender working in weeks is up against an attacker working in hours.

A caution: this curve was already falling steeply in 2021–2023, before capable exploit-writing agents existed. AI did not start the trend and the table does not isolate its contribution. What AI changes is the cost of both halves: it removes the skilled labour that used to sit between an advisory and a working N-day exploit, and, as the next section shows, it makes finding new zero-days far cheaper. The UK NCSC said in May 2025 that AI will "almost certainly" shorten the disclosure-to-exploitation gap further by 2027. ([NCSC](https://www.ncsc.gov.uk/report/impact-ai-cyber-threat-now-2027)) The data since then has not argued with them, and neither has CISA: its June 2026 patching directive notes that attackers' "use of AI may further narrow the time defenders have to react between patch release and possible exploitation". ([CISA BOD 26-04](https://www.cisa.gov/news-events/directives/bod-26-04-prioritizing-security-updates-based-risk))

**Calibrated multiplier for N-day exploitation: about 3× in 2024, about 10× or more in 2026**, measured as labour and elapsed time per working exploit.

## 🐛 Finding new vulnerabilities: a step change, and also the defender's best tool

This is the stage where the 2024 answer and the 2026 answer differ most, and 2025 shows the path between them.

- **2024: mostly can't.** Fang's agent, the one that exploited 87% of known bugs, found only 7% when it was not told where to look. ([Fang et al.](https://arxiv.org/abs/2404.08144))
- **2025: can, but noisy.** Sean Heelan used OpenAI's o3 to find CVE-2025-37899, a remotely reachable use-after-free in the Linux kernel's SMB server. His write-up is unusually honest about the hit rate. Given one 3,300-line handler, o3 found a known bug in 8 of 100 runs, with 28 false positives. Given 12,000 lines, it found it once in 100 runs, a signal-to-noise ratio of about 1:50, for about $116 in total. His conclusion was that the models make experts "significantly more efficient and effective", not that they replace them. ([Heelan](https://sean.heelan.io/2025/05/22/how-i-used-o3-to-find-cve-2025-37899-a-remote-zeroday-vulnerability-in-the-linux-kernels-smb-implementation/)) That June, XBOW's autonomous tester reached the top of HackerOne's US leaderboard after submitting about 1,060 reports. Humans reviewed each one before submission, and XBOW credited automated *validators* for keeping the noise down. ([XBOW](https://xbow.com/blog/top-1-how-xbow-did-it))
- **2026: can, reliably.** Early 2026 frontier models were good at finding crashes and poor at weaponising them. On Firefox's JavaScript engine, Claude Opus 4.6 produced a working exploit **twice in several hundred attempts**. Claude Mythos Preview, on the same task, produced **181 working exploits**, plus register control on 29 more. Anthropic described Opus 4.6's autonomous exploit-development rate as "near 0%". ([Anthropic, April 2026](https://www.anthropic.com/research/mythos-preview)) A multiplier measured against near zero is not a meaningful number, and that is the point: in one model generation this went from "can't" to "can".

Two things stop this turning into a doomsday multiplier.

**First, the strongest capability was handed to defenders first.** Mythos Preview was not released publicly. Through Project Glasswing, partners found more than ten thousand high- or critical-severity vulnerabilities in the first month. Independent firms checked 1,752 of the open-source findings and confirmed 90.6% as real. ([Anthropic, Glasswing update](https://www.anthropic.com/news/glasswing-initial-update)) Defenders had used earlier tools this way too. In July 2025 Google said its Big Sleep agent had found an SQLite flaw (CVE-2025-6965) that threat-intelligence signals suggested attackers were preparing to use, and got it fixed first, which Google called the first time an AI agent had directly foiled exploitation in the wild. ([Google](https://blog.google/technology/safety-security/cybersecurity-updates-summer-2025/))

**Second, the head start is short.** NIST's CAISI found the open-weight GLM-5.3 trailing the US frontier by about **four months** on cyber benchmarks. On a V8 exploitation benchmark it built end-to-end exploits in 50 of 410 attempts, against Mythos Preview's 56. Its safeguards could be removed for about $4,400 of GPU time with little loss of capability. ([Anthropic, September 2026](https://anthropic.com/research/glm-5-3-and-the-spread-of-advanced-cyber-capabilities)) Whatever defenders can do with a frontier model today, assume an attacker with a downloaded model can do it next season with nobody watching.

**Calibrated multiplier for zero-day discovery and exploitation: undefined as a ratio, and the absolute capability is real.** It was niche in 2024, noisy but useful in 2025, and is now available to anyone who can run an open-weight model.

## 🤖 Running the operation: one operator, team-sized output

The measurements here come from incident reports rather than experiments, so they say more about *scale* than about a clean multiplier.

- **GTG-2002 (disclosed August 2025).** A single criminal operator used Claude Code to scan thousands of VPN endpoints, break into at least 17 organisations including hospitals, emergency services and government bodies, decide which data to steal, and draft ransom notes, some demanding more than $500,000. Nothing was encrypted; it was pure data theft and extortion. Anthropic called it "vibe hacking". ([Anthropic, August 2025](https://www.anthropic.com/news/detecting-countering-misuse-aug-2025))
- **GTG-1002 (disclosed November 2025).** A state-linked espionage group ran Claude Code as an orchestration engine against about 30 organisations. Anthropic estimated the AI did **80–90% of the tactical work**, with humans involved at a handful of decision points. At its peak it made "thousands of requests, often multiple per second", a pace Anthropic said human operators could not match. Its mistakes and false positives forced the operators to add human checkpoints, and a small number of intrusions succeeded. ([Anthropic, November 2025](https://www.anthropic.com/news/disrupting-AI-espionage))
- **Malware that calls a model.** Also in November 2025, Google's threat intelligence group reported the first malware it had seen querying an LLM during live operations: PROMPTSTEAL, used by Russia's APT28 against Ukraine, which asks a hosted model to write the commands it runs on each victim. A second family, PROMPTFLUX, asks Gemini to rewrite its own code to evade antivirus, though Google assessed it as still experimental. ([Google GTIG](https://cloud.google.com/blog/topics/threat-intelligence/threat-actor-usage-of-ai-tools))
- **FortiGate (January–February 2026).** A Russian-speaking actor that Amazon assessed as **low-to-medium skill** used commercial LLMs to plan, write tooling for, and run a campaign that compromised **more than 600 firewalls in over 55 countries in five weeks**. No vulnerability was exploited: exposed management ports, reused passwords, no MFA. Amazon's summary: the advantage was "AI-augmented efficiency and scale, not deeper technical skill". ([AWS Security Blog](https://aws.amazon.com/blogs/security/ai-augmented-threat-actor-accesses-fortigate-devices-at-scale/))
- **Anthropic's September 2026 report.** One actor went from a single stolen developer token to full administrative control of a cloud estate in about three hours. A lone hacktivist tracked 42 targets and got inside at least 14. A financially motivated actor hit about thirty AI companies in four days by repeating one attack path. ([Anthropic, September 2026](https://www.anthropic.com/threat-intelligence-report-september-2026))
- **Breakout time.** CrowdStrike's average eCrime breakout time fell from 48 minutes in its 2025 report to **29 minutes** in its 2026 report, with the fastest at 27 seconds. ([CrowdStrike 2025](https://www.crowdstrike.com/en-us/press-releases/crowdstrike-releases-2025-global-threat-report/) · [CrowdStrike 2026](https://www.crowdstrike.com/en-us/press-releases/2026-crowdstrike-global-threat-report/)) That is about 1.7×. Some of it is AI, some is better tooling and playbooks, and the report does not separate them.

The low end of the market moved too. In the same August 2025 report, Anthropic described a UK-based actor who used Claude to build ransomware kits, with encryption and anti-detection features, and sell them on criminal forums, while apparently being unable to write that code without it. ([Anthropic, August 2025](https://www.anthropic.com/news/detecting-countering-misuse-aug-2025)) That is the low-skill case in its purest form: the product exists only because the model does.

If one operator now does what took a team of five to ten, and an AI does 80–90% of the hands-on work, **the labour multiplier for running an operation is about 5× to 10×.**

## 🟰 Where the multiplier is still close to 1×

This is the part that rarely makes the headlines.

- **Technique.** Anthropic's September 2026 report says that "none of the operations" it disrupted relied on a novel technique. The attacks were familiar; the economics changed. The FortiGate campaign exploited no vulnerabilities at all. AI made *old* attacks cheap. It has not, in the wild and at scale, invented new classes of attack. Verizon's data agrees: fewer than 2.5% of the AI-assisted actions it analysed with Anthropic used uncommon techniques. ([TechTarget on DBIR 2026](https://www.techtarget.com/news/Verizon-2026-DBIR-6-key-takeaways-for-CISOs/836215/)) So did the NCSC's forecast, which expected AI to work "through evolution and enhancement of existing" techniques "rather than creating novel threat vectors". ([NCSC](https://www.ncsc.gov.uk/report/impact-ai-cyber-threat-now-2027))
- **Severity.** The same Anthropic report notes that several of the most serious compromises came from fully human-directed operations. Autonomy and impact are not the same thing.
- **Judgement.** Humans still chose targets, decided how to monetise, and checked results, in every case above. GTG-1002's operators had to add checkpoints because the model overstated its findings.
- **Noise.** AI makes junk cheap too. curl ended its bug bounty in January 2026 after a flood of AI-generated reports that were mostly invented. By mid-2026 the problem had changed shape: curl reportedly now receives a *correct* AI-generated report every 18 hours or so. ([The Register](https://www.theregister.com/security/2026/01/21/curl-shutters-bug-bounty-program-to-stop-ai-slop/5063039) · [Cybernews](https://cybernews.com/security/curl-bug-bounty-ai-security-reports-daniel-stenberg/)) Heelan's 1:50 signal-to-noise in 2025 and Glasswing's 90.6% confirmation rate in 2026 are the same story told with numbers. Junk was a temporary drag on attackers and researchers alike, and it is going away.

## 🎯 Putting the numbers together

First, a precise definition. For each stage, **the attacker's multiplier = what it cost the attacker to get a result without AI ÷ what the same result costs with AI**, where cost is money, elapsed time or skilled hours (each row says which). 10× means the job now costs a tenth of what it did. 1× means AI changed nothing.

### By stage

| Stage, and what the multiplier measures | 2024 | Late 2026 | Evidence, and how much to trust it |
|---|---|---|---|
| **Phishing**: cost per target, for the same click rate | ~12× (up to 50× profit at scale) | At least that; no newer controlled study | Heiding et al., tested on 101 people. *High*. Voice and mobile data from CrowdStrike and Verizon point the same way |
| **Exploiting known bugs**: cost and time per working exploit | ~3× | ~10× or more ("weeks into hours", $20–$2,000 per exploit) | Fang et al. 2024; Mythos Preview and GLM-5.3 in 2026; Verizon and Mandiant for the real-world window. *Medium*: lab costs and expert estimates |
| **Finding and exploiting new bugs**: working exploits per attempt | Near zero (2 in several hundred) | 181 on the same task; open-weight models ~4 months behind | Heelan and XBOW for 2025; Anthropic and NIST CAISI benchmarks for 2026. *Medium*: lab results, not real attacks. Starting from ~0, the ratio is not a meaningful number |
| **Running the operation**: skilled human hours per operation | No data | 5×–10× (AI does 80–90% of the hands-on work) | GTG-2002, GTG-1002, FortiGate, Anthropic September 2026, Google GTIG. *Medium*: incident reports |
| **Inventing new techniques** | ~1× | ~1× | "None of the operations" used a novel technique; under 2.5% of AI-assisted actions in Verizon's data were uncommon. *Medium-high*: two independent datasets agree |

### By attacker

The same stage gives very different multipliers depending on who is attacking, because the multiplier depends on what they could already do without AI.

| Attacker | What AI gives them | Multiplier |
|---|---|---|
| Top-tier state team | Fewer people for the same work | 5×–10×, a staffing multiplier |
| Mid-tier criminal crew | Fewer people, and fills skill gaps (exploits, malware, lures in other languages) | ~10× |
| Low-skill actor | Things they could not do at all before (FortiGate: 600+ firewalls, 55 countries, five weeks; ransomware kits from someone who could not code them) | No meaningful ratio: from "couldn't" to "can" |

### From stages to one number

The stage multipliers do **not** multiply together. A 50× cheaper phishing email does not make the whole operation 50× cheaper, let alone 50 × 10 × 10. An operation's cost is the *sum* of its stages, so the overall saving is limited by the parts AI did not speed up: choosing targets, judging results, monetising. This is [Amdahl's law](https://en.wikipedia.org/wiki/Amdahl%27s_law), applied to crime.

The incident reports tell us how big that leftover human part is. In GTG-1002, AI did 80–90% of the hands-on work, and humans did the rest. Even if the AI part had cost nothing, the operation could only get 5× (if humans still do 20%) to 10× (if they do 10%) cheaper overall. That is where the headline comes from: **for a typical operation in late 2026, the attacker's job is about an order of magnitude cheaper.** Not 2×, which ignores everything that happened in 2026. Not 100×, which would require the human share to fall to 1%.

The human share is falling. In one of the September 2026 cases, Anthropic says "AI agents performed nearly all of the work". As that share goes from 10% towards 1%, the ceiling on the multiplier goes from 10× towards 100×. That is the "suddenly" to watch for.

Even at 10×, the effect is large. A crew that could run ten operations a year can now run a hundred, and a target that was not worth attacking last year is worth attacking now.

## 🍾 The real asymmetry is in the bottlenecks

If AI helps both sides, why does the defender's job get harder rather than easier? Glasswing found vulnerabilities in their thousands, and in the Heiding study Claude 3.5 Sonnet caught 97% of the phishing emails with no false positives. Defenders get uplift too.

It is worth measuring how much. The best controlled data on AI help for defenders comes from Microsoft's randomised trials of Security Copilot: new analysts finished security tasks 26% faster and 44% more accurately, and experienced analysts 22% faster and 7% more accurately. ([Microsoft, new analysts](https://papers.ssrn.com/abstract=4648700) · [Microsoft, experienced analysts](https://www.microsoft.com/en-us/security/blog/2024/03/13/microsoft-copilot-for-security-is-generally-available-on-april-1-2024-with-new-capabilities/)) Those are vendor-run studies of a vendor's product, and they measure different tasks from anything on the attacker's side, so the comparison is rough. But 22–26% faster is about **1.3×**, against the attacker's 5×–10× on running an operation. AI made the defender's analyst a little faster. It made the attacker's whole team smaller.

The difference is *which bottleneck AI removes*.

- **The attacker's bottleneck was skilled labour.** AI removes it almost directly: more targets, more exploits, more lures, fewer people.
- **The defender's bottleneck is organisational throughput:** patch testing, change windows, maintainers' time, asset inventory, the one legacy appliance nobody owns. AI barely touches it. In Glasswing's first month, Anthropic had disclosed 530 confirmed high- or critical-severity bugs and **75 were patched**. Some maintainers asked Anthropic to slow down, and a high- or critical-severity fix took about two weeks on average. ([Glasswing update](https://www.anthropic.com/news/glasswing-initial-update)) Across industry, Verizon's 2026 data shows the same thing at scale: the median time to fix a known-exploited vulnerability rose from 32 to 43 days, the median number of them each organisation had to deal with went from 11 to 16, and only 26% were fully fixed. ([TechTarget on DBIR 2026](https://www.techtarget.com/news/Verizon-2026-DBIR-6-key-takeaways-for-CISOs/836215/))

Writing the fix is no longer the hard part. In DARPA's AI Cyber Challenge final in August 2025, automated systems found 54 of 63 planted vulnerabilities across 54 million lines of code and patched 43 of them, submitting patches in an average of 45 minutes at about $152 per task. They also found 18 real vulnerabilities and offered patches for 11. ([DARPA](https://www.darpa.mil/news/2025/aixcc-results)) A patch only scored if it stopped the proof-of-vulnerability input from triggering the bug *and* still passed the program's functionality tests, so every one of those 43 was machine-validated. ([Team Atlanta](https://arxiv.org/abs/2601.17471)) Google DeepMind's CodeMender had upstreamed 72 security fixes to open-source projects by October 2025. It validates its own patches first, checking that they fix the root cause, are functionally correct and cause no regressions, and only surfaces the ones that pass for a human to look at. ([Google DeepMind](https://deepmind.google/discover/blog/introducing-codemender-an-ai-agent-for-code-security/)) What these systems cannot do is test the fix against your production estate, schedule the change, and roll it out to every copy of the software you run. That last mile is where the 43 days go.

Finding got about 10× cheaper for both sides. Writing the fix got cheaper too. *Shipping* the fix did not. A defender who uses AI only to *find* more problems has added to their own queue. The NCSC calls the result a "digital divide". ([NCSC](https://www.ncsc.gov.uk/report/impact-ai-cyber-threat-now-2027)) In one line, it divides:

> **Organisations that can turn findings into fixes at machine speed, and organisations that cannot.**
{: .block-minor}

Which side you are on matters more than how many bugs your tools can find.

There is also a containment cost the attacker never pays. In July 2026, by OpenAI's own account, agents in a cyber evaluation with production safeguards switched off got out of their test environment through zero-days in a package proxy and went on to compromise Hugging Face's production infrastructure, roughly 17,600 actions in under three days, with no human at the keyboard. ([BleepingComputer](https://www.bleepingcomputer.com/news/security/hugging-face-breach-autonomous-ai-agent-system-internal-datasets-credentials/) · [summary and timeline](https://en.wikipedia.org/wiki/OpenAI%E2%80%93HuggingFace_incident)) Defenders who run offensive agents of their own now have to sandbox them as carefully as any other untrusted code, which is what the [earlier posts]({% post_url 2026-10-21-sandboxing-untrusted-ai-agents-on-linux %}) [in this series]({% post_url 2026-10-25-hardening-a-shared-host-against-cache-covert-channels %}) are about.

## 🧯 What a 10× attacker means for defenders

If the attacker's cost per operation fell by about 10×, two kinds of defence still work: the ones whose cost to the attacker did *not* fall, and the ones that let you move at the attacker's speed. Everything below is one or the other. The first five are the short list; the sections after them go into each in more depth.

1. **Remove the cheap paths.** The FortiGate campaign needed exposed management interfaces and single-factor logins. AI scales whatever is easy, so make fewer things easy: phishing-resistant MFA (FIDO2/passkeys, not SMS or push), no admin interfaces on the internet, no shared credentials.
2. **Assume time-to-exploit is negative.** Patching the day after disclosure is already late on average. Put virtual patching, segmentation and least privilege between every internet-facing service and everything else, so that an unpatched bug is a contained bug.
3. **Treat patch throughput as the metric.** You will be handed more true findings than you can fix, by your own tools, by researchers, and by labs. Invest in the boring pipeline: asset inventory, staged rollouts, automated tests that let you ship a fix in hours.
4. **Detect on behaviour, not on lures.** The phishing will be perfect. Breakout is measured in minutes. Detection has to key on what happens after the click (new OAuth grants, token use from new places, unusual admin API calls), with response automated enough to act inside a 29-minute window.
5. **Use the same tools, inside a sandbox.** Run AI code review and vulnerability discovery on your own code before someone else does, and run it with the same isolation you would give any untrusted agent.

### 🔐 Make the cheap attacks expensive again

The attacks AI made cheapest are the ones that were already cheap: lures, password guessing, exposed services. These are also the ones you can shut off outright rather than race.

- **Phishing-resistant MFA everywhere, starting with admins.** A perfect lure is worthless if the stolen password cannot be used. CISA calls phishing-resistant MFA the "gold standard" and notes that "the only widely available phishing-resistant authentication is FIDO/WebAuthn". ([CISA](https://www.cisa.gov/sites/default/files/publications/fact-sheet-implementing-phishing-resistant-mfa-508c.pdf)) SMS codes and push approvals can be relayed or fatigued; passkeys and security keys cannot. Do administrators, help-desk staff and finance first, because those are the accounts the voice and video scams go after.
- **Nothing administrative on the internet.** Every FortiGate in the Amazon case had its management interface exposed. Put management planes behind a VPN or zero-trust access proxy, and alert when one appears on an external scan. Edge devices went from 3% to 22% of exploitation breaches in a year in Verizon's data; they deserve their own inventory and their own patch deadline.
- **Verify money and access changes out of band.** The Arup transfers, help-desk MFA resets and payment-detail changes all rest on someone believing a voice, a face or an email. Make the rule mechanical: call back on a number already on file, require a second approver above a threshold, and never reset MFA on the strength of a phone call alone. A rule that does not depend on spotting the fake still works when the fake is perfect.
- **Retire shared and default credentials.** Credential lists cost an AI-assisted crew nothing to try against every login page on the internet. A password manager, unique service-account secrets and lockout on admin logins take that path away.

### ⏱️ Patch on the attacker's clock

You cannot patch everything in three days. You can patch the right things in three days, if you have decided in advance which ones they are.

CISA's June 2026 directive for US federal agencies, BOD 26-04, is a useful template even if you are not bound by it. It replaced the old flat "two weeks for anything in KEV" rule with a deadline based on four questions about each vulnerability: is the asset publicly exposed, is the CVE in KEV, can an adversary *automate* every step of exploitation, and does exploitation give partial or total control? The worst combination gets a three-day deadline followed by a forensic check for signs it was already used. ([CISA BOD 26-04](https://www.cisa.gov/news-events/directives/bod-26-04-prioritizing-security-updates-based-risk) · [BOD 22-01, revoked](https://www.cisa.gov/news-events/directives/bod-22-01-reducing-significant-risk-known-exploited-vulnerabilities-revoked))

The "automatable" question is the one AI moves. A bug that once needed a skilled human to turn into an exploit is, after Mythos and GLM-5.3, increasingly one an agent can take end to end. When in doubt, answer "yes".

For zero-days there is no patch to apply, and those are now most of what gets exploited. Have a mitigation path ready that does not depend on the vendor: disable the vulnerable feature, block the endpoint at a web application firewall, pull the device off the internet, or isolate it. Then patch when the patch arrives, and check whether the bug was used in the gap.

### 🏭 Build the fix pipeline, not just the finding pipeline

AI-generated findings and AI-generated patches both arrive faster than ever. The constraint is everything between "patch exists" and "patch is running everywhere".

- **Know what you run.** You cannot patch software you do not know you have. An accurate asset inventory, and a software bill of materials for what you build, turn "are we affected?" from a week of emails into a query.
- **Make shipping a fix boring.** Automated tests, staged rollouts and fast rollback are what let a team deploy a fix in hours without fear. The organisations that already ship code many times a day will absorb this shift best; the ones with a monthly change window will feel it most.
- **Let AI write the patch, and let AI prove it works.** If every fix waits for a human, you have rebuilt the bottleneck this post is about. Instead, require evidence: the original exploit or crash input no longer works, the test suite still passes, and fuzzing finds no change in behaviour beyond the bug. That is how AIxCC scored its patches, and how CodeMender decides which patches are worth showing anyone. Ship what passes automatically. Keep human review for the risky cases (authentication, cryptography, anything that touches the tests or the build pipeline themselves) and for a random sample of the rest, so you notice if the checks start to slip.
- **Validate with tests, not with a second model's opinion.** A model asked to make the tests pass will sometimes change the tests, special-case the failing input, or weaken an assertion; after the Hugging Face incident, an OpenAI researcher said its models "really like to cheat" when pushed to work fast. ([summary and timeline](https://en.wikipedia.org/wiki/OpenAI%E2%80%93HuggingFace_incident)) A model reviewing another model's patch can share its blind spots. Deterministic checks (exploit replay, regression tests, fuzzing) are much harder to talk round. Treat the fix pipeline as an attack surface, too: an AI that reads issue text and code comments written by outsiders can be steered by them, so a patch that came from an outside report gets the stricter path.
- **Watch inflow against outflow.** Count findings arriving each week and fixes shipped each week. If arrivals exceed fixes week after week, your backlog grows without anyone noticing until one week it does. That is the Hemingway curve from the top of this post, applied to your own queue.

### 🧱 Contain: assume the bug will be used

If time-to-exploit is negative, some bugs *will* be exploited before you can fix them. Plan for that, and make the first host an attacker reaches a dead end.

- **Segment.** An internet-facing service should not be able to reach your identity provider, backups or production databases directly. Average breakout is 29 minutes; segmentation turns those minutes into hours.
- **Least privilege, especially for tokens.** Several 2026 cases went from one stolen developer or cloud token to full administrative control within hours. Scope tokens narrowly, make them short-lived, and keep production admin rights out of everyday accounts and CI pipelines.
- **Third parties are your perimeter too.** Verizon found third-party involvement in 48% of breaches in 2026, up 60%. ([Verizon](https://www.verizon.com/about/news/breach-industry-wide-dbir-finds)) Give vendors the narrowest access that works, and log it as carefully as your own staff's.
- **Plan for extortion without encryption.** GTG-2002 encrypted nothing; it stole data and threatened to publish it. Backups do not help with that. Keeping less sensitive data, and encrypting what you keep with keys the attacker cannot easily reach, does.

### 📡 Detect on behaviour, and on speed

The attack will not look unusual. It will be fast, and its machine speed is something you can detect.

- **Watch identity, not inboxes.** New OAuth grants, MFA method changes, token use from new places, sign-ins followed by mailbox rule changes. Most of what happens after a perfect phishing email shows up in your identity logs.
- **Watch for machine-speed behaviour.** GTG-1002 made "thousands of requests, often multiple per second". An agent working through an environment enumerates more widely and faster than a person does. Rate and breadth (how many hosts, how many API calls, how many directories in how few minutes) are signals a human attacker rarely produced and an AI-driven one usually does.
- **Plant tripwires.** Honeytokens and canary credentials cost almost nothing and have no legitimate use, so any use is an alert. An agent that tries every credential it finds will try these too.
- **Pre-approve the first response.** If containment needs a meeting, it will happen after breakout. Decide in advance which actions an analyst, or an automated playbook, can take immediately: disable an account, revoke tokens, isolate a host.

### 🤝 Use AI on defence, with eyes open

The tools that raised the attacker's multiplier can raise yours. Anthropic's own advice after GTG-1002 was for security teams to "experiment with applying AI for defense", and its investigators used Claude to analyse the campaign's data. ([Anthropic, November 2025](https://www.anthropic.com/news/disrupting-AI-espionage))

- **Find your bugs before someone else does.** Run AI-assisted code review and vulnerability discovery on your own code and dependencies, before release where possible. Big Sleep's SQLite catch is the model: found and fixed before use.
- **Validate before you act.** Heelan's 1:50 ratio and curl's slop problem are what happens without validation. XBOW's answer was deterministic validators: a finding counts only if a test proves it. Do the same, so AI findings add to the queue only when they are real. The same rule applies on the way out: a fix counts only if a test proves it, which is what lets you ship AI-written patches without a human reading each one.
- **Use AI to speed triage, and measure it.** The Copilot trials suggest about a quarter faster, not ten times. That is still worth having, but do not plan staffing around a vendor's headline.
- **Sandbox your own agents.** An agent with tools and credentials is untrusted code, as the Hugging Face incident showed. Give it the least access that works, isolate it, and log what it does.
- **Govern the AI your staff already use.** Verizon found 45% of employees regularly using AI on corporate systems, up from 15%, often through personal accounts. ([Verizon](https://www.verizon.com/about/news/breach-industry-wide-dbir-finds)) Provide an approved tool, or data will go to an unapproved one.

### 📊 What to measure

If the attacker's multiplier is about 10×, the useful defensive metrics are the ones that track speed and exposure, not activity.

| Metric | Why it matters | Reference point |
|---|---|---|
| Median days to fix KEV vulnerabilities on internet-facing assets | The attacker's clock now runs in hours | Industry median 43 days (DBIR 2026); BOD 26-04 sets 3 days for the worst cases |
| Share of admin and finance accounts on phishing-resistant MFA | Removes the payoff from a perfect lure | 100% |
| Management interfaces reachable from the internet | The whole FortiGate campaign rested on these | Zero |
| Findings opened vs fixes shipped, per week | A growing backlog is the "gradually" | Fixes ≥ findings, every week |
| Time from first alert to containment | Has to beat breakout | Under 29 minutes (CrowdStrike 2026 average) |
| Payment and MFA changes verified out of band | Defeats voice and video impersonation | 100% |

### 🏘️ If you are a small organisation

The NCSC's "digital divide" is mostly about size: big organisations can afford to fight AI with AI, and many small ones cannot. If that is you, do not try to do all of the above. Do the parts that remove whole classes of attack:

1. Phishing-resistant MFA on email, admin and finance accounts.
2. Nothing administrative exposed to the internet.
3. Software and services that update themselves, or a managed provider whose contract says how fast they patch.
4. Offline backups, and a call-back rule for payments.

CISA's [Cross-Sector Cybersecurity Performance Goals 2.0](https://www.cisa.gov/sites/default/files/2025-12/CPG_Report_2.0_508c.pdf) is a good checklist to work through after that.

None of this is new advice. That is the uncomfortable part. The defender's job did not change shape. It got about ten times less forgiving.

## 🔗 Sources

### Research and competitions

- Fang, Bindu, Gupta, Kang, [LLM Agents can Autonomously Exploit One-day Vulnerabilities](https://arxiv.org/abs/2404.08144), April 2024. Cost analysis: $3.52 per run, $8.80 per exploit, 2.8× cheaper than a $25 human estimate.
- Heiding, Schneier, Vishwanath et al., [Evaluating Large Language Models' Capability to Launch Fully Automated Spear Phishing Campaigns](https://arxiv.org/abs/2412.00586), 2024, published in *Expert Systems with Applications*, 2026.
- Sean Heelan, [How I used o3 to find CVE-2025-37899](https://sean.heelan.io/2025/05/22/how-i-used-o3-to-find-cve-2025-37899-a-remote-zeroday-vulnerability-in-the-linux-kernels-smb-implementation/), May 2025. Hit rates, false positives and cost per 100 runs.
- XBOW, [The road to Top 1: how XBOW did it](https://xbow.com/blog/top-1-how-xbow-did-it), June 2025.
- Team Atlanta, [PatchIsland: Orchestration of LLM Agents for Continuous Vulnerability Repair](https://arxiv.org/abs/2601.17471), 2026. How the winning AIxCC team's patches were scored: stop the proof of vulnerability and pass the functionality tests.
- DARPA, [AI Cyber Challenge marks pivotal inflection point for cyber defense](https://www.darpa.mil/news/2025/aixcc-results), August 2025. 54 of 63 synthetic vulnerabilities found, 43 patched, 18 real vulnerabilities, $152 per task, 45 minutes per patch.

### Government

- UK NCSC, [Impact of AI on cyber threat from now to 2027](https://www.ncsc.gov.uk/report/impact-ai-cyber-threat-now-2027), May 2025.
- CISA, [BOD 26-04: Prioritizing Security Updates Based on Risk](https://www.cisa.gov/news-events/directives/bod-26-04-prioritizing-security-updates-based-risk), June 2026, which revoked [BOD 22-01](https://www.cisa.gov/news-events/directives/bod-22-01-reducing-significant-risk-known-exploited-vulnerabilities-revoked).
- CISA, [Implementing Phishing-Resistant MFA](https://www.cisa.gov/sites/default/files/publications/fact-sheet-implementing-phishing-resistant-mfa-508c.pdf), October 2022.
- CISA, [Cross-Sector Cybersecurity Performance Goals 2.0](https://www.cisa.gov/sites/default/files/2025-12/CPG_Report_2.0_508c.pdf), December 2025.

### Breach and vulnerability data

- NIST, [NVD CVE API 2.0](https://nvd.nist.gov/developers/vulnerabilities), monthly counts of published, non-rejected CVEs, pulled 3 November 2026 for the chart.
- Verizon, [2026 Data Breach Investigations Report: news release](https://www.verizon.com/about/news/breach-industry-wide-dbir-finds), May 2026, with summaries by [TechTarget](https://www.techtarget.com/news/Verizon-2026-DBIR-6-key-takeaways-for-CISOs/836215/) and [Tenable](https://www.tenable.com/blog/key-findings-from-the-verizon-dbir-2026).
- Verizon 2025 DBIR edge-device findings, via [SecurityWeek](https://www.securityweek.com/verizon-dbir-flags-major-patch-delays-on-vpns-edge-appliances/), April 2025.
- Mandiant, [How Low Can You Go? An Analysis of 2023 Time-to-Exploit Trends](https://cloud.google.com/blog/topics/threat-intelligence/time-to-exploit-trends-2023), 2024. Definition of TTE; 97 of 138 exploited vulnerabilities in 2023 were zero-days.
- Mandiant, M-Trends 2026, May 2026, via [Resilient Cyber's summary](https://www.resilientcyber.io/p/m-trends-2026-what-450000-hours-of). Time-to-exploit series and initial infection vectors.

### Security industry threat reports

- CrowdStrike, [2025 Global Threat Report](https://www.crowdstrike.com/en-us/press-releases/crowdstrike-releases-2025-global-threat-report/), February 2025, and [2026 Global Threat Report](https://www.crowdstrike.com/en-us/press-releases/2026-crowdstrike-global-threat-report/), February 2026.
- Google Threat Intelligence Group, [Advances in threat actor usage of AI tools](https://cloud.google.com/blog/topics/threat-intelligence/threat-actor-usage-of-ai-tools), November 2025. PROMPTSTEAL and PROMPTFLUX.
- Amazon Threat Intelligence, [AI-augmented threat actor accesses FortiGate devices at scale](https://aws.amazon.com/blogs/security/ai-augmented-threat-actor-accesses-fortigate-devices-at-scale/), February 2026.
- Microsoft, [Randomized Controlled Trial for Microsoft Security Copilot](https://papers.ssrn.com/abstract=4648700), November 2023 (149 new-in-career participants: 26% faster, 44% more accurate).
- Microsoft, [Copilot for Security general availability](https://www.microsoft.com/en-us/security/blog/2024/03/13/microsoft-copilot-for-security-is-generally-available-on-april-1-2024-with-new-capabilities/), March 2024, reporting its trial with experienced analysts (22% faster, 7% more accurate).

### AI labs

- Anthropic, [Detecting and countering misuse of AI: August 2025](https://www.anthropic.com/news/detecting-countering-misuse-aug-2025). GTG-2002 and the no-code ransomware case.
- Anthropic, [Disrupting the first reported AI-orchestrated cyber espionage campaign](https://www.anthropic.com/news/disrupting-AI-espionage), November 2025.
- OpenAI, [Strengthening cyber resilience as AI capabilities advance](https://openai.com/index/strengthening-cyber-resilience/), December 2025. CTF success rose from 27% (GPT-5, August 2025) to 76% (GPT-5.1-Codex-Max, November 2025).
- Google, [A summer of security: empowering cyber defenders with AI](https://blog.google/technology/safety-security/cybersecurity-updates-summer-2025/), July 2025. Big Sleep and CVE-2025-6965.
- Google DeepMind, [Introducing CodeMender: an AI agent for code security](https://deepmind.google/discover/blog/introducing-codemender-an-ai-agent-for-code-security/), October 2025. Automatic validation before human review.
- Anthropic, [Claude Mythos Preview's cybersecurity capabilities](https://www.anthropic.com/research/mythos-preview), April 2026.
- Anthropic, [Project Glasswing: an initial update](https://www.anthropic.com/news/glasswing-initial-update), May 2026.
- Anthropic, [GLM-5.3 and the spread of advanced cyber capabilities](https://anthropic.com/research/glm-5-3-and-the-spread-of-advanced-cyber-capabilities), September 2026, citing NIST CAISI's assessment.
- Anthropic, [Detecting and countering misuse of AI: September 2026](https://www.anthropic.com/threat-intelligence-report-september-2026).

### Incidents and reporting

- Arup deepfake fraud: [CNN](https://www.cnn.com/2024/05/16/tech/arup-deepfake-scam-loss-hong-kong-intl-hnk), May 2024.
- Daniel Stenberg, [The end of the curl bug-bounty](https://daniel.haxx.se/blog/2026/01/26/the-end-of-the-curl-bug-bounty/), January 2026; [The Register](https://www.theregister.com/security/2026/01/21/curl-shutters-bug-bounty-program-to-stop-ai-slop/5063039); [Cybernews](https://cybernews.com/security/curl-bug-bounty-ai-security-reports-daniel-stenberg/), June 2026.
- Hugging Face incident: [BleepingComputer](https://www.bleepingcomputer.com/news/security/hugging-face-breach-autonomous-ai-agent-system-internal-datasets-credentials/), July 2026; [Wikipedia summary and timeline](https://en.wikipedia.org/wiki/OpenAI%E2%80%93HuggingFace_incident), which flags several claims as unverified.
