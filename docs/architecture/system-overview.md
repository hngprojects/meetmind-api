# System Architecture Overview

High-level architecture of the MeetMind platform — an intelligent meeting agent that listens, decides relevance, and captures knowledge passively.

```mermaid
---
config:
  layout: dagre
---
flowchart TD

    %% ─── PLATFORMS ────────────────────────────
    subgraph PLATFORMS["① Meeting Platforms (External Sources)"]
        GMEET["1️⃣ Google Meet
MVP target"]
        ZOOM["2️⃣ Zoom
MVP target"]
        CUSTOM["3️⃣ Custom App
via SDK adapter"]
    end

    %% ─── SDK LAYER ────────────────────────────
    subgraph SDK["② SDK Layer — Python API"]
        direction TB
        ADAPTER["⬤ Entry Point
Platform Adapter
Normalises message format"]
        API_IN["process_message()
REST endpoint"]
        API_RESP["should_respond()
REST endpoint"]
        API_SUM["get_summary()
REST endpoint"]
    end

    %% ─── AGENT CORE ────────────────────────────
    subgraph AGENT["③ MeetMind Agent Core"]
        CTX["Context Listener
Rolling 20–50 msg window"]
        REL["Relevance Engine
YES / NO · score · reason"]
        THRESHOLD{"Above
threshold?"}
        IGNORE["Ignore message"]
        RESP["Controlled Response
Generate + send reply"]
        DB_AGENT[("State Store
Session + Relevance Data")]
    end

    %% ─── KNOWLEDGE LAYER ───────────────────────
    subgraph KNOWLEDGE["④ Knowledge Layer — Passive Intelligence"]
        direction LR
        NOTE["Note Capture
Decisions · actions · points"]
        QUERY["Query Engine
NL post-session queries"]
        EXPORT["Export
Markdown · JSON · clipboard"]
        DB_KNOW[("Knowledge DB
Semantic · Notes · Actions")]
    end

    %% ─── CONSUMERS ─────────────────────────────
    subgraph CONSUMERS["⑤ Consumers / Outputs"]
        direction LR
        TEAMS["Remote Teams
End users"]
        DEVS["Developers
Python SDK"]
        STARTUPS["Startups
Embed via REST"]
    end

    %% ─── FLOWS ─────────────────────────────────
    GMEET -->|"raw message"| ADAPTER
    ZOOM -->|"raw message"| ADAPTER
    CUSTOM -->|"raw message"| ADAPTER

    ADAPTER --> API_IN
    ADAPTER --> API_RESP

    API_IN -->|"normalised message"| CTX
    CTX -->|"context snapshot"| REL
    REL --> THRESHOLD
    THRESHOLD -->|"NO"| IGNORE
    THRESHOLD -->|"YES"| RESP

    RESP -->|"reply"| API_RESP
    API_RESP -->|"post message"| GMEET
    API_RESP -->|"post message"| ZOOM
    API_RESP -->|"post message"| CUSTOM

    CTX -.->|"parallel"| NOTE
    NOTE --> QUERY
    QUERY --> EXPORT
    QUERY --> API_SUM

    EXPORT --> TEAMS
    API_SUM --> DEVS
    API_SUM --> STARTUPS

    %% Data & storage connections
    REL --> DB_AGENT
    NOTE --> DB_KNOW
    QUERY --> DB_KNOW

    %% ─── STYLES ────────────────────────────────
    classDef platform fill:#eef2ff,stroke:#818cf8,color:#1e1b4b,stroke-width:1px
    classDef sdk fill:#ecfeff,stroke:#06b6d4,color:#083344,stroke-width:1px
    classDef entry fill:#fef9c3,stroke:#f59e0b,color:#78350f,stroke-width:2px
    classDef agent fill:#f5f3ff,stroke:#a78bfa,color:#1e1b4b,stroke-width:1px
    classDef knowledge fill:#f0fdf4,stroke:#4ade80,color:#064e3b,stroke-width:1px
    classDef consumer fill:#fff7ed,stroke:#fb923c,color:#431407,stroke-width:1px
    classDef db fill:#f0f9ff,stroke:#38bdf8,color:#0c4a6e,stroke-dasharray: 3 2

    class GMEET,ZOOM,CUSTOM platform
    class ADAPTER entry
    class API_IN,API_RESP,API_SUM sdk
    class CTX,REL,IGNORE,RESP,DB_AGENT agent
    class NOTE,QUERY,EXPORT,DB_KNOW knowledge
    class TEAMS,DEVS,STARTUPS consumer
    class THRESHOLD decision
    class DB_AGENT,DB_KNOW db
```

## Layer Summary

| Layer | Responsibility |
|-------|----------------|
| ① Platforms | External meeting sources (Google Meet, Zoom, custom apps) |
| ② SDK Layer | Python API that normalises messages and exposes REST endpoints |
| ③ Agent Core | Context window management, relevance scoring, controlled responses |
| ④ Knowledge Layer | Passive note capture, NL query engine, export capabilities |
| ⑤ Consumers | End users, developers (SDK), and startups (REST embed) |
