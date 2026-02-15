/**
 * Validation utilities for RTAC XML config files.
 */

export interface ValidationResult {
    valid: boolean;
    errors: string[];
    warnings: string[];
}

export function validateXml(content: string): ValidationResult {
    const errors: string[] = [];
    const warnings: string[] = [];

    if (!content.trim()) {
        errors.push('File is empty');
        return { valid: false, errors, warnings };
    }

    // Basic XML structure check
    try {
        const parser = new DOMParser();
        const doc = parser.parseFromString(content, 'application/xml');
        const parseErrors = doc.querySelectorAll('parsererror');
        if (parseErrors.length > 0) {
            errors.push(`XML Parse Error: ${parseErrors[0].textContent}`);
        }
    } catch (e: any) {
        errors.push(`XML Parse Error: ${e.message}`);
    }

    // RTAC-specific checks
    if (!content.includes('Device') && !content.includes('TagList') && !content.includes('SettingPage')) {
        warnings.push('File does not appear to contain RTAC-specific elements (Device, TagList, or SettingPage)');
    }

    return { valid: errors.length === 0, errors, warnings };
}

export function validateExpFile(filename: string): ValidationResult {
    const errors: string[] = [];
    const warnings: string[] = [];

    if (!filename.toLowerCase().endsWith('.exp')) {
        errors.push('File must have .exp extension');
    }

    warnings.push('.exp files require AcRtacCmd.exe (Windows only) for conversion to XML. Upload pre-converted XML files for cloud processing.');

    return { valid: errors.length === 0, errors, warnings };
}
