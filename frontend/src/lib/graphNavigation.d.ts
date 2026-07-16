export interface GraphNavigationNode {
  id: string;
  type?: string;
}

export function graphNodePath(node: GraphNavigationNode): string | null;
