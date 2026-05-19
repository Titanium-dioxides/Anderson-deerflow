import re

# 1. Fix rethlas_exploration_trajectory
with open('rethlas_exploration_trajectory.mermaid.md', 'w') as f:
    f.write('''```mermaid
flowchart LR
    BS["Broad Search"] --> FS["Focused Search"]
    FS --> AP["Attack Plan"]
    AP --> GN["Generation"]

    GN --> PA["Plan A Attempt"]
    GN --> PB["Plan B Attempt"]
    GN --> PC["Plan C Attempt"]

    PA --> PD["Plan D Formulation"]
    PB --> PD
    PC --> PD

    PD --> PC2["Proof Completion"]

    PC2 --> NV["Natural Language Verification"]

    NV --> F["Failure"]
    NV --> S["Success"]
```''')

# 2. Fix whole_pipeline - add "formal agent" / "informal agent" labels
with open('whole_pipeline.mermaid.md', 'w') as f:
    f.write('''```mermaid
flowchart TD
    subgraph Rethlas["Rethlas — informal agent"]
        direction TB
        GA["Generation Agent<br/>Propose Candidate Proofs"] --> VA["Verification Agent<br/>Verify Candidate Proofs"]
        VA -. "call" .-> GA
        GA -.->|"call"| RT["Tools"]
        VA -.->|"call"| RT
        RT --> MAT["Matlas<br/>Theorem Retrieval"]
        RT --> WS["Web Search<br/>Reference Lookup"]
        RT --> MM["Memory Manager<br/>Reading & Logging"]
        SK["Skills"] --> SK1["Construct examples"]
        SK --> SK2["Construct counterexamples"]
        SK --> SK3["Propose subgoal<br/>decomposition plans"]
        SK --> SK4["Identify key failures"]
    end

    Rethlas -->|"Candidate Informal Proof"| Archon

    subgraph Archon["Archon — formal agent"]
        direction TB
        subgraph A_Scaffolding["Scaffolding"]
            RS["(Re)Write Formal Sketch<br/>split files & theorems"] --> AC{"compile &<br/>semantics"}
        end
        AC -->|no| RS
        AC -->|yes| A_Proving["Proving"]
        subgraph A_Proving["Proving"]
            FZ["Formalize<br/>generate & fix proof"] --> OK{"0 sorry &<br/>compiles"}
            OK -->|no| ST["Strategies"]
            OK -->|yes| FC["Final Checks"]
            ST --> S1["① Ask Informal Agent (Detailing)<br/>for more detailed proof steps"]
            ST --> S2["② Decompose<br/>split into smaller sub-lemmas"]
            ST --> S3["③ Ask Informal Agent (Re-routing)<br/>for alternative proof route<br/>(bypass formal difficulty)"]
            S1 -.->|retry| FZ
            S2 -.->|retry| FZ
            S3 -.->|retry| FZ
        end
        FC --> PD["Polish & Done<br/>warnings · redundancy<br/>specificity"]
    end
```''')

# 3. Fix Archon_Workflow - use exact SVG labels
with open('Archon_Workflow.mermaid.md', 'w') as f:
    f.write('''```mermaid
flowchart TD
    subgraph Phases["Archon Workflow"]
        direction TB
        
        subgraph Scaffolding["Scaffolding"]
            RS["Read & Search<br/>Informal Materials"] --> WF["(Re)Write Formal Sketch<br/>split files & theorems"]
        end

        subgraph Proving["Proving"]
            WF --> AC{"compile &<br/>semantics"}
            AC -->|no| WF
            AC -->|yes| FZ["Formalize<br/>generate & fix proof"]
            FZ --> OK{"0 sorry &<br/>compiles"}
            OK -->|no| ST["Strategies"]
            ST --> S1["① Ask Informal Agent (Detailing)<br/>for more detailed proof steps"]
            ST --> S2["② Decompose<br/>split into smaller sub-lemmas"]
            ST --> S3["③ Ask Informal Agent (Re-routing)<br/>for alternative proof route<br/>(bypass formal difficulty)"]
            S1 -.->|retry| FZ
            S2 -.->|retry| FZ
            S3 -.->|retry| FZ
        end

        subgraph VNP["Verification and Polish"]
            OK -->|yes| FC["Final Checks"]
            FC --> PD["Polish & Done<br/>warnings · redundancy<br/>specificity"]
        end
    end

    subgraph Agents["Agent Types"]
        LA["Lean Agent"]
        LAPA["Lean Agent + Plan Agent"]
    end
```''')

# 4. Fix Agent_system_with_tools - add "call" and "result" edge labels
with open('Agent_system_with_tools.mermaid.md', 'w') as f:
    f.write('''```mermaid
flowchart TD
    subgraph System["Agent System"]
        PA["Plan Agent<br/>Summary, Strategy<br/>& Decomposition"]
        PA -->|dispatch| MA["(Multi) Lean Agent(s)<br/>(Parallel) Proof Attempts"]
        MA -->|iterate| PA
        MA -->|result| PA
    end

    subgraph Tools["Tools"]
        T1["Ask Informal Agent<br/>Natural Language Reasoning"]
        T2["LeanSearch<br/>Theorem-Definition Retrieval"]
        T3["Lean LSP MCP<br/>Diagnostics & Searching"]
        T4["Web Search<br/>Reference Lookup"]
        T5["Memory Manager<br/>Reading & Logging"]
    end

    MA -.->|call| Tools
    Tools -.->|result| MA
```''')

print("✅ All Mermaid diagrams updated")
