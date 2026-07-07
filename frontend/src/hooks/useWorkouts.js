import { useState, useEffect } from "react";
import axios from "axios";
import { API_BASE } from "@/utils/constants";

export const useWorkouts = () => {
  const [workouts, setWorkouts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchWorkouts = async () => {
      try {
        setLoading(true);
        const res = await axios.get(`${API_BASE}/workouts`);
        setWorkouts(res.data);
      } catch (err) {
        setError(err.message);
        console.error("Failed to fetch workouts:", err);
      } finally {
        setLoading(false);
      }
    };

    fetchWorkouts();
  }, []);

  return { workouts, loading, error };
};

export const useStats = () => {
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchStats = async () => {
      try {
        setLoading(true);
        const res = await axios.get(`${API_BASE}/stats`);
        setStats(res.data);
      } catch (err) {
        setError(err.message);
        console.error("Failed to fetch stats:", err);
      } finally {
        setLoading(false);
      }
    };

    fetchStats();
  }, []);

  return { stats, loading, error };
};

export const useDashboardData = (lang) => {
  const [insight, setInsight] = useState(null);
  const [rag, setRag] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true);
        const [insightRes, ragRes] = await Promise.all([
          axios.get(`${API_BASE}/dashboard/insight?language=${lang}`),
          axios.get(`${API_BASE}/rag/dashboard`).catch(() => ({ data: null }))
        ]);
        setInsight(insightRes.data);
        setRag(ragRes.data);
      } catch (err) {
        setError(err.message);
        console.error("Failed to fetch dashboard data:", err);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [lang]);

  return { insight, rag, loading, error };
};

export const useCoachHistory = () => {
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const loadHistory = async () => {
    try {
      setLoading(true);
      const res = await axios.get(`${API_BASE}/coach/history?user_id=default&limit=50`);
      setMessages(res.data.map(msg => ({
        role: msg.role,
        content: msg.content,
        workout_id: msg.workout_id,
        timestamp: msg.timestamp
      })));
    } catch (err) {
      setError(err.message);
      console.error("Failed to load coach history:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadHistory();
  }, []);

  return { messages, setMessages, loading, error, reload: loadHistory };
};
