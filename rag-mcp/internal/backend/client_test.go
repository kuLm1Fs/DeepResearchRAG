package backend

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestClientSendsTenantTraceAndToken(t *testing.T) {
	var got SearchRequest
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer internal-token" {
			t.Errorf("auth %q", r.Header.Get("Authorization"))
		}
		if r.Header.Get("X-Tenant-ID") != "acme" {
			t.Errorf("tenant %q", r.Header.Get("X-Tenant-ID"))
		}
		if r.Header.Get("X-Trace-ID") != "trace-1" {
			t.Errorf("trace %q", r.Header.Get("X-Trace-ID"))
		}
		if r.URL.Path != "/api/internal/mcp/search" {
			t.Errorf("path %s", r.URL.Path)
		}
		body, _ := io.ReadAll(r.Body)
		if err := jsonUnmarshal(body, &got); err != nil {
			t.Fatal(err)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"queries":["q"],"strategy":"hybrid","top_k":2,"results":[{"doc_id":"d1","source":"sec","score":0.5,"timestamp":"2024-01-01T00:00:00Z"}]}`))
	}))
	defer srv.Close()

	client := NewClient(srv.URL, "internal-token")
	resp, err := client.Search(context.Background(), "acme", "trace-1", SearchRequest{
		Queries: []string{"q"},
		TopK:    2,
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(resp.Results) != 1 || resp.Results[0].DocID != "d1" || resp.Results[0].Source != "sec" {
		t.Fatalf("results %#v", resp.Results)
	}
	if got.TopK != 2 || len(got.Queries) != 1 {
		t.Fatalf("forwarded %#v", got)
	}
}

func TestClientReturnsStatusError(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "retrieval failed", http.StatusServiceUnavailable)
	}))
	defer srv.Close()

	client := NewClient(srv.URL, "internal-token")
	_, err := client.GetDocument(context.Background(), "acme", "trace-1", "doc/1")
	if err == nil {
		t.Fatal("expected status error")
	}
	status, ok := err.(*StatusError)
	if !ok || status.Status != http.StatusServiceUnavailable {
		t.Fatalf("error %#v", err)
	}
}

func TestCancelledContextAbortsRequest(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	_, err := NewClient("http://127.0.0.1:1", "tok").Search(ctx, "acme", "t", SearchRequest{
		Queries: []string{"q"},
		TopK:    1,
	})
	if err == nil {
		t.Fatal("expected cancellation error")
	}
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("error %v", err)
	}
}

func jsonUnmarshal(raw []byte, dest any) error {
	return json.NewDecoder(bytes.NewReader(raw)).Decode(dest)
}
