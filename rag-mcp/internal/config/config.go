// Package config loads process configuration for the MCP server.
package config

import (
	"encoding/json"
	"fmt"
	"os"
	"strings"
	"time"
)

const (
	DefaultBackendURL    = "http://127.0.0.1:8000"
	DefaultTenant        = "local"
	DefaultHTTPAddr      = ":8081"
	DefaultSearchTimeout = 45 * time.Second
	DefaultIngestTimeout = 120 * time.Second
	DefaultDocTimeout    = 20 * time.Second
	MaxIngestBytes       = 8 << 20
)

// Config is the runtime configuration. Secrets stay in the environment.
type Config struct {
	Transport     string
	Addr          string
	BackendURL    string
	InternalToken string
	Tokens        map[string]string
	Tenant        string
	IngestRoot    string
	SearchTimeout time.Duration
	IngestTimeout time.Duration
	DocTimeout    time.Duration
	LogLevel      string
}

// FromEnv reads configuration from the environment.
//
// MCP_TOKENS is either a JSON object {"bearer":"tenant"} or a comma-separated
// list of bearer=tenant pairs. HTTP mode requires at least one pair.
func FromEnv() (Config, error) {
	cfg := Config{
		Transport:     env("RAG_MCP_TRANSPORT", "stdio"),
		Addr:          env("RAG_MCP_ADDR", DefaultHTTPAddr),
		BackendURL:    strings.TrimRight(env("RAG_BACKEND_URL", DefaultBackendURL), "/"),
		InternalToken: os.Getenv("MCP_INTERNAL_TOKEN"),
		Tenant:        env("MCP_TENANT_ID", DefaultTenant),
		IngestRoot:    os.Getenv("RAG_MCP_INGEST_ROOT"),
		SearchTimeout: durationEnv("RAG_MCP_SEARCH_TIMEOUT", DefaultSearchTimeout),
		IngestTimeout: durationEnv("RAG_MCP_INGEST_TIMEOUT", DefaultIngestTimeout),
		DocTimeout:    durationEnv("RAG_MCP_DOCUMENT_TIMEOUT", DefaultDocTimeout),
		LogLevel:      env("LOG_LEVEL", "INFO"),
	}
	tokens, err := ParseTokenMap(os.Getenv("MCP_TOKENS"))
	if err != nil {
		return Config{}, err
	}
	if single := os.Getenv("MCP_BEARER_TOKEN"); single != "" {
		tenant := cfg.Tenant
		if tenant == "" {
			return Config{}, fmt.Errorf("MCP_BEARER_TOKEN requires MCP_TENANT_ID")
		}
		if err := validatePair(single, tenant); err != nil {
			return Config{}, err
		}
		tokens[single] = tenant
	}
	cfg.Tokens = tokens
	if strings.TrimSpace(cfg.InternalToken) == "" {
		return Config{}, fmt.Errorf("MCP_INTERNAL_TOKEN is required")
	}
	switch cfg.Transport {
	case "stdio", "http":
	default:
		return Config{}, fmt.Errorf("RAG_MCP_TRANSPORT must be stdio or http")
	}
	if cfg.Transport == "http" && len(cfg.Tokens) == 0 {
		return Config{}, fmt.Errorf("HTTP mode requires MCP_TOKENS or MCP_BEARER_TOKEN")
	}
	if strings.TrimSpace(cfg.Tenant) == "" || len(cfg.Tenant) > 64 || strings.ContainsAny(cfg.Tenant, " \t") {
		return Config{}, fmt.Errorf("invalid MCP_TENANT_ID")
	}
	return cfg, nil
}

// ParseTokenMap parses the MCP_TOKENS value.
func ParseTokenMap(raw string) (map[string]string, error) {
	out := map[string]string{}
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return out, nil
	}
	if strings.HasPrefix(raw, "{") {
		if err := json.Unmarshal([]byte(raw), &out); err != nil {
			return nil, fmt.Errorf("MCP_TOKENS: %w", err)
		}
		for token, tenant := range out {
			if err := validatePair(token, tenant); err != nil {
				return nil, err
			}
		}
		return out, nil
	}
	for _, part := range strings.Split(raw, ",") {
		part = strings.TrimSpace(part)
		if part == "" {
			continue
		}
		token, tenant, ok := strings.Cut(part, "=")
		if !ok {
			return nil, fmt.Errorf("MCP_TOKENS entry %q must look like token=tenant", part)
		}
		token = strings.TrimSpace(token)
		tenant = strings.TrimSpace(tenant)
		if err := validatePair(token, tenant); err != nil {
			return nil, err
		}
		out[token] = tenant
	}
	if len(out) == 0 {
		return nil, fmt.Errorf("MCP_TOKENS did not contain any token=tenant pairs")
	}
	return out, nil
}

func validatePair(token, tenant string) error {
	if len(strings.TrimSpace(token)) < 8 {
		return fmt.Errorf("bearer token must be at least 8 characters")
	}
	tenant = strings.TrimSpace(tenant)
	if tenant == "" || len(tenant) > 64 || strings.ContainsAny(tenant, " \t") {
		return fmt.Errorf("invalid tenant %q", tenant)
	}
	return nil
}

func env(key, fallback string) string {
	if value := strings.TrimSpace(os.Getenv(key)); value != "" {
		return value
	}
	return fallback
}

func durationEnv(key string, fallback time.Duration) time.Duration {
	raw := strings.TrimSpace(os.Getenv(key))
	if raw == "" {
		return fallback
	}
	parsed, err := time.ParseDuration(raw)
	if err != nil || parsed <= 0 {
		return fallback
	}
	return parsed
}
