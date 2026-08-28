const EXACT_AUTH_ERROR_KEYS = new Map([
  ["Invalid email or password.", "auth.invalidEmailOrPassword"],
  ["An account with this email already exists.", "auth.accountAlreadyExists"],
  ["Account is disabled. Please contact support.", "auth.accountDisabled"],
  ["Invalid or expired reset token.", "auth.invalidOrExpiredResetToken"],
  ["Authentication required", "auth.authenticationRequired"],
  ["Token has expired", "auth.tokenExpired"],
  ["Invalid authentication token", "auth.invalidAuthenticationToken"],
  ["Google ID token has expired.", "auth.googleTokenExpired"],
  ["GOOGLE_CLIENT_ID is not configured on the server.", "auth.googleNotConfiguredServer"],
]);

function _mapByPattern(detail) {
  if (!detail) return null;
  const lower = detail.toLowerCase();
  if (lower.includes("google id token audience")) return "auth.googleAudienceMismatch";
  if (lower.includes("google id token issuer")) return "auth.googleIssuerInvalid";
  if (lower.includes("could not verify google identity")) return "auth.googleProviderUnavailable";
  return null;
}

export function mapAuthErrorDetail(t, detail, fallbackKey = "auth.somethingWentWrong") {
  if (typeof detail === "string") {
    const normalized = detail.trim();
    const exact = EXACT_AUTH_ERROR_KEYS.get(normalized);
    if (exact) return t(exact);
    const byPattern = _mapByPattern(normalized);
    if (byPattern) return t(byPattern);
  }
  return t(fallbackKey);
}

export function getAuthErrorMessage(t, error, fallbackKey = "auth.somethingWentWrong") {
  const detail = error?.response?.data?.detail || error?.response?.data?.message;
  return mapAuthErrorDetail(t, detail, fallbackKey);
}
