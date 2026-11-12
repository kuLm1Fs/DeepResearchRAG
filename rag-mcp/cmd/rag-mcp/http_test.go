package main

import (
	"bytes"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"rag-mcp/internal/config"
)

func TestStreamableHTTPSearchRoundTrip(t *testing.T) {
	var tenant, trace string
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer internal-token-value" {
			t.Errorf("internal token %q", r.Header.Get("Authorization"))
		}
		tenant = r.Header.Get("X-Tenant-ID")
		trace = r.Header.Get("X-Trace-ID")
		w.Header().Set("Content-Type", "application/json")
		switch r.URL.Path {
		case "/api/internal/mcp/rewrite":
			_, _ = w.Write([]byte(`{"queries":["3M FY2018 capex"],"strategy":"hybrid","rewrite_applied":true}`))
		case "/api/internal/mcp/search":
			_, _ = w.Write([]byte(`{"queries":["3M FY2018 capex"],"strategy":"hybrid","top_k":5,"results":[{"doc_id":"doc-1","source":"sec","score":0.7,"timestamp":"2024-01-01T00:00:00Z","content":"Purchases of PP&E 1577"}]}`))
		default:
			http.NotFound(w, r)
		}
	}))
	defer upstream.Close()

	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	cfg := config.Config{
		BackendURL:    upstream.URL,
		InternalToken: "internal-token-value",
		Tokens:        map[string]string{"client-token": "acme"},
		SearchTimeout: 5 * time.Second,
		IngestTimeout: 5 * time.Second,
		DocTimeout:    5 * time.Second,
	}
	mcpServer, handler := newMCP(cfg, logger)
	srv := httptest.NewServer(newHTTPMux(cfg, logger, mcpServer, handler))
	defer srv.Close()

	health, err := http.Get(srv.URL + "/healthz")
	if err != nil {
		t.Fatal(err)
	}
	health.Body.Close()
	if health.StatusCode != http.StatusOK {
		t.Fatalf("health %d", health.StatusCode)
	}

	denied := postMCP(t, srv.URL+"/mcp", "", nil, map[string]any{
		"jsonrpc": "2.0",
		"id":      1,
		"method":  "initialize",
		"params":  map[string]any{"protocolVersion": "2025-11-25", "capabilities": map[string]any{}, "clientInfo": map[string]any{"name": "test", "version": "0"}},
	})
	if denied.StatusCode != http.StatusUnauthorized {
		t.Fatalf("missing token status %d", denied.StatusCode)
	}
	denied.Body.Close()

	initResp := postMCP(t, srv.URL+"/mcp", "client-token", nil, map[string]any{
		"jsonrpc": "2.0",
		"id":      1,
		"method":  "initialize",
		"params": map[string]any{
			"protocolVersion": "2025-11-25",
			"capabilities":    map[string]any{},
			"clientInfo":      map[string]any{"name": "test", "version": "0"},
		},
	})
	defer initResp.Body.Close()
	if initResp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(initResp.Body)
		t.Fatalf("initialize %d %s", initResp.StatusCode, body)
	}
	session := initResp.Header.Get("Mcp-Session-Id")
	if session == "" {
		t.Fatal("expected session id")
	}

	callResp := postMCP(t, srv.URL+"/mcp", "client-token", map[string]string{"Mcp-Session-Id": session}, map[string]any{
		"jsonrpc": "2.0",
		"id":      2,
		"method":  "tools/call",
		"params": map[string]any{
			"name": "search",
			"arguments": map[string]any{
				"query":   "what did they spend?",
				"rewrite": true,
			},
		},
	})
	defer callResp.Body.Close()
	raw, _ := io.ReadAll(callResp.Body)
	if callResp.StatusCode != http.StatusOK {
		t.Fatalf("tools/call %d %s", callResp.StatusCode, raw)
	}
	payload := decodeMCP(t, callResp.Header.Get("Content-Type"), raw)
	result, _ := payload["result"].(map[string]any)
	if result == nil {
		t.Fatalf("response %s", raw)
	}
	if result["isError"] == true {
		t.Fatalf("tool error %s", raw)
	}
	encoded, _ := json.Marshal(result)
	if !strings.Contains(string(encoded), "doc-1") || !strings.Contains(string(encoded), "sec") {
		t.Fatalf("missing evidence in %s", encoded)
	}
	if tenant != "acme" {
		t.Fatalf("tenant %q", tenant)
	}
	if trace == "" {
		t.Fatal("trace id was not forwarded")
	}
}

