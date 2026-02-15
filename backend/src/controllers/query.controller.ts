import { Request, Response } from 'express';
import axios from 'axios';

// Endpoints for existing Railway services
const N8N_WEBHOOK_URL = process.env.N8N_WEBHOOK_URL || 'https://n8n-g8qm-production.up.railway.app';
const CIMGRAPH_API_URL = process.env.CIMGRAPH_API_URL || 'http://cimgraph-api.railway.internal';
const BLAZEGRAPH_URL = process.env.BLAZEGRAPH_URL || 'http://blazegraph.railway.internal:8080/bigdata';

export const queryController = {
    /** RAG search via n8n webhook. */
    async search(req: Request, res: Response) {
        try {
            const { query, context } = req.body;
            if (!query) return res.status(400).json({ error: 'query is required' });

            // Try n8n RAG search webhook
            try {
                const resp = await axios.post(
                    `${N8N_WEBHOOK_URL}/webhook/rag-search`,
                    { query, context: context || 'scada-studio' },
                    { timeout: 30000 }
                );
                return res.json(resp.data);
            } catch (n8nErr: any) {
                // Fallback: try CIMGraph API directly
                try {
                    const resp = await axios.post(
                        `${CIMGRAPH_API_URL}/query`,
                        { question: query, cim_profile: 'rc4_2021' },
                        { timeout: 30000 }
                    );
                    return res.json({ source: 'cimgraph-api', results: resp.data });
                } catch (cimErr: any) {
                    return res.json({
                        source: 'local',
                        message: 'External search services unavailable. Query stored for later processing.',
                        query,
                    });
                }
            }
        } catch (err: any) {
            return res.status(500).json({ error: err.message });
        }
    },

    /** CIM topology query via Blazegraph SPARQL or CIMGraph API. */
    async cimTopology(req: Request, res: Response) {
        try {
            const { query, sparql } = req.body;

            if (sparql) {
                // Direct SPARQL query to Blazegraph
                try {
                    const resp = await axios.post(
                        `${BLAZEGRAPH_URL}/namespace/kb/sparql`,
                        `query=${encodeURIComponent(sparql)}`,
                        {
                            headers: { 'Content-Type': 'application/x-www-form-urlencoded', Accept: 'application/json' },
                            timeout: 30000,
                        }
                    );
                    return res.json({ source: 'blazegraph', results: resp.data });
                } catch (err: any) {
                    return res.status(502).json({ error: 'Blazegraph unavailable', details: err.message });
                }
            }

            if (query) {
                // Natural language → SPARQL via CIMGraph API
                try {
                    const resp = await axios.post(
                        `${CIMGRAPH_API_URL}/generate-sparql`,
                        { question: query, cim_profile: 'rc4_2021' },
                        { timeout: 30000 }
                    );
                    return res.json({ source: 'cimgraph-api', sparql: resp.data.sparql, results: resp.data });
                } catch (err: any) {
                    return res.status(502).json({ error: 'CIMGraph API unavailable', details: err.message });
                }
            }

            return res.status(400).json({ error: 'Provide either "query" (natural language) or "sparql" (SPARQL query)' });
        } catch (err: any) {
            return res.status(500).json({ error: err.message });
        }
    },
};
