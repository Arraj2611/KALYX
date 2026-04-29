/**
 * Format numbers consistently for server and client rendering
 * to avoid hydration mismatches
 */
export function formatCurrency(value: number | null | undefined): string {
    if (value === null || value === undefined) return '0.00'

    // Use consistent formatting that works on both server and client
    return value.toLocaleString('en-IN', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    })
}

export function formatNumber(value: number | null | undefined): string {
    if (value === null || value === undefined) return '0'

    return value.toLocaleString('en-IN')
}

