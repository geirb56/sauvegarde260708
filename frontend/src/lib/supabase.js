import { createClient } from "@supabase/supabase-js";

const supabaseUrl = process.env.REACT_APP_SUPABASE_URL;
const supabaseAnonKey = process.env.REACT_APP_SUPABASE_ANON_KEY;

if (!supabaseUrl || !supabaseAnonKey) {
  console.warn(
    "⚠️ Supabase environment variables not set. " +
    "REACT_APP_SUPABASE_URL and REACT_APP_SUPABASE_ANON_KEY are required."
  );
}

export const supabase = createClient(
  supabaseUrl || "http://localhost",
  supabaseAnonKey || "placeholder"
);
