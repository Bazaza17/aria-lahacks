# Tracks and prizes — and how Aria could fit

> Pulled Sat Oct 17, ~2 AM from live.lahacks.com/tracks and each sponsor's linked brief. "Not posted" means the brief didn't list it, so ask at the booth.
> **Fit** is a quick read on how naturally Aria maps to each track. Nothing here is a decision; see `01-decisions.md`.
> The MLH prizes in the older event notes came from mlh.com. The event's own MLH doc lists different items, and that's what's below. Confirm at the opening ceremony.

Fit key: **Strong** = Aria fits as is · **Add-on** = small layer on top of whatever gets built · **Possible** = real extra work · **Weak** = forced · **Conflict** = a rule blocks it

## Quick read

- **Strong:** Applied Intelligence, Agentverse, Fetch.ai challenge
- **Add-on:** Sentry, StepFun, Gemini, ElevenLabs, GoDaddy, Vultr
- **Possible:** Model Learning, Beyond the Digital, Paper, Photon, Devin, Browser Use, veri.studio, Solana, Commit Fellowship (now that you're a team)
- **Weak:** Base44, Workday, QNX, Espressif, Tiger Data, Visa, Intuit, Snowflake
- **Conflict:** Even Realities (bans emergency-routing apps), Creao (its own agent must do the core work)

## By recruiting benefits and cash

Lincoln's preference: challenges with recruiting benefits and good cash prizes.

| Track | Recruiting | Cash | Fit |
|---|---|---|---|
| Fetch.ai | Internship interview for each top-3 team | $1,500 / $1,000 / $500 | Strong |
| Sentry (entered) | Guaranteed internship/new-grad interview per member | — | Add-on |
| Photon | Fast-track to the final interview round (iMessage winner) | $400 iMessage, $300 voice, plus credits | Possible |
| Creao | Interview opportunities for winning teams | $2,000 / $1,000 / $500 | Conflict |
| Commit Fellowship (MLH) | Interview for a 3-week founder sprint (Nov 2–20) | — | Possible |
| Paper | — | $1,500 / $1,000 / $500 | Possible |
| Visa | — | $2,000 | Weak |
| Base44 | — | $1,500 / $500 | Weak |
| QNX | — | $1,000 / $250 / $250 | Weak |

Workday offers a meeting with its Developer Relations team, not an interview.

## Main tracks (a submission goes under one)

| Track | Prize | What it needs | How it's judged | How Aria could fit | Fit |
|---|---|---|---|---|---|
| **Applied Intelligence** | LA Hacks prizes TBD | AI applied to a real-world problem (automation, accessibility, health, any meaningful use) | LA Hacks rubric: Technical Depth · Product Thinking & Impact · Execution & Polish · Originality | Pre-incident planning for responders: scan + floor plan → world model → fire/flood → routes and crowd sim → size-up | Strong |
| **Agentverse (Fetch.ai)** | TBD (Fetch's cash prize is a separate challenge, below) | Agents on Agentverse, found through ASI:One, turning intent into a real outcome | Same as the Fetch challenge | The same agent build | Strong |
| **Model Learning** | TBD | Systems that learn from data: patterns, predictions | A model that clearly learns, with numbers showing it works | A) Surrogate model trained on many sim runs that predicts clearance time and bottleneck exits instantly, with its error vs. the full sim<br>B) Earthquake damage model that predicts which exits fail from building features | Possible |
| **Beyond the Digital** | TBD | AI in the physical world: hardware, embedded, AR/VR, new interfaces | A physical-world experience judges can try | A) A real LiDAR scan of the venue as the world model<br>B) WebXR view of routes over the scan | Possible |

## Company challenges

