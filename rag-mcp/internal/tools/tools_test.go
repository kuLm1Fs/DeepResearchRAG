package tools

import (
	"context"
	"errors"
	"log/slog"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/mark3labs/mcp-go/mcp"

	"rag-mcp/internal/auth"
	"rag-mcp/internal/backend"
)

type fakeBackend struct {
	rewrite func(ctx context.Context, tenant, trace string, in backend.RewriteRequest) (backend.RewriteResponse, error)
	search  func(ctx context.Context, tenant, trace string, in backend.SearchRequest) (backend.SearchResponse, error)
	ingest  func(ctx context.Context, tenant, trace string, in backend.IngestRequest) (backend.IngestResponse, error)
	get     func(ctx context.Context, tenant, trace, docID string) (backend.Document, error)
}

func (f fakeBackend) Rewrite(ctx context.Context, tenant, trace string, in backend.RewriteRequest) (backend.RewriteResponse, error) {
	return f.rewrite(ctx, tenant, trace, in)
}

func (f fakeBackend) Search(ctx context.Context, tenant, trace string, in backend.SearchRequest) (backend.SearchResponse, error) {
	return f.search(ctx, tenant, trace, in)
}

func (f fakeBackend) Ingest(ctx context.Context, tenant, trace string, in backend.IngestRequest) (backend.IngestResponse, error) {
	return f.ingest(ctx, tenant, trace, in)
}

func (f fakeBackend) GetDocument(ctx context.Context, tenant, trace, docID string) (backend.Document, error) {
	return f.get(ctx, tenant, trace, docID)
}

func testHandler(api backend.API) *Handler {
	logger := slog.New(slog.NewTextHandler(os.Stderr, &slog.HandlerOptions{Level: slog.LevelError}))
	h := NewHandler(api, logger)
	h.AllowDefaultTenant = true
	h.DefaultTenant = "local"
	h.SearchTimeout = time.Second
	h.IngestTimeout = time.Second
	h.DocTimeout = time.Second
	return h
}

func callArgs(args map[string]any) mcp.CallToolRequest {
	return mcp.CallToolRequest{
		Params: mcp.CallToolParams{Arguments: args},
	}
}

func TestSearchUsesRewriteThenOriginalTenant(t *testing.T) {
	var got backend.SearchRequest
	var gotTenant string
	notes := []string{}
	h := testHandler(fakeBackend{
		rewrite: func(ctx context.Context, tenant, trace string, in backend.RewriteRequest) (backend.RewriteResponse, error) {
			if in.Context != "earlier turn about 3M" {
				t.Fatalf("context %q", in.Context)
			}
			return backend.RewriteResponse{
				Queries:  []string{"3M FY2018 capital expenditure", "3M cash flow 2018"},
				Strategy: "hybrid",
			}, nil
		},
		search: func(ctx context.Context, tenant, trace string, in backend.SearchRequest) (backend.SearchResponse, error) {
			got = in
			gotTenant = tenant
			if trace == "" {
				t.Fatal("missing trace id")
			}
			stamp := "2024-01-02T00:00:00Z"
			return backend.SearchResponse{
				Queries:  in.Queries,
				Strategy: in.Strategy,
				TopK:     in.TopK,
				Results: []backend.Evidence{{
					DocID:     "doc-1",
					Source:    "sec",
					Score:     0.8,
					Timestamp: &stamp,
					Content:   "Purchases of PP&E (1,577)",
				}},
			}, nil
		},
	})
	h.Notify = func(ctx context.Context, request mcp.CallToolRequest, progress, total float64, message string) {
		notes = append(notes, message)
	}
	ctx := auth.WithTenant(context.Background(), "acme")
	result, err := h.Search(ctx, callArgs(map[string]any{
		"query":   "what did they spend?",
		"top_k":   3,
		"context": "earlier turn about 3M",
		"filters": map[string]any{"company_id": "other", "language": "en", "source": "sec"},
	}))
	if err != nil {
		t.Fatal(err)
	}
	if result.IsError {
		t.Fatalf("tool error %#v", result.Content)
	}
	if gotTenant != "acme" {
		t.Fatalf("tenant %s", gotTenant)
	}
	if len(got.Queries) != 2 || got.Queries[0] != "3M FY2018 capital expenditure" {
		t.Fatalf("queries %#v", got.Queries)
	}
	if _, leaked := got.Filters["company_id"]; leaked {
		t.Fatalf("tenant filter leaked into backend request: %#v", got.Filters)
	}
	if got.Filters["language"] != "en" || got.Filters["source"] != "sec" {
		t.Fatalf("filters %#v", got.Filters)
	}
	payload, _ := result.StructuredContent.(map[string]any)
	results, _ := payload["results"].([]backend.Evidence)
	if len(results) != 1 || results[0].DocID != "doc-1" || results[0].Source != "sec" {
		t.Fatalf("payload %#v", payload)
	}
	if len(notes) < 3 {
		t.Fatalf("progress notes %#v", notes)
	}
}

