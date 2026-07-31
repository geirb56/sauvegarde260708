/**
 * OAuthButtons — Google and Apple sign-in buttons.
 *
 * Handles the entire OAuth flow:
 *   1. Loads the provider SDK (Google GSI / Apple JS SDK) on mount.
 *   2. Triggers the provider's auth dialog when the button is clicked.
 *   3. Receives the provider's ID token client-side.
 *   4. Sends only the ID token to the RunIndex backend for server-side
 *      verification — the frontend never derives identity from the token.
 *   5. Stores the RunIndex JWT returned by the backend.
 *   6. Calls loginWithToken() to update AuthContext.
 *
 * Security notes:
 *   - REACT_APP_GOOGLE_CLIENT_ID and REACT_APP_APPLE_CLIENT_ID are public
 *     OAuth identifiers, not secrets.  They are safe to include in the
 *     frontend bundle.
 *   - The frontend never reads claims from the provider ID token.
 *   - No Google / Apple session is created on the client side.
 */

import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { API_BASE_URL } from "@/config";
import { useAuth } from "@/context/AuthContext";
import { useLanguage } from "@/context/LanguageContext";
import { Button } from "@/components/ui/button";
import { Loader2 } from "lucide-react";
import { getAuthErrorMessage } from "@/lib/authErrors";

// ── Configuration (public IDs, not secrets) ───────────────────────────────────

const GOOGLE_CLIENT_ID = process.env.REACT_APP_GOOGLE_CLIENT_ID || "";
const APPLE_CLIENT_ID = process.env.REACT_APP_APPLE_CLIENT_ID || "";
const APPLE_REDIRECT_URI =
  process.env.REACT_APP_APPLE_REDIRECT_URI ||
  (typeof window !== "undefined" ? window.location.origin : "");

async function fetchOAuthChallenge(provider) {
  const res = await axios.post(`${API_BASE_URL}/auth/oauth/challenge/${provider}`);
  return res.data;
}

// ── Google Sign-In ────────────────────────────────────────────────────────────

function useGoogleSignIn({ onSuccess, onError, t }) {
  const [ready, setReady] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!GOOGLE_CLIENT_ID) return;

    // Load Google Identity Services script
    if (document.getElementById("google-gsi-script")) {
      if (window.google?.accounts) setReady(true);
      return;
    }

    const script = document.createElement("script");
    script.id = "google-gsi-script";
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.defer = true;
    script.onload = () => {
      setReady(true);
    };
    script.onerror = () => {
      onError(t("auth.googleLoadFailed"));
    };
    document.head.appendChild(script);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleGoogleCredential = useCallback(async (idToken, state) => {
   try {
     const res = await axios.post(`${API_BASE_URL}/auth/google`, {
       id_token: idToken,
       state,
     });
     onSuccess(res.data);
   } catch (err) {
     onError(getAuthErrorMessage(t, err, "auth.googleFailed"));
   } finally {
     setLoading(false);
   }
  }, [onSuccess, onError, t]);

  const signIn = useCallback(() => {
    if (!GOOGLE_CLIENT_ID) {
      onError(t("auth.googleNotConfigured"));
      return;
    }
    if (!window.google?.accounts) {
      onError(t("auth.googleUnavailable"));
      return;
    }
    setLoading(true);
    fetchOAuthChallenge("google")
      .then((challenge) => {
        window.google.accounts.id.initialize({
          client_id: GOOGLE_CLIENT_ID,
          nonce: challenge.nonce,
          callback: (response) => {
            if (response.credential) {
              handleGoogleCredential(response.credential, challenge.state);
            } else {
              setLoading(false);
              onError(t("auth.googleCancelled"));
            }
          },
          cancel_on_tap_outside: true,
        });
        window.google.accounts.id.prompt((notification) => {
          if (
            notification.isNotDisplayed() ||
            notification.isSkippedMoment()
          ) {
            const btn = document.createElement("div");
            btn.style.display = "none";
            document.body.appendChild(btn);
            window.google.accounts.id.renderButton(btn, {
              theme: "outline",
              size: "large",
              click_listener: () => {},
            });
            btn.querySelector("div[role='button']")?.click();
            document.body.removeChild(btn);
          }
        });
      })
      .catch((err) => {
        setLoading(false);
        onError(getAuthErrorMessage(t, err, "auth.googleFailed"));
      });
  }, [handleGoogleCredential, onError, t]);

  return { signIn, ready: ready && !!GOOGLE_CLIENT_ID, loading };
}

// ── Apple Sign-In ─────────────────────────────────────────────────────────────

