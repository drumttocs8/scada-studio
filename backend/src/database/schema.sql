-- SCADA Studio DB Schema

CREATE TABLE devices (
  id SERIAL PRIMARY KEY,
  name VARCHAR(255) UNIQUE NOT NULL,
  file_path VARCHAR(500) NOT NULL,
  repository VARCHAR(255) NOT NULL,
  protocol VARCHAR(50),
  firmware_version VARCHAR(50),
  device_type VARCHAR(100),
  last_modified TIMESTAMP,
  git_commit_hash VARCHAR(40),
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE points (
  id SERIAL PRIMARY KEY,
  device_id INTEGER REFERENCES devices(id) ON DELETE CASCADE,
  tag_name VARCHAR(255) NOT NULL,
  point_type VARCHAR(50),
  address VARCHAR(100),
  data_type VARCHAR(50),
  description TEXT,
  units VARCHAR(50),
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE config_metadata (
  id SERIAL PRIMARY KEY,
  device_id INTEGER REFERENCES devices(id) ON DELETE CASCADE,
  key VARCHAR(255) NOT NULL,
  value TEXT,
  UNIQUE(device_id, key)
);

CREATE INDEX idx_devices_protocol ON devices(protocol);
CREATE INDEX idx_devices_name ON devices(name);
CREATE INDEX idx_points_tag_name ON points(tag_name);
CREATE INDEX idx_points_device ON points(device_id);
