# Acknowledgements

SourceBrief would not have taken its current shape without the open-source maintainers and researchers who shared their work in public.

The projects below challenged us to think more carefully about source-grounded answers, knowledge graphs, precise code navigation, context packaging, repo-specific agents, evaluation, and safe improvement loops. SourceBrief is an independent project, but it is better because these ideas were available to study, compare, and learn from.

Thank you to every maintainer, contributor, researcher, issue reporter, and documentation author behind them.

## Knowledge graphs, GraphRAG, and memory

| Project | What we appreciate |
| --- | --- |
| [Graphify](https://github.com/Graphify-Labs/graphify) | Repository and document graph extraction, graph merging, confidence-aware relationships, and community-oriented navigation. Historical SourceBrief research also followed the earlier `safishamsi/graphify` location. |
| [LightRAG](https://github.com/HKUDS/LightRAG) | Entity-relation GraphRAG, local/global/hybrid retrieval modes, incremental processing, and source-aware graph maintenance. |
| [Understand Anything](https://github.com/Egonex-AI/Understand-Anything) | Turning heterogeneous repositories and documents into navigable structural and semantic knowledge. Historical links under `Lum1104` now resolve to this project. |
| [Knowhere](https://github.com/Ontos-AI/knowhere) | Document parsing, knowledge-base construction, and observable agentic retrieval workflows. |
| [CodeGraph](https://github.com/colbymchenry/codegraph) | Multi-language structural code graphs, cross-file relationships, incremental updates, and search-quality evaluation. |
| [Code Review Graph](https://github.com/tirth8205/code-review-graph) | Change-impact and blast-radius analysis for review workflows. |
| [Hindsight](https://github.com/vectorize-io/hindsight) | Temporal memory, retain/recall/reflect workflows, and graph-assisted retrieval. |
| [Hermes Optimization Guide](https://github.com/OnlyTerp/hermes-optimization-guide) | Practical community guidance connecting Hermes, retrieval, and LightRAG-style memory systems. |

## Precise code context and navigation

| Project | What we appreciate |
| --- | --- |
| [Claude Context](https://github.com/zilliztech/claude-context) | Asynchronous code indexing, precise retrieval, file-selection controls, and visible indexing progress. |
| [Serena](https://github.com/oraios/serena) | Language-server-backed symbol navigation and precise code operations for agent workflows. |
| [Repomix](https://github.com/yamadashy/repomix) | Deterministic, filterable, token-aware repository context packaging. |
| [EvoEmbedding](https://github.com/MiG-NJU/EvoEmbedding) | Research into temporal and evolvable embedding memory. |

## Repo agents and knowledge packaging

| Project | What we appreciate |
| --- | --- |
| [GitAgent](https://github.com/open-gitagent/gitagent) | The repo-as-agent model: versioned identity, rules, memory, tools, skills, and hooks. |
| [RAG Skill](https://github.com/ConardLi/rag-skill) | Retrieval-first agent guidance and progressive disclosure instead of loading an entire corpus at once. |
| [Book to Skill](https://github.com/virgiliojr94/book-to-skill) | Deterministic extraction followed by spec-driven skill compilation. |
| [Skill-Anything](https://github.com/SYuan03/Skill-Anything) | Section-aware parsing, parallel map-reduce processing, and reusable knowledge-pack generation. |
| [Garden Skills](https://github.com/ConardLi/garden-skills) | Practical skill packaging, resource-map-first navigation, and the `kb-retriever` progressive-disclosure pattern. |

## Ingestion, retrieval experiments, evaluation, and improvement

| Project | What we appreciate |
| --- | --- |
| [CORTEX AI Super RAG](https://github.com/SaiAkhil066/CORTEX-AI-SUPER-RAG) | A practical comparison surface for contextual retrieval, HyDE, RAG-Fusion, graph retrieval, neural reranking, and corrective RAG. |
| [Hyper-Extract](https://github.com/yifanfeng97/Hyper-Extract) | Typed document extraction, provider abstraction, and incremental or parallel processing patterns. |
| [Awesome Agent Harness](https://github.com/Picrew/awesome-agent-harness) | A useful taxonomy and catalog for thinking about agent harnesses and outcome-oriented evaluation. |
| [Hermes Agent Self-Evolution](https://github.com/NousResearch/hermes-agent-self-evolution) | Review-, replay-, and evaluation-driven skill improvement with explicit candidate generation. |
| [SkillOpt](https://github.com/microsoft/SkillOpt) | Treating skills as optimizable artifacts while preserving validation and promotion gates. |

## Additional technical foundations

We also benefited from the public documentation and engineering work behind [Microsoft GraphRAG](https://github.com/microsoft/graphrag) and [pgvector](https://github.com/pgvector/pgvector).

## Attribution boundary

This page records intellectual and community inspiration. It is not a dependency inventory or a third-party notice file. SourceBrief's actual bundled dependencies and redistributed artifacts remain governed by their package manifests, lockfiles, source headers, and applicable licenses.

Project names and trademarks belong to their respective owners. Inclusion here does not imply affiliation with, sponsorship by, or endorsement of SourceBrief by any listed project. It also does not mean that SourceBrief copied or redistributes source code from every project named above.
