# Cross-Profile Device Mapping Architecture

## Overview

CIM models are split across profiles — **EQ** (Electrical), **SC** (SCADA/Communications), **PE** (Protection), **CN** (Communications Network). Equipment that is physically a single device appears in multiple profiles with different URIs and class types.

The **device mapping** system associates these cross-profile entities so that:
- The SCADA topology overlay can position RemoteUnits on the correct EQ buses
- Points lists can be enriched with electrical context (voltage level, bay, equipment type)
- Protection relays can be linked to the SCADA devices they communicate through
- The D3 visualization can show unified cross-profile views

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   EQ Profile    │     │   SC Profile     │     │   PE Profile    │
│  (Breakers,     │     │  (RemoteUnits,   │     │  (Relays,       │
│   Transformers) │     │   SCADA Points)  │     │   Protections)  │
└───────┬─────────┘     └───────┬──────────┘     └───────┬─────────┘
        │                       │                        │
        │   eq_uri              │ sc_device_uri          │ pe_relay_uri
        └───────────┬───────────┘────────────────────────┘
                    │
          ┌─────────▼──────────┐
          │  device_mappings   │
          │  (PostgreSQL)      │
          │                    │
          │  substation        │
          │  eq_uri / eq_name  │
          │  sc_device_uri     │
          │  pe_relay_uri      │
          │  tag_pattern       │
          │  confidence        │
          │  source            │
          └─────────┬──────────┘
                    │
        ┌───────────┼───────────────┐
        │           │               │
   ┌────▼───┐  ┌───▼────┐   ┌─────▼──────┐
   │ Manual  │  │ Naming │   │ AI-inferred │
   │ Entry   │  │ Match  │   │ (n8n/LLM)  │
   └─────────┘  └────────┘   └────────────┘
```

## Schema

```sql
CREATE TABLE device_mappings (
    id              SERIAL PRIMARY KEY,
    substation      TEXT NOT NULL,
    -- EQ profile
    eq_uri          TEXT,                    -- CIM mRID of EQ equipment
    eq_name         TEXT,                    -- IdentifiedObject.name
    eq_type         TEXT,                    -- Breaker, PowerTransformer, etc.
    -- SC profile
    sc_device_uri   TEXT,                    -- RemoteUnit CIM mRID
    sc_device_name  TEXT,                    -- RemoteUnit name
    sc_map_name     TEXT,                    -- RTAC map name from PLG parser
    -- PE profile
    pe_relay_uri    TEXT,                    -- Relay CIM mRID
    pe_relay_name   TEXT,                    -- Relay name
    -- Tag matching
    tag_pattern     TEXT,                    -- Regex for SCADA tag names
    -- Provenance
    confidence      FLOAT DEFAULT 1.0,      -- 1.0 = manual, <1.0 = auto
    source          TEXT DEFAULT 'manual',   -- manual | naming_convention | ai_inferred
    model_name      TEXT,                    -- Blazegraph model name
    config_id       INTEGER REFERENCES rtac_configs(id),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (substation, eq_uri, sc_device_uri)
);
```

## Mapping Resolution Strategy (3-Tier)

### Tier 1: Explicit / Manual (confidence = 1.0)

User provides a mapping dictionary (JSON or CSV) that directly associates:
- EQ equipment name → SC RemoteUnit name/map_name
- Example: `{"hv_bk_1": "SEL451_Bay1", "main_xfmr": "SEL787_Xfmr"}`

These are stored with `source = 'manual'` and `confidence = 1.0`.

### Tier 2: Naming Convention Match (confidence = 0.7-0.9)

RTAC tag names typically encode equipment names following utility naming standards:
- `BKR1_MW` → Breaker 1 megawatt measurement
- `XFMR_TAP_POS` → Transformer tap position
- `CAP_BANK_STS` → Capacitor bank status

A pattern-matching engine scans SC point `tagName` values and attempts to match them to EQ `IdentifiedObject.name` values. Confidence varies based on match quality:
- Exact substring: 0.9
- Fuzzy match (Levenshtein ≤ 2): 0.8
- Partial overlap: 0.7

### Tier 3: AI-Inferred (confidence = 0.4-0.7)

For utilities with non-obvious naming conventions, an n8n workflow:
1. Fetches all EQ equipment names + types for a substation
2. Fetches all SC RemoteUnit names + point tag names
3. Sends both lists to an LLM with utility-specific context
4. LLM proposes associations with reasoning
5. Associations stored with `source = 'ai_inferred'`, `confidence` based on LLM self-assessment

## CIM Standard Linkage

The standard CIM bridge between profiles is `Measurement.PowerSystemResource`:

```xml
<!-- SC Profile: Analog measurement -->
<cim:Analog rdf:ID="_analog-001">
  <cim:IdentifiedObject.name>BKR1_MW</cim:IdentifiedObject.name>
  <cim:Measurement.PowerSystemResource rdf:resource="#_eq-breaker-001"/>
