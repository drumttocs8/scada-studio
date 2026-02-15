- [x] Clarify Project Requirements
- [x] Scaffold the Project
- [x] Customize the Project
- [x] Install Required Extensions
- [x] Compile the Project
- [ ] Create and Run Task
- [ ] Launch the Project
- [x] Ensure Documentation is Complete

Work through each checklist item systematically.
Update the copilot-instructions.md file in the .github directory directly as you complete each step.

---

**SCADA Studio Project Requirements:**
- Frontend app to:
	- Use RTAC PLG to convert .exp files to .xml and parse them
	- Enable points list generation and general RAG (Retrieval-Augmented Generation) searches
	- Generate CIM-style topology of data flow
	- Integrate with Gitea or any local/remote git server for version control
	- Be tested and deployed in Railway alongside other tools