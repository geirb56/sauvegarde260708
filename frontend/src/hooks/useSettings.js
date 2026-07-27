import { useState, useEffect } from "react";
import axios from "axios";
import { API_BASE } from "@/utils/constants";

export const useGoal = () => {
  const [goal, setGoal] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const loadGoal = async () => {
    try {
      setLoading(true);
      const res = await axios.get(`${API_BASE}/user/goal?user_id=default`);
      setGoal(res.data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadGoal();
  }, []);

  return { goal, setGoal, loading, error, reload: loadGoal };
};

export const useSubscriptionStatus = () => {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const loadStatus = async () => {
    try {
      setLoading(true);
      const res = await axios.get(`${API_BASE}/subscription/status?user_id=default`);
      setStatus(res.data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadStatus();
  }, []);

  return { status, setStatus, loading, error, reload: loadStatus };
};

export const usePremiumStatus = () => {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const loadStatus = async () => {
    try {
      setLoading(true);
      const res = await axios.get(`${API_BASE}/premium/status?user_id=default`);
      setStatus(res.data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadStatus();
  }, []);

  return { status, setStatus, loading, error, reload: loadStatus };
};
