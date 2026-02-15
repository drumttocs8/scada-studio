/**
 * Client-side XML parsing utilities.
 * Used for preview/validation before uploading to the backend.
 */

export function parseXmlString(xml: string): Document {
    const parser = new DOMParser();
    const doc = parser.parseFromString(xml, 'application/xml');
    const errors = doc.querySelectorAll('parsererror');
    if (errors.length > 0) {
        throw new Error(`XML Parse Error: ${errors[0].textContent}`);
    }
    return doc;
}

export function xmlToJson(xml: string): Record<string, any> {
    const doc = parseXmlString(xml);
    return elementToObj(doc.documentElement);
}

function elementToObj(el: Element): any {
    const obj: any = {};
    // Attributes
    for (const attr of Array.from(el.attributes)) {
        obj[`@${attr.name}`] = attr.value;
    }
    // Children
    for (const child of Array.from(el.children)) {
        const key = child.tagName;
        const val = elementToObj(child);
        if (obj[key]) {
            if (!Array.isArray(obj[key])) obj[key] = [obj[key]];
            obj[key].push(val);
        } else {
            obj[key] = val;
        }
    }
    // Text content (only if no children)
    if (el.children.length === 0) {
        const text = el.textContent?.trim();
        if (text) return text;
    }
    return obj;
}

export function formatXml(xml: string, indent = '  '): string {
    let formatted = '';
    let depth = 0;
    const lines = xml.replace(/>\s*</g, '>\n<').split('\n');
    for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed) continue;
        if (trimmed.startsWith('</')) depth--;
        formatted += indent.repeat(Math.max(0, depth)) + trimmed + '\n';
        if (trimmed.startsWith('<') && !trimmed.startsWith('</') && !trimmed.endsWith('/>') && !trimmed.startsWith('<?')) {
            depth++;
        }
    }
    return formatted;
}
