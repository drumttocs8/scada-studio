# User Guide

## Dashboard

The Dashboard shows an overview of uploaded RTAC XML configurations with counts of devices and points. Upload new XML files via drag-and-drop or file browser.

## Editor

Select a configuration from the Dashboard to open it in the Editor. Tabs:
- **XML Source** — Monaco editor with syntax highlighting
- **Devices** — Parsed server devices with map names
- **Points** — All extracted points with name, address, type, map
- **Points List** — Generate and download structured points list (JSON/CSV)

## Query

- **RAG Search** — Natural language search across RTAC configurations via n8n
- **CIM Topology** — Query CIM data model topology via CIMGraph API
- **SPARQL** — Direct SPARQL queries to Blazegraph

## Diff

Upload two XML files to compare them side-by-side with added/removed line highlighting.

## Settings

Configure Git server (Gitea) connection for version control integration.