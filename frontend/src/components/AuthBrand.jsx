export default function AuthBrand({
  altText = "RunIndex",
  className = "",
  testId = "auth-brand-logo",
}) {
  return (
    <img
      src="/runindex-logo.png"
      alt={altText}
      className={`mx-auto h-auto w-full max-w-[280px] ${className}`.trim()}
      data-testid={testId}
    />
  );
}
