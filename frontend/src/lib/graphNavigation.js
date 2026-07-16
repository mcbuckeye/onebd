/** Resolve API graph entity IDs such as `company_123` to application routes. */
export function graphNodePath(node) {
  const prefixedId = node.id.match(/^(company|deal)_(\d+)$/);
  const nodeType = node.type || prefixedId?.[1];
  const entityId = prefixedId?.[2] || node.id;

  if (!/^\d+$/.test(entityId)) return null;
  if (nodeType === 'deal') return `/deals/${entityId}`;
  if (nodeType === 'company' || !nodeType) return `/company/${entityId}`;
  return null;
}
