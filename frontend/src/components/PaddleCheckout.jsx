import { useEffect, useCallback } from "react";

const PADDLE_CLIENT_TOKEN = process.env.VITE_PADDLE_CLIENT_TOKEN || import.meta?.env?.VITE_PADDLE_CLIENT_TOKEN || "";
const PADDLE_ENV = process.env.VITE_PADDLE_ENVIRONMENT || import.meta?.env?.VITE_PADDLE_ENVIRONMENT || "sandbox";

/**
 * Loads Paddle.js once and initialises the SDK.
 * Returns a promise that resolves with the global Paddle object.
 */
function loadPaddleJS() {
  return new Promise((resolve, reject) => {
    if (window.Paddle) {
      return resolve(window.Paddle);
    }

    const existing = document.getElementById("paddle-js");
    if (existing) {
      existing.addEventListener("load", () => resolve(window.Paddle));
      existing.addEventListener("error", reject);
      return;
    }

    const script = document.createElement("script");
    script.id = "paddle-js";
    script.src = "https://cdn.paddle.com/paddle/v2/paddle.js";
    script.onload = () => {
      if (!window.Paddle) {
        return reject(new Error("Paddle.js failed to initialise"));
      }
      if (PADDLE_ENV === "sandbox") {
        window.Paddle.Environment.set("sandbox");
      }
      if (PADDLE_CLIENT_TOKEN) {
        window.Paddle.Initialize({ token: PADDLE_CLIENT_TOKEN });
      }
      resolve(window.Paddle);
    };
    script.onerror = reject;
    document.body.appendChild(script);
  });
}

/**
 * PaddleCheckout component
 *
 * Opens the Paddle overlay checkout when `checkoutUrl` is provided.
 * If `checkoutUrl` is a hosted Paddle URL the user will be redirected there
 * directly (fallback).  When Paddle.js is loaded and a priceId is given the
 * component can also open the overlay directly.
 *
 * Props:
 *   checkoutUrl  - hosted checkout URL returned by the backend
 *   priceId      - (optional) Paddle price ID for overlay checkout
 *   userId       - user identifier passed as custom_data
 *   onSuccess    - callback(transactionId) after successful payment
 *   onClose      - callback when the overlay is closed without payment
 */
export default function PaddleCheckout({ checkoutUrl, priceId, userId, onSuccess, onClose }) {
  const openCheckout = useCallback(async () => {
    if (!checkoutUrl && !priceId) return;

    try {
      const Paddle = await loadPaddleJS();

      if (priceId) {
        // Overlay checkout
        Paddle.Checkout.open({
          items: [{ priceId, quantity: 1 }],
          customData: { user_id: userId },
          settings: {
            displayModeTheme: "dark",
          },
          eventCallback: (event) => {
            if (event.name === "checkout.completed") {
              const txId = event.data?.transaction_id;
              onSuccess && onSuccess(txId);
            } else if (event.name === "checkout.closed") {
              onClose && onClose();
            }
          },
        });
      } else if (checkoutUrl) {
        // Fall back to hosted checkout (full redirect)
        window.location.href = checkoutUrl;
      }
    } catch (err) {
      console.error("PaddleCheckout error:", err);
      // Fallback: redirect to hosted checkout URL
      if (checkoutUrl) {
        window.location.href = checkoutUrl;
      }
    }
  }, [checkoutUrl, priceId, userId, onSuccess, onClose]);

  useEffect(() => {
    if (checkoutUrl || priceId) {
      openCheckout();
    }
  }, [checkoutUrl, priceId, openCheckout]);

  return null;
}
