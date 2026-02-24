- [x] Clarify Project Requirements
- [x] Scaffold the Project (Gitea + Sidecar + pgvector)
- [x] Create docker-compose.yml
- [x] Build sidecar FastAPI service (plugins/)
- [x] Implement RTAC PLG parser module
- [x] Implement RAG indexer + search (pgvector)
- [x] Implement similar-configs finder
- [x] Create Gitea custom templates
- [x] Create DB init scripts
- [x] Ensure Documentation is Complete
- [x] Create and Run Task (docker compose up)
- [x] Launch the Project
- [x] Set up Gitea webhooks for auto-indexing
- [x] Cross-profile device mapping (schema + API + architecture doc)
- [ ] Test end-to-end with real RTAC XML

Work through each checklist item systematically.
Update the copilot-instructions.md file in the .github directory directly as you complete each step.

---

**SCADA Studio Project Requirements:**
- Gitea-based RTAC configuration management platform:
	- Vanilla Gitea (Docker image, independently updatable) for version control
	- FastAPI sidecar (`drumttocs8/scada-studio`) for custom SCADA functionality
	- Gitea custom templates (`drumttocs8/gitea`) — thin Dockerfile overlay
	- RTAC PLG parser adapted for in-memory XML processing via API
	- PostgreSQL for config/points storage; RAG/embeddings handled by n8n
	- Automatic indexing via Gitea push webhooks → sidecar
	- Custom Gitea templates adding SCADA toolbar + file-view buttons
	- Similar-config finder (text-based; vector search via n8n)
	- Points list generation (JSON/CSV) from RTAC XML
	- Integration with n8n, CIMGraph API, and Blazegraph
	- Deployable on Railway alongside other Verance AI tools

**Railway Services (project: splendid-nature):**
- `gitea` — Gitea UI from `drumttocs8/gitea` (thin overlay on gitea/gitea:main-nightly-rootless)
- `scada-studio` — FastAPI sidecar from `drumttocs8/scada-studio`
- `pgvector` — Shared PostgreSQL (used by both Gitea and sidecar)