func TestModernProtocolSearchRoundTrip(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/internal/mcp/search" {
			t.Errorf("unexpected path %s", r.URL.Path)
			http.NotFound(w, r)
			return
		}
		if r.Header.Get("X-Tenant-ID") != "acme" {
			t.Errorf("tenant %q", r.Header.Get("X-Tenant-ID"))
		}
		_, _ = w.Write([]byte(`{"queries":["capex"],"strategy":"hybrid","top_k":5,"results":[{"doc_id":"doc-9","source":"sec","score":0.4}]}`))
	}))
	defer upstream.Close()

	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	cfg := config.Config{
		BackendURL:    upstream.URL,
		InternalToken: "internal-token-value",
		Tokens:        map[string]string{"client-token": "acme"},
		SearchTimeout: 5 * time.Second,
	}
	mcpServer, handler := newMCP(cfg, logger)
	srv := httptest.NewServer(newHTTPMux(cfg, logger, mcpServer, handler))
	defer srv.Close()

	resp := postMCP(t, srv.URL+"/mcp", "client-token", map[string]string{
		"Mcp-Protocol-Version": "2026-07-28",
		"Mcp-Method":           "tools/call",
		"Mcp-Name":             "search",
	}, map[string]any{
		"jsonrpc": "2.0",
		"id":      1,
		"method":  "tools/call",
		"params": map[string]any{
			"name":      "search",
			"arguments": map[string]any{"query": "capex", "rewrite": false},
			"_meta": map[string]any{
				"io.modelcontextprotocol/protocolVersion": "2026-07-28",
				"io.modelcontextprotocol/clientInfo": map[string]any{
					"name": "test", "version": "0",
				},
				"io.modelcontextprotocol/clientCapabilities": map[string]any{},
			},
		},
	})
	defer resp.Body.Close()
	raw, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("status %d %s", resp.StatusCode, raw)
	}
	if !strings.Contains(string(raw), "doc-9") {
		t.Fatalf("missing evidence %s", raw)
	}
}

func postMCP(t *testing.T, url, token string, extra map[string]string, body map[string]any) *http.Response {
	t.Helper()
	raw, err := json.Marshal(body)
	if err != nil {
		t.Fatal(err)
	}
	req, err := http.NewRequest(http.MethodPost, url, bytes.NewReader(raw))
	if err != nil {
		t.Fatal(err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "application/json, text/event-stream")
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	for key, value := range extra {
		req.Header.Set(key, value)
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	return resp
}

func decodeMCP(t *testing.T, contentType string, raw []byte) map[string]any {
	t.Helper()
	text := string(raw)
	if strings.Contains(contentType, "text/event-stream") || strings.Contains(text, "data:") {
		var last map[string]any
		for _, line := range strings.Split(text, "\n") {
			line = strings.TrimSpace(line)
			if !strings.HasPrefix(line, "data:") {
				continue
			}
			chunk := strings.TrimSpace(strings.TrimPrefix(line, "data:"))
			if chunk == "" || chunk == "[DONE]" {
				continue
			}
			last = map[string]any{}
			if err := json.Unmarshal([]byte(chunk), &last); err != nil {
				t.Fatalf("sse json: %v %s", err, chunk)
			}
		}
		if last == nil {
			t.Fatalf("empty sse %s", text)
		}
		return last
	}
	var payload map[string]any
	if err := json.Unmarshal(raw, &payload); err != nil {
		t.Fatalf("json: %v %s", err, text)
	}
	return payload
}
