// Package backend calls the Python retrieval and ingest bridge.
package backend

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
)

// Evidence is one retrieved chunk.
type Evidence struct {
	DocID       string  `json:"doc_id"`
	ChunkID     string  `json:"chunk_id"`
	ID          string  `json:"id"`
	Title       string  `json:"title"`
	Content     string  `json:"content"`
	Source      string  `json:"source"`
	URL         string  `json:"url"`
	Timestamp   *string `json:"timestamp"`
	PublishedAt int64   `json:"published_at"`
	Score       float64 `json:"score"`
	Language    string  `json:"language"`
	Category    string  `json:"category"`
}

// RewriteRequest is the optional query-analysis call.
type RewriteRequest struct {
	Query   string `json:"query"`
	Context string `json:"context,omitempty"`
}

// RewriteResponse is analyze_query output, or a fallback to the original query.
type RewriteResponse struct {
	Queries         []string `json:"queries"`
	Strategy        string   `json:"strategy"`
	Intent          string   `json:"intent"`
	Keywords        []string `json:"keywords"`
	RewriteApplied  bool     `json:"rewrite_applied"`
	RewriteFallback bool     `json:"rewrite_fallback"`
	RewriteError    string   `json:"rewrite_error"`
}

// SearchRequest asks the Python retriever to run the given queries.
type SearchRequest struct {
	Queries  []string       `json:"queries"`
	TopK     int            `json:"top_k"`
	Filters  map[string]any `json:"filters,omitempty"`
	Strategy string         `json:"strategy,omitempty"`
}

// SearchResponse is the fused evidence list.
type SearchResponse struct {
	Queries  []string   `json:"queries"`
	Strategy string     `json:"strategy"`
	TopK     int        `json:"top_k"`
	Results  []Evidence `json:"results"`
}

// IngestRequest imports one document. Exactly one of Text or URL is set.
type IngestRequest struct {
	Text     string `json:"text,omitempty"`
	URL      string `json:"url,omitempty"`
	Title    string `json:"title,omitempty"`
	Source   string `json:"source,omitempty"`
	Language string `json:"language,omitempty"`
	Category string `json:"category,omitempty"`
}

// IngestResponse identifies the stored document.
type IngestResponse struct {
	DocID     string `json:"doc_id"`
	Title     string `json:"title"`
	Source    string `json:"source"`
	URL       string `json:"url"`
	Chunks    int    `json:"chunks"`
	Inserted  int    `json:"inserted"`
	Truncated bool   `json:"truncated"`
}

// Document is the full text assembled from a document's chunks.
type Document struct {
	DocID       string  `json:"doc_id"`
	Title       string  `json:"title"`
	Source      string  `json:"source"`
	URL         string  `json:"url"`
	Timestamp   *string `json:"timestamp"`
	PublishedAt int64   `json:"published_at"`
	Text        string  `json:"text"`
	Chunks      []struct {
		ChunkID string `json:"chunk_id"`
		Content string `json:"content"`
	} `json:"chunks"`
}

// API is the subset of the Python bridge the tool handlers depend on.
type API interface {
	Rewrite(ctx context.Context, tenant, traceID string, in RewriteRequest) (RewriteResponse, error)
	Search(ctx context.Context, tenant, traceID string, in SearchRequest) (SearchResponse, error)
	Ingest(ctx context.Context, tenant, traceID string, in IngestRequest) (IngestResponse, error)
	GetDocument(ctx context.Context, tenant, traceID, docID string) (Document, error)
}

// Client is an HTTP client for /api/internal/mcp.
type Client struct {
	BaseURL string
	Token   string
	HTTP    *http.Client
}

// NewClient returns a client that uses per-request deadlines from ctx.
func NewClient(baseURL, token string) *Client {
	return &Client{
		BaseURL: strings.TrimRight(baseURL, "/"),
		Token:   token,
		HTTP:    &http.Client{Timeout: 0},
	}
}

// Rewrite calls analyze_query. A non-200 response is returned as an error so
// the tool handler can search with the original query.
func (c *Client) Rewrite(ctx context.Context, tenant, traceID string, in RewriteRequest) (RewriteResponse, error) {
	var out RewriteResponse
	err := c.do(ctx, http.MethodPost, "/api/internal/mcp/rewrite", tenant, traceID, in, &out)
	return out, err
}

// Search runs multi-path retrieval for one tenant.
func (c *Client) Search(ctx context.Context, tenant, traceID string, in SearchRequest) (SearchResponse, error) {
	var out SearchResponse
	err := c.do(ctx, http.MethodPost, "/api/internal/mcp/search", tenant, traceID, in, &out)
	return out, err
}

// Ingest chunks, embeds, and stores one document.
func (c *Client) Ingest(ctx context.Context, tenant, traceID string, in IngestRequest) (IngestResponse, error) {
	var out IngestResponse
	err := c.do(ctx, http.MethodPost, "/api/internal/mcp/ingest", tenant, traceID, in, &out)
	return out, err
}

// GetDocument loads the full text of one document in the tenant.
func (c *Client) GetDocument(ctx context.Context, tenant, traceID, docID string) (Document, error) {
	var out Document
	path := "/api/internal/mcp/documents/" + url.PathEscape(docID)
	err := c.do(ctx, http.MethodGet, path, tenant, traceID, nil, &out)
	return out, err
}

func (c *Client) do(ctx context.Context, method, path, tenant, traceID string, in any, out any) error {
	var body io.Reader
	if in != nil {
		payload, err := json.Marshal(in)
		if err != nil {
			return err
		}
		body = bytes.NewReader(payload)
	}
	if ctx == nil {
		ctx = context.Background()
	}
	req, err := http.NewRequestWithContext(ctx, method, c.BaseURL+path, body)
	if err != nil {
		return err
	}
	req.Header.Set("Authorization", "Bearer "+c.Token)
	req.Header.Set("X-Tenant-ID", tenant)
	req.Header.Set("X-Trace-ID", traceID)
	req.Header.Set("Accept", "application/json")
	if in != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	client := c.HTTP
	if client == nil {
		client = http.DefaultClient
	}
	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	raw, err := io.ReadAll(io.LimitReader(resp.Body, 8<<20))
	if err != nil {
		return err
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		message := strings.TrimSpace(string(raw))
		if message == "" {
			message = resp.Status
		}
		return &StatusError{Status: resp.StatusCode, Body: message}
	}
	if out == nil || len(raw) == 0 {
		return nil
	}
	if err := json.Unmarshal(raw, out); err != nil {
		return fmt.Errorf("decode %s: %w", path, err)
	}
	return nil
}

// StatusError is a non-2xx response from the Python bridge.
type StatusError struct {
	Status int
	Body   string
}

func (e *StatusError) Error() string {
	return fmt.Sprintf("backend status %d: %s", e.Status, e.Body)
}
