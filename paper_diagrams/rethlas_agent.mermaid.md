```mermaid
flowchart LR
    subgraph Rethlas["Rethlas Agent"]
        direction TB
        GA["Generation Agent<br/>Propose Candidate Proofs"]
        VA["Verification Agent<br/>Verify Candidate Proofs"]
        GA <-->|call| VA
    end

    subgraph Tools["Tools"]
        T1["Matlas<br/>Theorem Retrieval"]
        T2["Web Search<br/>Reference Lookup"]
        T3["Memory Manager<br/>Reading & Logging"]
    end

    subgraph Skills["Skills"]
        S1["Construct examples"]
        S2["Construct counterexamples"]
        S3["Propose subgoal<br/>decomposition plans"]
        S4["Identify key failures"]
    end

    GA -.-> Tools
    VA -.-> Tools
    GA -.-> Skills
    VA -.-> Skills
