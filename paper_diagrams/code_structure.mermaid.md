```mermaid
flowchart LR
    subgraph Project["Lean Formalization Project"]
        direction TB
        LF["lakefile.toml"] --> SRC
        SRC["src/"] --> THM["Theorem.lean"]
        SRC --> LEMMAS["Lemmas/"]
        LEMMAS --> L1["Lemma1.lean"]
        LEMMAS --> L2["Lemma2.lean"]
        SRC --> UTIL["Utils.lean"]
        SRC --> DEFS["Definitions.lean"]
        DOT["."] --> LF
        DOT --> SRC
        DOT --> BUILD["lake-packages/"]
        DOT --> OUT["build/"]
    end