function useAppleSignIn({ onSuccess, onError, t }) {
  const [ready, setReady] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!APPLE_CLIENT_ID) return;

    if (document.getElementById("apple-signin-script")) {
      if (window.AppleID) setReady(true);
      return;
    }

    const script = document.createElement("script");
    script.id = "apple-signin-script";
    script.src =
      "https://appleid.cdn-apple.com/appleauth/static/jsapi/appleid/1/en_US/appleid.auth.js";
    script.async = true;
    script.defer = true;
    script.onload = () => {
      setReady(true);
    };
    script.onerror = () => {
      onError(t("auth.appleLoadFailed"));
    };
    document.head.appendChild(script);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const signIn = useCallback(async () => {
    if (!APPLE_CLIENT_ID) {
      onError(t("auth.appleNotConfigured"));
      return;
    }
    if (!window.AppleID?.auth) {
      onError(t("auth.appleUnavailable"));
      return;
    }

    setLoading(true);
    try {
    const challenge = await fetchOAuthChallenge("apple");
    window.AppleID.auth.init({
      clientId: APPLE_CLIENT_ID,
      scope: "name email",
      redirectURI: APPLE_REDIRECT_URI,
      usePopup: true,
      state: challenge.state,
      nonce: challenge.nonce,
    });
      const result = await window.AppleID.auth.signIn();
      const idToken = result?.authorization?.id_token;
      const returnedState = result?.authorization?.state || challenge.state;
      const email = result?.user?.email || null;

      if (!idToken) {
        onError(t("auth.appleNoToken"));
        return;
      }
      if (returnedState !== challenge.state) {
        onError(t("auth.appleFailed"));
        return;
      }

      const res = await axios.post(`${API_BASE_URL}/auth/apple`, {
        id_token: idToken,
        email: email,
        state: challenge.state,
      });
      onSuccess(res.data);
    } catch (err) {
      if (err?.error === "popup_closed_by_user" || err?.error === "user_cancelled_authorize") {
        onError(t("auth.appleCancelled"));
      } else if (err?.response) {
        onError(getAuthErrorMessage(t, err, "auth.appleFailed"));
      } else if (err?.error) {
        // Apple JS SDK error codes
        onError(t("auth.appleFailed"));
      } else {
        onError(t("auth.appleFailed"));
      }
    } finally {
      setLoading(false);
    }
  }, [onError, onSuccess, t]);

  return { signIn, ready: ready && !!APPLE_CLIENT_ID, loading };
}

// ── OAuthButtons component ────────────────────────────────────────────────────

/**
 * @param {{ onError: (msg: string) => void, onSuccess: () => void }} props
 */
export default function OAuthButtons({ onError, onSuccess }) {
  const { loginWithToken } = useAuth();
  const { t } = useLanguage();

  const handleSuccess = useCallback(
    (data) => {
      // data = { access_token, token_type, user }
      loginWithToken(data.access_token, data.user);
      onSuccess?.();
    },
    [loginWithToken, onSuccess]
  );

  const google = useGoogleSignIn({ onSuccess: handleSuccess, onError, t });
  const apple = useAppleSignIn({ onSuccess: handleSuccess, onError, t });

  const hasGoogle = !!GOOGLE_CLIENT_ID;
  const hasApple = !!APPLE_CLIENT_ID;

  if (!hasGoogle && !hasApple) return null;

  return (
    <div className="space-y-2">
      {hasGoogle && (
        <Button
          type="button"
          variant="outline"
          className="w-full flex items-center justify-center gap-2"
          onClick={google.signIn}
          disabled={!google.ready || google.loading}
          aria-label={t("auth.continueWithGoogle")}
        >
          {google.loading ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <GoogleIcon />
          )}
          {t("auth.continueWithGoogle")}
        </Button>
      )}

      {hasApple && (
        <Button
          type="button"
          variant="outline"
          className="w-full flex items-center justify-center gap-2"
          onClick={apple.signIn}
          disabled={!apple.ready || apple.loading}
          aria-label={t("auth.continueWithApple")}
        >
          {apple.loading ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <AppleIcon />
          )}
          {t("auth.continueWithApple")}
        </Button>
      )}
    </div>
  );
}

// ── Provider icons ────────────────────────────────────────────────────────────

function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
      <path
        fill="#EA4335"
        d="M24 9.5c3.5 0 6.6 1.2 9 3.2l6.7-6.7C35.8 2.5 30.2 0 24 0 14.6 0 6.6 5.4 2.7 13.2l7.8 6C12.3 13.2 17.7 9.5 24 9.5z"
      />
      <path
        fill="#4285F4"
        d="M46.5 24.5c0-1.6-.1-3.1-.4-4.5H24v8.5h12.7c-.6 3-2.3 5.5-4.8 7.2l7.5 5.8C43.7 37.6 46.5 31.5 46.5 24.5z"
      />
      <path
        fill="#FBBC05"
        d="M10.5 28.7c-.5-1.5-.8-3-.8-4.7s.3-3.2.8-4.7L2.7 13.2C1 16.5 0 20.1 0 24s1 7.5 2.7 10.8l7.8-6.1z"
      />
      <path
        fill="#34A853"
        d="M24 48c6.2 0 11.4-2 15.2-5.5l-7.5-5.8c-2 1.4-4.6 2.2-7.7 2.2-6.3 0-11.7-3.7-13.5-9l-7.8 6C6.6 42.6 14.6 48 24 48z"
      />
    </svg>
  );
}

function AppleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 814 1000" aria-hidden="true">
      <path
        fill="currentColor"
        d="M788.1 340.9c-5.8 4.5-108.2 62.2-108.2 190.5 0 148.4 130.3 200.9 134.2 202.2-.6 3.2-20.7 71.9-68.7 141.9-42.8 61.6-87.5 123.1-155.5 123.1s-85.5-39.5-164-39.5c-76 0-103.7 40.8-165.9 40.8s-105-57.8-155.5-127.4C46 376.7 0 209.4 0 166.7C0 69.4 64.8 15.9 148.4 15.9 195.7 15.9 239.8 31 271.8 56.8c.1 0 71.7 46.8 133.8 46.8 57.8 0 119.5-37.7 157-37.7zm-8.7-93.9c-36.2 15.9-68.1 41.2-95.5 73-24.4 27.5-55.7 76-55.7 140.1 0 4 .3 8 .3 8h4c2.9 0 6.2-.3 9.2-.3 71.2 0 121.4-38.8 140.2-65.2 23.1-33.1 31.5-71.2 31.5-108.5 0-10.8-.8-21.8-2.3-31.4-12 3.4-21.4 7.9-31.7 13.3z"
      />
    </svg>
  );
}
