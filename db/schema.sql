-- users
CREATE TABLE IF NOT EXISTS users (
  id UUID PRIMARY KEY,
  email TEXT UNIQUE NOT NULL,
  provider TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- credentials_temp
CREATE TABLE IF NOT EXISTS credentials_temp (
  user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  encrypted_password TEXT NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL
);

-- activities
CREATE TABLE IF NOT EXISTS activities (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  external_id TEXT NOT NULL,
  source TEXT NOT NULL,
  distance_m DOUBLE PRECISION,
  duration_s DOUBLE PRECISION,
  avg_hr INTEGER,
  pace DOUBLE PRECISION,
  raw_payload JSONB,
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(user_id, external_id)
);

-- sync_logs
CREATE TABLE IF NOT EXISTS sync_logs (
  id BIGSERIAL PRIMARY KEY,
  user_id UUID REFERENCES users(id),
  status TEXT,
  error TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);
