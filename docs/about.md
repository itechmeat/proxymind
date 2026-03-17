# ProxyMind

Self-hosted open-source digital twin — an AI agent that knows, thinks, and communicates like its prototype.

## The Problem

Influencers, scientists, book authors, public figures — they cannot physically respond to everyone. Their knowledge is scattered across books, articles, podcasts, videos, and social media posts. The audience wants an answer specifically from this person, but access is limited.

Existing solutions do not address this:

- **Generic chatbots** — uncontrollable, hallucinate, do not convey personality.
- **FAQ bots** — primitive, cannot hold a dialogue, do not understand context.
- **Cloud AI builders** (Custom GPT, Character.ai) — data goes to third-party servers, the owner controls neither the knowledge, nor the behavior, nor the infrastructure.

There is no solution that simultaneously: accurately conveys the personality, responds strictly based on the prototype's knowledge, belongs to the owner, and exists as an autonomous agent in an open ecosystem.

## What ProxyMind Is

ProxyMind is a self-hosted AI agent that serves as the digital twin of a specific person or character. One installation — one twin.

The twin has three dimensions:

- **Knowledge** — a versioned knowledge base assembled from the prototype's books, articles, podcasts, posts, videos, and other materials.
- **Character** — speech style, tone, manner of communication, values.
- **Behavior** — reactions to specific topics, discussion boundaries, dialogue style: whether it asks follow-up questions, jokes, deflects, or answers directly.

The twin relies on a **published knowledge base** as its primary source of answers. It can discuss adjacent topics loosely related to its knowledge but does not stray far beyond those boundaries. If the knowledge base has no answer — the twin honestly says so rather than making things up.

## What ProxyMind Is Not

- **Not a chatbot with a prompt.** The twin has a full personality configuration through a set of files, not a single system prompt string.
- **Not "knows everything".** The twin relies on a published knowledge scope. It can discuss adjacent topics but does not stray far beyond its knowledge boundaries.
- **Not a cloud service.** Fully self-hosted. Data, knowledge, and configuration belong to the owner.
- **Not a platform for multiple agents.** One instance — one twin. Each new twin requires a separate installation.

## Knowledge Sources

The twin builds its knowledge base from the prototype's materials:

- Books and publications
- Articles, blogs, website pages
- Social media posts (Telegram, X, etc.)
- Podcasts and audio transcripts
- YouTube video transcripts
- FAQs, interviews, structured data

All sources go through an ingestion pipeline: parsing, chunking, indexing. Knowledge is versioned — the agent responds based on a **published snapshot**, not everything ever uploaded. This provides:

- Predictable responses.
- Ability to test a draft before publishing.
- Rollback to a previous version.
- Audit and reproducibility.

The twin **references the prototype's materials** in responses. For online sources — clickable links (to a video, post, store). For offline sources — textual references (book title, chapter, page). References can appear inline within the response text or in a collapsible block below the message (similar to Perplexity). Citations are not in every message but where they are appropriate and strengthen the response.

## Commercial Component

The twin can recommend products and services related to its prototype:

- **Books and publications** — quotes a fragment and provides a link to the store where the book is sold.
- **Events** — offers tickets to the prototype's concert, lecture, or conference.
- **Courses, merch, subscriptions** — any products and services tied to the prototype.

Recommendations are delivered **natively** — not as an advertising banner but as a natural suggestion within the conversation context. The twin recommends the way a real person would: mentions their book when the topic calls for it, or invites to a concert if the conversation partner is interested in music.

Sales priorities change over time — the twin's owner manages them through a separate configuration file. Before a concert, tickets are promoted more actively; after — they stop. Products are not necessarily tied to the knowledge base and exist outside the knowledge scope.

## Twin Personality

Personality is defined through a set of configuration files (similar to OpenClaw):

Base set (v1):

- **Identity** (IDENTITY.md) — who this twin is, their role, background.
- **Character** (SOUL.md) — speech style, tone, values.
- **Behavior** (BEHAVIOR.md) — reactions to topics, discussion boundaries, dialogue style.

Extended model (future versions):

- **Tools** — what the twin can do beyond answering questions.
- Additional configuration files (TOOLS.md, HEARTBEAT.md, etc.).

This is not a single system prompt string but a structured personality description that can evolve and be versioned alongside the knowledge base.

## How It Is Used

The primary scenario is a chat on a website or in an application. A visitor communicates with the twin through a web interface, receiving responses on behalf of the prototype with references to their materials.

In later stages, the twin can also operate through external messaging and social platforms via **channel connectors** (for example Telegram, Facebook, VK, Instagram, TikTok, and similar channels). In that model, the visitor chats in the native channel instead of registering in a separate ProxyMind UI. The system identifies the visitor through the platform-provided identity and maps it to an internal visitor record and session context.

Installation and setup are performed by a technical specialist — for themselves or as a service. The twin's owner (or their representative) uploads materials, configures the personality, and publishes the knowledge base.

## Compatibility with Agent Ecosystems

ProxyMind does not exist in isolation. The twin is a full-fledged agent compatible with open protocols:

- **A2A (Agent-to-Agent)** — external interface. The twin publishes an Agent Card, accepts tasks from other agents, participates in inter-agent interactions, and can exist on agent marketplaces.
- **MCP (Model Context Protocol)** — internal interface. Standardized access to the twin's tools, data sources, and internal capabilities.

A2A on the outside, MCP on the inside.

The initial focus is a chat-first digital twin. A2A and MCP are built into the architecture from the start to avoid rebuilding the foundation, but are implemented in later stages.

## Key Properties

- **Open-source** — fully open code.
- **Self-hosted** — data and infrastructure belong to the owner.
- **One instance = one twin** — clean isolation of personality and knowledge.
- **Managed knowledge** — versioning, snapshots, publishing.
- **Source references** — citations, inline links, and a collapsible block with relevant materials.
- **Configurable personality** — character and behavior through files.
- **A2A/MCP compatibility** — the twin as an agent in an open ecosystem.
- **LLM provider independence** — the reasoning model can be from any provider; embeddings are tied to the chosen embedding provider.
- **Multilingual** — all language-dependent components (search, stemming, tokenization) are configurable for any widely-used language.
