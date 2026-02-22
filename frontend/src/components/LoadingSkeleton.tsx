interface LoadingSkeletonProps {
  className?: string;
  variant?: 'text' | 'circular' | 'rectangular';
  width?: string;
  height?: string;
  count?: number;
}

export default function LoadingSkeleton({
  className = '',
  variant = 'rectangular',
  width = 'w-full',
  height = 'h-4',
  count = 1,
}: LoadingSkeletonProps) {
  const baseClasses = 'bg-slate-800 animate-pulse';
  
  const variantClasses = {
    text: 'rounded',
    circular: 'rounded-full',
    rectangular: 'rounded-lg',
  };

  const skeletonClasses = `${baseClasses} ${variantClasses[variant]} ${width} ${height} ${className}`;

  if (count === 1) {
    return <div className={skeletonClasses}></div>;
  }

  return (
    <div className="space-y-3">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className={skeletonClasses}></div>
      ))}
    </div>
  );
}

// Preset skeleton components for common use cases
export function TableSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-3">
      <LoadingSkeleton height="h-10" className="mb-4" /> {/* Header */}
      {Array.from({ length: rows }).map((_, i) => (
        <LoadingSkeleton key={i} height="h-12" />
      ))}
    </div>
  );
}

export function CardSkeleton() {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-lg p-6 space-y-4">
      <LoadingSkeleton width="w-3/4" height="h-6" />
      <LoadingSkeleton count={3} />
      <div className="flex gap-2 mt-4">
        <LoadingSkeleton width="w-24" height="h-8" />
        <LoadingSkeleton width="w-24" height="h-8" />
      </div>
    </div>
  );
}
