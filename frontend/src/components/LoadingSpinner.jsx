import { Loader2 } from "lucide-react";

export const LoadingSpinner = ({ text = "", size = "md" }) => {
  const sizeClass = {
    sm: "w-4 h-4",
    md: "w-6 h-6",
    lg: "w-8 h-8"
  }[size];

  return (
    <div className="flex items-center justify-center gap-3">
      <Loader2 className={`${sizeClass} animate-spin text-primary`} />
      {text && <span className="font-mono text-xs uppercase tracking-widest text-muted-foreground">{text}</span>}
    </div>
  );
};

export const LoadingCard = () => (
  <div className="p-4 md:p-8 animate-pulse space-y-4">
    <div className="h-8 w-48 bg-muted rounded-sm" />
    <div className="h-64 bg-muted rounded-sm" />
  </div>
);

export const LoadingGrid = ({ columns = 3 }) => (
  <div className={`grid grid-cols-${columns} gap-4 animate-pulse`}>
    {Array.from({ length: columns }).map((_, i) => (
      <div key={i} className="h-32 bg-muted rounded-sm" />
    ))}
  </div>
);
