-- Database schema (PostgreSQL)
CREATE TABLE users (
  id serial PRIMARY KEY,
  username text NOT NULL,
  email text NOT NULL,
  hashed_password text NOT NULL,
  is_active boolean DEFAULT true
);

CREATE TABLE strategies (
  id serial PRIMARY KEY,
  name text NOT NULL,
  enabled boolean DEFAULT true,
  params jsonb
);

CREATE TABLE signals (
  id serial PRIMARY KEY,
  strategy_id integer REFERENCES strategies(id),
  symbol text,
  side text,
  entry numeric,
  stoploss numeric,
  target numeric,
  confidence numeric,
  ts timestamptz DEFAULT now()
);

CREATE TABLE trades (
  id serial PRIMARY KEY,
  order_id text,
  signal_id integer REFERENCES signals(id),
  symbol text,
  side text,
  qty integer,
  price numeric,
  status text,
  ts timestamptz DEFAULT now()
);
