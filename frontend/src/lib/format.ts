/** Presentation helpers for source strings returned by OneBD APIs. */

export function formatDate(value: string | null | undefined): string {
  if (!value) return '—';
  const normalized = /^\d{4}-\d{2}-\d{2}$/.test(value)
    ? `${value}T00:00:00`
    : value;
  const parsed = new Date(normalized);
  return Number.isNaN(parsed.getTime())
    ? value.slice(0, 10)
    : parsed.toLocaleDateString();
}

function decodeEntity(entity: string): string {
  const named: Record<string, string> = {
    amp: '&',
    apos: "'",
    gt: '>',
    lt: '<',
    nbsp: ' ',
    quot: '"',
  };
  const body = entity.slice(1, -1);
  if (body.startsWith('#x') || body.startsWith('#X')) {
    const value = Number.parseInt(body.slice(2), 16);
    return Number.isFinite(value) ? String.fromCodePoint(value) : entity;
  }
  if (body.startsWith('#')) {
    const value = Number.parseInt(body.slice(1), 10);
    return Number.isFinite(value) ? String.fromCodePoint(value) : entity;
  }
  return named[body] ?? entity;
}

export function decodeSourceEntities(value: string | null | undefined): string {
  return (value || '').replace(/&(?:#\d+|#x[\da-f]+|amp|apos|gt|lt|nbsp|quot);/gi, decodeEntity);
}

export function stripSourceMarkup(value: string | null | undefined): string {
  return decodeSourceEntities(value)
    .replace(/<\/?para>/gi, '\n')
    .replace(/<ulink\b[^>]*>/gi, '')
    .replace(/<\/ulink>/gi, '')
    .replace(/<[^>]+>/g, '')
    .replace(/\[\s*\d+\s*\]/g, '')
    .replace(/[ \t]+/g, ' ')
    .replace(/\n\s*\n+/g, '\n\n')
    .trim();
}