</cim:Analog>
```

The `device_mappings` table enables populating this link automatically:
1. RTAC PLG parser extracts devices and points → stored in `rtac_configs` + `points`
2. Device mapping associates `sc_map_name` → `eq_uri`
3. SC profile builder (`SCProfileBuilder`) reads mapping from DB instead of requiring a manual dict
4. Generated CIM XML includes correct `Measurement.PowerSystemResource` references

## Integration Points

### scada-studio (FastAPI sidecar)
- `POST /api/mappings` — Create/update device mappings
- `GET /api/mappings?substation=X` — List mappings for a substation
- `POST /api/mappings/auto-detect` — Run naming-convention matching
- `DELETE /api/mappings/{id}` — Remove a mapping

### cim-admin (visualization)
- `/api/profiles/cross-query` — Already queries across profiles; enhanced to JOIN `device_mappings`
- Diagram overlay: SC layer positions RemoteUnits near their mapped EQ equipment
- D3 unified view: Single graph showing EQ + SC + PE nodes with mapping edges

### n8n (AI workflows)
- Trigger: Gitea push webhook (RTAC config change) or manual
- Action: Fetch EQ + SC data → LLM inference → store in `device_mappings`
- Notification: Slack/email when new low-confidence mappings need review

### Gitea (version control)
- RTAC configs stored in git repos
- Mapping exports (JSON) committed alongside configs for audit trail
- Webhook triggers re-mapping on config changes

## Data Flow

```
1. Upload RTAC XML → Gitea repo
                        │
2. Webhook fires    ────┤
                        │
3. scada-studio parses  ├─→ rtac_configs + points tables
                        │
4. Auto-detect runs     ├─→ naming convention matcher
                        │       │
5. If EQ model exists   │       ├─→ device_mappings (confidence ≥ 0.7)
                        │       │
6. Low-confidence gaps  │       └─→ n8n AI workflow trigger
                        │               │
7. LLM proposes links   │              └─→ device_mappings (confidence 0.4-0.7)
                        │
8. User reviews/edits   └─→ device_mappings (confidence → 1.0)
                        │
9. SC profile rebuild   └─→ CIM XML with Measurement.PowerSystemResource links
```

## Export Format

Mappings can be exported as JSON for git tracking:

```json
{
  "substation": "ORS1",
  "model": "ORS1-PPC-R151",
  "mappings": [
    {
      "eq_name": "hv_bk_1",
      "eq_type": "Breaker",
      "sc_device": "NYSEGServer",
      "sc_map_name": "DNP3_NYSEG",
      "pe_relay": null,
      "tag_pattern": "^NYSEG_BKR1_",
      "confidence": 0.85,
      "source": "naming_convention"
    }
  ],
  "exported_at": "2025-01-15T12:00:00Z"
}
```

This JSON is stored in the Gitea repo alongside the RTAC config files for audit trail and version control.
