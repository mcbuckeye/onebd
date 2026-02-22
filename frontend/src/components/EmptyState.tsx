import { LucideIcon } from 'lucide-react';
import { ReactNode } from 'react';

interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  description?: string;
  action?: {
    label: string;
    onClick: () => void;
  };
  children?: ReactNode;
}

export default function EmptyState({ 
  icon: Icon, 
  title, 
  description, 
  action,
  children 
}: EmptyStateProps) {
  return (
    <div className="text-center py-16 px-4">
      <div className="inline-flex items-center justify-center w-16 h-16 bg-slate-800/50 rounded-full mb-4">
        <Icon className="w-8 h-8 text-slate-600" />
      </div>
      <h3 className="text-lg font-medium text-slate-300 mb-2">{title}</h3>
      {description && (
        <p className="text-sm text-slate-500 mb-6 max-w-md mx-auto">{description}</p>
      )}
      {action && (
        <button
          onClick={action.onClick}
          className="px-6 py-2.5 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg transition-colors"
        >
          {action.label}
        </button>
      )}
      {children}
    </div>
  );
}