| Track | Prize | What it needs | How it's judged | How Aria could fit | Fit |
|---|---|---|---|---|---|
| **Fetch.ai: ASI:One Agent Challenge** | 🥇 $1,500 · 🥈 $1,000 · 🥉 $500, each + internship interview | ≥1 agent on Agentverse · Agent Chat Protocol · usable in ASI:One · real tools or multi-agent · whole main workflow inside an ASI:One chat · public repo + run steps · README with agent names, addresses and both badges · Submission Agent · shared chat URL · profile URLs · 3–5 min video | Functionality 25 · Fetch tech 20 · Innovation 20 · Impact 20 · UX 15. Bonus: multi-agent, Payment Protocol, Interactive Cards, error recovery, real-time data, keeps running after | A) Orchestrator + world-model, hazard, evac-sim and report agents<br>B) Live data: USGS quakes, NWS alerts, FEMA flood zones<br>C) Report as an Interactive Card<br>D) Payment Protocol pay-per-preplan | Strong |
| **Paper: Best Designed Hack** | 🥇 $1,500 · 🥈 $1,000 · 🥉 $500 | Best-designed interface (Paper isn't stated as required; free Paper Pro month offered) | Hierarchy, legibility, consistency, contrast · ease of use · personal craft that doesn't look AI-generated | A) New web viewer: scan + sim playback + size-up card, designed in Paper first<br>B) Phone-first one-glance report for a captain in the truck | Possible |
| **Photon: Messaging/Calling Agent** | iMessage: $400 + $300 credits (+ interview fast-track) · runner-up $200 + $100 credits · Best Voice: $300 + $100 credits | Built on the Photon 2.0 beta (free), live on ≥1 channel; voice runs on an SMS number | Vision · Craft · Depth (real-world edge cases) · Traction; human in the loop, safety fallbacks | A) Text an address, get the size-up + viewer link<br>B) Call Aria on the way in for a spoken size-up (pairs with ElevenLabs)<br>C) Aria joins a crew's group thread with updates | Possible |
| **Cognition: Best Use of Devin** | $5,000 in Devin credits (1 winner); free credits for every team | Build with Devin | Creativity · novelty · polish | Give Devin self-contained work (real data tools, viewer overlays, deploy) through GitHub pull requests | Possible |
| **Sentry: Best Use of Sentry** | Guaranteed internship/new-grad interview per member | ≥2 Sentry products beyond error monitoring: Session Replay, Logs, Tracing, Profiling, Uptime Monitoring, MCP/AI agent monitoring | How observability shaped what you built, shown with real moments: a slow call found in a trace, a broken flow caught in a replay, a bug your logs pointed to. Those moments have to happen during the build, so Sentry goes in at the start, not at the end | A) API and agents: Tracing + AI agent monitoring (Sentry's Anthropic integration records each Claude call, its tools and tokens) + Logs on the sim<br>B) Web viewer: Session Replay + Tracing<br>C) Uptime Monitoring on the agents' health endpoint | Add-on (set up at the start) |
| **StepFun: Step 5 Preview** | Not posted | App must call `step-5-preview` at runtime; explain each model's role | Task completion · reliability · user understands and controls the flow | A) Read the floor plan image into the graph<br>B) Write the report | Add-on |
| **Browser Use** | Not posted | An agent built with Browser Use that acts on the web | Working demo for a real audience | Records agent that pulls year built, construction and occupancy from county assessor and permit sites | Possible |
| **Creao AI** | Disruptor $2,000 · One-Person Company $1,000 · Team Empowerment $500 (+ Launchpad) | A Creao agent (agent.creao.ai) does the core work; README run link + agent ID | AI as foundation 30 · depth on Creao 25 · originality 20 · track fit 15 · demo 10 | Rebuild the specialists as a Creao "org chart"; the core would then run on Creao instead of Fetch | Conflict |
| **Base44** | 🥇 $1,500 · runner-up $500 | Built substantially on Base44; live Base44 app | Real problem + user, working product, learning shown, growth potential | A responder web app on Base44 that calls the agents | Weak |
| **Even Realities: G2 glasses** | 🥇 G2 per member · 🥈 $250 OpenAI card each · 🥉 $100 each | Even Hub app on G2, Beta upload, name ≤20 chars without "Even", runs on a real G2 at judging | Made for G2 · Quiet by Design · Originality · Polish · Execution | The brief bans emergency-routing apps, which is what Aria on G2 would be | Conflict |
| **Visa: Future of Shopping** | $2,000 | GenAI shopping experience with secure payments | Innovation 25 · UX 25 · Technical 20 · Commerce 15 · Trust 15 | No natural fit | Weak |
| **Workday: Future of Work** | Not in the brief (+ Workday DevRel meeting) | Agent that helps people succeed after joining a company | Agentic logic 30 · new-hire relevance 20 · responsible AI 20 · future of work 15 · UX 10 · pitch 5 | Onboarding new firefighters to a district's buildings | Weak |
| **Intuit QuickBooks** | $200 / $100 / $50 gift card per person | System One approach on the provided accounting data; beat baselines | Technical unlock + customer value + real evaluation | No natural fit | Weak |
| **QNX** | 🥇 $1,000 · two $250 runners-up | QNX OS + an AI module from oss.qnx.com | Not posted | Run the sim on a QNX box as an on-site controller (needs hardware) | Weak |
| **Espressif** | Hardware (ESP-VoCat, M5Stack Stopwatch) | Espressif hardware | Creative, meaningful use | ESP32 smoke/water sensor feeding the sim (needs a board) | Weak |
| **veri.studio** | Not posted (GPU credits) | Post-train or fine-tune a model on Veri; show before/after | Size of improvement + demo | Fine-tune a small model to read floor plans into graph JSON | Possible |

## MLH challenges (per the event's MLH doc)

| Track | Prize | What it needs | How it's judged | How Aria could fit | Fit |
|---|---|---|---|---|---|
| **Gemini API** | Google swag kit | Build with the Gemini API | Not posted | A) Read the floor plan into rooms, doors, exits<br>B) Write the size-up | Add-on |
| **ElevenLabs** | Wireless earbuds | An audio experience built with ElevenLabs | Not posted | Spoken size-up (audio in chat, or a Photon call) | Add-on |
| **GoDaddy Registry domain** | Digital gift card | Register your domain through GoDaddy Registry (code from MLH) | Not posted | A domain for the viewer | Add-on |
| **Solana** | Ledger Nano S Plus | Innovate with Solana | Not posted | A) Write each pre-plan's hash to devnet as a tamper-proof record for insurers and inspectors<br>B) Settle pay-per-preplan in devnet USDC | Possible |
| **Vultr** | Portable screens | Use Vultr cloud (free credits) | Not posted | Host the agents on a Vultr VM so they stay up after the event | Add-on |
| **Tiger Data** | Stream Deck Mini | Tiger Data powers the project | Most innovative, impactful, performance-driven use | Store each sim tick as time-series for replay and stats | Weak |
| **Snowflake API** | Raspberry Pi 4 | Snowflake REST LLM API | Not posted | No natural fit | Weak |
| **Commit Fellowship** | Interview for the 3-week founder sprint (Nov 2–20) + *The Lean Startup* | Working prototype built with a team; opt in at submission; supplemental form | Picked after the event | Aria as the team's prototype (you're a team of 3 now) | Possible |
| **DEV Writing Challenge** | $100 | Post on DEV this month with #mlhacks | Substance, originality, story, popularity | A write-up after the event | After the event |

## Rules that cut across everything

- Pre-existing code must be open source. State exactly what was built at the event; judges score only that.
- Submissions are due Sun 12:00 PM. Be in Collins Conference Room for judging at 12:30.
- Opt into every prize the project qualifies for on Devpost.
