export default function AuthBrand({
  altText = "RunIndex",
  className = "",
  testId = "auth-brand-logo",
}) {
  return (
    <img
      src="/runindex-logo.png"
      alt={altText}
      className={`mx-auto h-12 w-auto max-w-[220px] ${className}`.trim()}
      data-testid={testId}
    />
  );
}