func TestSearchFallsBackWhenRewriteFails(t *testing.T) {
	var queries []string
	h := testHandler(fakeBackend{
		rewrite: func(ctx context.Context, tenant, trace string, in backend.RewriteRequest) (backend.RewriteResponse, error) {
			return backend.RewriteResponse{}, errors.New("analyzer down")
		},
		search: func(ctx context.Context, tenant, trace string, in backend.SearchRequest) (backend.SearchResponse, error) {
			queries = in.Queries
			return backend.SearchResponse{Queries: in.Queries, Strategy: in.Strategy, Results: []backend.Evidence{}}, nil
		},
	})
	h.Notify = func(ctx context.Context, request mcp.CallToolRequest, progress, total float64, message string) {}
	result, err := h.Search(context.Background(), callArgs(map[string]any{"query": "original question"}))
	if err != nil || result.IsError {
		t.Fatalf("err %v result %#v", err, result)
	}
	if len(queries) != 1 || queries[0] != "original question" {
		t.Fatalf("queries %#v", queries)
	}
	payload := result.StructuredContent.(map[string]any)
	if payload["rewrite_fallback"] != true {
		t.Fatalf("fallback flag %#v", payload["rewrite_fallback"])
	}
}

func TestSearchDoesNotRetryWhenRetrievalFails(t *testing.T) {
	calls := 0
	h := testHandler(fakeBackend{
		rewrite: func(ctx context.Context, tenant, trace string, in backend.RewriteRequest) (backend.RewriteResponse, error) {
			return backend.RewriteResponse{Queries: []string{"rewritten"}}, nil
		},
		search: func(ctx context.Context, tenant, trace string, in backend.SearchRequest) (backend.SearchResponse, error) {
			calls++
			return backend.SearchResponse{}, errors.New("milvus down")
		},
	})
	h.Notify = func(ctx context.Context, request mcp.CallToolRequest, progress, total float64, message string) {}
	result, err := h.Search(context.Background(), callArgs(map[string]any{"query": "capex"}))
	if err != nil {
		t.Fatal(err)
	}
	if !result.IsError {
		t.Fatal("expected tool error")
	}
	if calls != 1 {
		t.Fatalf("search calls %d", calls)
	}
}

func TestSearchCancelledContextDoesNotCallBackend(t *testing.T) {
	h := testHandler(fakeBackend{
		rewrite: func(ctx context.Context, tenant, trace string, in backend.RewriteRequest) (backend.RewriteResponse, error) {
			t.Fatal("rewrite should not run")
			return backend.RewriteResponse{}, nil
		},
		search: func(ctx context.Context, tenant, trace string, in backend.SearchRequest) (backend.SearchResponse, error) {
			t.Fatal("search should not run")
			return backend.SearchResponse{}, nil
		},
	})
	h.Notify = func(ctx context.Context, request mcp.CallToolRequest, progress, total float64, message string) {}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	result, err := h.Search(ctx, callArgs(map[string]any{"query": "capex", "rewrite": false}))
	if err != nil {
		t.Fatal(err)
	}
	if !result.IsError {
		t.Fatal("expected cancellation error")
	}
}

func TestIngestFileIsSandboxed(t *testing.T) {
	root := t.TempDir()
	if err := os.WriteFile(filepath.Join(root, "note.txt"), []byte("revenue was 10"), 0o644); err != nil {
		t.Fatal(err)
	}
	outside := filepath.Join(t.TempDir(), "secret.txt")
	if err := os.WriteFile(outside, []byte("secret"), 0o644); err != nil {
		t.Fatal(err)
	}

	var got backend.IngestRequest
	h := testHandler(fakeBackend{
		ingest: func(ctx context.Context, tenant, trace string, in backend.IngestRequest) (backend.IngestResponse, error) {
			got = in
			if tenant != "local" {
				t.Fatalf("tenant %s", tenant)
			}
			return backend.IngestResponse{DocID: "doc-9", Title: in.Title, Chunks: 1, Inserted: 1}, nil
		},
	})
	h.IngestRoot = root
	h.Notify = func(ctx context.Context, request mcp.CallToolRequest, progress, total float64, message string) {}

	result, err := h.Ingest(context.Background(), callArgs(map[string]any{"file_path": "note.txt"}))
	if err != nil || result.IsError {
		t.Fatalf("err %v %#v", err, result)
	}
	if got.Text != "revenue was 10" || got.Title != "note.txt" || got.URL != "" {
		t.Fatalf("ingest %#v", got)
	}

	escaped, err := h.Ingest(context.Background(), callArgs(map[string]any{"file_path": outside}))
	if err != nil {
		t.Fatal(err)
	}
	if !escaped.IsError {
		t.Fatal("expected path escape to fail")
	}

	missing, err := h.Ingest(context.Background(), callArgs(map[string]any{"text": "a", "url": "https://example.com"}))
	if err != nil || !missing.IsError {
		t.Fatal("expected exactly-one validation error")
	}
}

func TestGetDocumentPassesTenant(t *testing.T) {
	h := testHandler(fakeBackend{
		get: func(ctx context.Context, tenant, trace, docID string) (backend.Document, error) {
			if tenant != "acme" || docID != "doc-1" {
				t.Fatalf("tenant %s doc %s", tenant, docID)
			}
			return backend.Document{DocID: docID, Source: "sec", Text: "full filing"}, nil
		},
	})
	ctx := auth.WithTenant(context.Background(), "acme")
	result, err := h.GetDocument(ctx, callArgs(map[string]any{"doc_id": "doc-1"}))
	if err != nil || result.IsError {
		t.Fatalf("err %v %#v", err, result)
	}
	document := result.StructuredContent.(map[string]any)["document"].(backend.Document)
	if document.Text != "full filing" || document.Source != "sec" {
		t.Fatalf("document %#v", document)
	}
}

func TestHTTPModeRefusesImplicitTenant(t *testing.T) {
	h := testHandler(fakeBackend{})
	h.AllowDefaultTenant = false
	result, err := h.GetDocument(context.Background(), callArgs(map[string]any{"doc_id": "doc-1"}))
	if err != nil || !result.IsError {
		t.Fatal("expected missing tenant error")
	}
}
