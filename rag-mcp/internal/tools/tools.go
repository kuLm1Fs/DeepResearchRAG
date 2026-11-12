// Package tools implements the MCP tools that front the Python retrieval core.
package tools

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/mark3labs/mcp-go/mcp"
	"github.com/mark3labs/mcp-go/server"

	"rag-mcp/internal/auth"
	"rag-mcp/internal/backend"
)

const maxIngestBytes int64 = 8 << 20

// Handler serves search, ingest, and get_document.
type Handler struct {
	Backend            backend.API
	Logger             *slog.Logger
	SearchTimeout      time.Duration
	IngestTimeout      time.Duration
	DocTimeout         time.Duration
	IngestRoot         string
	MaxFileBytes       int64
	DefaultTenant      string
	AllowDefaultTenant bool
	Notify             func(ctx context.Context, request mcp.CallToolRequest, progress, total float64, message string)
}

// NewHandler fills timeouts and the progress notifier.
func NewHandler(api backend.API, logger *slog.Logger) *Handler {
	if logger == nil {
		logger = slog.Default()
	}
	h := &Handler{
		Backend:       api,
		Logger:        logger,
		SearchTimeout: 45 * time.Second,
		IngestTimeout: 120 * time.Second,
		DocTimeout:    20 * time.Second,
		MaxFileBytes:  maxIngestBytes,
	}
	h.Notify = h.defaultNotify
	return h
}

// Register adds the three tools to an MCP server.
func (h *Handler) Register(mcpServer *server.MCPServer) {
	mcpServer.AddTool(searchTool(), h.Search)
	mcpServer.AddTool(ingestTool(), h.Ingest)
	mcpServer.AddTool(getDocumentTool(), h.GetDocument)
}

func searchTool() mcp.Tool {
	return mcp.NewTool("search",
		mcp.WithDescription("Search the finance document index for evidence chunks. Each hit includes doc_id, source, timestamp, and score. Pass doc_id to get_document to read the full text behind a citation. Results stay inside the authenticated tenant."),
		mcp.WithReadOnlyHintAnnotation(true),
		mcp.WithDestructiveHintAnnotation(false),
		mcp.WithString("query", mcp.Required(), mcp.Description("Natural-language question or search text.")),
		mcp.WithNumber("top_k", mcp.Description("Maximum number of chunks to return. Default 5, maximum 50.")),
		mcp.WithBoolean("rewrite", mcp.Description("Rewrite the query before retrieval: resolve references from context and split sub-questions. Default true. On failure the original query is used.")),
		mcp.WithString("context", mcp.Description("Optional earlier conversation used only for rewriting, for example to resolve \"they\" or \"that filing\".")),
		mcp.WithObject("filters",
			mcp.Description("Optional filters. Keys: language, category, source, published_at_from, published_at_to (unix seconds). Tenant is chosen by the server, not by this object."),
			mcp.Properties(map[string]any{
				"language":          map[string]any{"type": "string"},
				"category":          map[string]any{"type": "string"},
				"source":            map[string]any{"type": "string"},
				"published_at_from": map[string]any{"type": "integer"},
				"published_at_to":   map[string]any{"type": "integer"},
			}),
		),
	)
}

func ingestTool() mcp.Tool {
	return mcp.NewTool("ingest",
		mcp.WithDescription("Import one document into the caller's tenant dataset. The text is chunked, embedded, and stored by the existing Python ingestion pipeline. Provide exactly one of text, url, or file_path."),
		mcp.WithDestructiveHintAnnotation(false),
		mcp.WithString("text", mcp.Description("Raw document text.")),
		mcp.WithString("url", mcp.Description("Public http(s) URL to fetch. Private and loopback addresses are refused.")),
		mcp.WithString("file_path", mcp.Description("File on the MCP server. Must stay inside RAG_MCP_INGEST_ROOT.")),
		mcp.WithString("title", mcp.Description("Optional title. Defaults to the first line, the URL title, or the file name.")),
		mcp.WithString("source", mcp.Description("Optional source label, for example sec or 10-K. Default mcp.")),
		mcp.WithString("language", mcp.Description("Optional language code, for example en or zh.")),
		mcp.WithString("category", mcp.Description("Optional category. Default document.")),
	)
}

func getDocumentTool() mcp.Tool {
	return mcp.NewTool("get_document",
		mcp.WithDescription("Fetch the full text of a document by doc_id so a citation can be checked against the source. doc_id is the parent id returned by search. Documents belonging to another tenant are not returned."),
		mcp.WithReadOnlyHintAnnotation(true),
		mcp.WithDestructiveHintAnnotation(false),
		mcp.WithString("doc_id", mcp.Required(), mcp.Description("Document id returned by search.")),
	)
}

// Search rewrites the query when asked, then calls the Python retriever.
func (h *Handler) Search(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
	ctx, cancel := context.WithTimeout(ctx, h.timeout(h.SearchTimeout, 45*time.Second))
	defer cancel()
	traceID := newTraceID()
	started := time.Now()
	tenant, err := h.tenant(ctx)
	if err != nil {
		return toolError(err), nil
	}
	if err := ctx.Err(); err != nil {
		h.log(ctx, traceID, "search", tenant, started, err)
		return toolError(err), nil
	}
	query := strings.TrimSpace(request.GetString("query", ""))
	if query == "" {
		return toolError(errors.New("query is required")), nil
	}
	if len(query) > 1000 {
		return toolError(errors.New("query must be at most 1000 characters")), nil
	}
	topK := request.GetInt("top_k", 5)
	if _, present := request.GetArguments()["top_k"]; present && (topK < 1 || topK > 50) {
		return toolError(errors.New("top_k must be between 1 and 50")), nil
	}
	if topK < 1 || topK > 50 {
		topK = 5
	}
	rewrite := request.GetBool("rewrite", true)
	filters := allowedFilters(request)

	queries := []string{query}
	strategy := "hybrid"
	fallback := false
	fallbackReason := ""
	h.progress(ctx, request, 1, 3, "rewriting query")
	if rewrite {
		rewritten, rewriteErr := h.Backend.Rewrite(ctx, tenant, traceID, backend.RewriteRequest{
			Query:   query,
			Context: request.GetString("context", ""),
		})
		if rewriteErr != nil {
			if ctx.Err() != nil {
				h.log(ctx, traceID, "search", tenant, started, ctx.Err())
				return toolError(ctx.Err()), nil
			}
			fallback = true
			fallbackReason = rewriteErr.Error()
			h.Logger.Warn("rewrite_fallback",
				slog.String("trace_id", traceID),
				slog.String("tenant", tenant),
				slog.String("error", fallbackReason),
			)
		} else {
			if len(rewritten.Queries) > 0 {
				queries = rewritten.Queries
			}
			if rewritten.Strategy != "" {
				strategy = rewritten.Strategy
			}
			fallback = rewritten.RewriteFallback
			fallbackReason = rewritten.RewriteError
		}
	}

	h.progress(ctx, request, 2, 3, "searching vector, keyword, and title indexes")
	stop := h.pulse(ctx, request, "still searching")
	found, err := h.Backend.Search(ctx, tenant, traceID, backend.SearchRequest{
		Queries:  queries,
		TopK:     topK,
		Filters:  filters,
		Strategy: strategy,
	})
	stop()
	if err != nil {
		h.log(ctx, traceID, "search", tenant, started, err)
		if ctx.Err() != nil {
			return toolError(ctx.Err()), nil
		}
		return toolError(err), nil
	}
	h.progress(ctx, request, 3, 3, "done")
	h.log(ctx, traceID, "search", tenant, started, nil)
	return toolOK(map[string]any{
		"trace_id":         traceID,
		"queries":          found.Queries,
		"strategy":         found.Strategy,
		"rewrite_fallback": fallback,
		"rewrite_error":    fallbackReason,
		"results":          found.Results,
	})
}

// Ingest reads a local file when asked, then asks Python to chunk and store it.
func (h *Handler) Ingest(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
	ctx, cancel := context.WithTimeout(ctx, h.timeout(h.IngestTimeout, 120*time.Second))
	defer cancel()
	traceID := newTraceID()
	started := time.Now()
	tenant, err := h.tenant(ctx)
	if err != nil {
		return toolError(err), nil
	}
	if err := ctx.Err(); err != nil {
		h.log(ctx, traceID, "ingest", tenant, started, err)
		return toolError(err), nil
	}
	text := strings.TrimSpace(request.GetString("text", ""))
	rawURL := strings.TrimSpace(request.GetString("url", ""))
	filePath := strings.TrimSpace(request.GetString("file_path", ""))
	provided := 0
	for _, value := range []string{text, rawURL, filePath} {
		if value != "" {
			provided++
		}
	}
	if provided != 1 {
		return toolError(errors.New("provide exactly one of text, url, or file_path")), nil
	}
	title := strings.TrimSpace(request.GetString("title", ""))
	if filePath != "" {
		resolved, err := resolveIngestPath(h.IngestRoot, filePath)
		if err != nil {
			return toolError(err), nil
		}
		contents, err := readLimited(resolved, h.maxFileBytes())
		if err != nil {
			return toolError(err), nil
		}
		text = contents
		if title == "" {
			title = filepath.Base(resolved)
		}
		h.progress(ctx, request, 1, 2, "read local file")
	}
	h.progress(ctx, request, 1, 2, "chunking and embedding")
	stored, err := h.Backend.Ingest(ctx, tenant, traceID, backend.IngestRequest{
		Text:     text,
		URL:      rawURL,
		Title:    title,
		Source:   request.GetString("source", ""),
		Language: request.GetString("language", ""),
		Category: request.GetString("category", ""),
	})
	if err != nil {
		h.log(ctx, traceID, "ingest", tenant, started, err)
		if ctx.Err() != nil {
			return toolError(ctx.Err()), nil
		}
		return toolError(err), nil
	}
	h.progress(ctx, request, 2, 2, "stored")
	h.log(ctx, traceID, "ingest", tenant, started, nil)
	return toolOK(map[string]any{
		"trace_id":  traceID,
		"doc_id":    stored.DocID,
		"title":     stored.Title,
		"source":    stored.Source,
		"url":       stored.URL,
		"chunks":    stored.Chunks,
		"inserted":  stored.Inserted,
		"truncated": stored.Truncated,
	})
}

// GetDocument loads one document after the tenant check performed by the bridge.
func (h *Handler) GetDocument(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
	ctx, cancel := context.WithTimeout(ctx, h.timeout(h.DocTimeout, 20*time.Second))
	defer cancel()
	traceID := newTraceID()
	started := time.Now()
	tenant, err := h.tenant(ctx)
	if err != nil {
		return toolError(err), nil
	}
	if err := ctx.Err(); err != nil {
		h.log(ctx, traceID, "get_document", tenant, started, err)
		return toolError(err), nil
	}
	docID := strings.TrimSpace(request.GetString("doc_id", ""))
	if docID == "" {
		return toolError(errors.New("doc_id is required")), nil
	}
	document, err := h.Backend.GetDocument(ctx, tenant, traceID, docID)
	if err != nil {
		h.log(ctx, traceID, "get_document", tenant, started, err)
		if ctx.Err() != nil {
			return toolError(ctx.Err()), nil
		}
		return toolError(err), nil
	}
	h.log(ctx, traceID, "get_document", tenant, started, nil)
	return toolOK(map[string]any{
		"trace_id": traceID,
		"document": document,
	})
}

func (h *Handler) tenant(ctx context.Context) (string, error) {
	if tenant, ok := auth.TenantFromContext(ctx); ok {
		return tenant, nil
	}
	if h.AllowDefaultTenant && strings.TrimSpace(h.DefaultTenant) != "" {
		return h.DefaultTenant, nil
	}
	return "", errors.New("missing tenant")
}

func (h *Handler) timeout(configured, fallback time.Duration) time.Duration {
	if configured > 0 {
		return configured
	}
	return fallback
}

func (h *Handler) maxFileBytes() int64 {
	if h.MaxFileBytes > 0 {
		return h.MaxFileBytes
	}
	return maxIngestBytes
}

func (h *Handler) log(ctx context.Context, traceID, tool, tenant string, started time.Time, err error) {
	attrs := []any{
		slog.String("trace_id", traceID),
		slog.String("tool", tool),
		slog.String("tenant", tenant),
		slog.Duration("elapsed", time.Since(started)),
	}
	if err != nil {
		if ctx.Err() != nil {
			h.Logger.Warn("tool_cancelled", append(attrs, slog.String("error", err.Error()))...)
			return
		}
		h.Logger.Error("tool_failed", append(attrs, slog.String("error", err.Error()))...)
		return
	}
	h.Logger.Info("tool_completed", attrs...)
}

func (h *Handler) progress(ctx context.Context, request mcp.CallToolRequest, progress, total float64, message string) {
	if h.Notify == nil {
		return
	}
	h.Notify(ctx, request, progress, total, message)
}

func (h *Handler) pulse(ctx context.Context, request mcp.CallToolRequest, message string) func() {
	done := make(chan struct{})
	var once sync.Once
	go func() {
		ticker := time.NewTicker(2 * time.Second)
		defer ticker.Stop()
		for {
			select {
			case <-done:
				return
			case <-ctx.Done():
				return
			case <-ticker.C:
				h.progress(ctx, request, 2.5, 3, message)
			}
		}
	}()
	return func() { once.Do(func() { close(done) }) }
}

func (h *Handler) defaultNotify(ctx context.Context, request mcp.CallToolRequest, progress, total float64, message string) {
	token, ok := progressToken(request)
	if !ok {
		return
	}
	mcpServer := server.ServerFromContext(ctx)
	if mcpServer == nil {
		return
	}
	_ = mcpServer.SendNotificationToClient(ctx, "notifications/progress", map[string]any{
		"progress":      progress,
		"total":         total,
		"progressToken": token,
		"message":       message,
	})
}

func progressToken(request mcp.CallToolRequest) (any, bool) {
	if request.Params.Meta == nil || request.Params.Meta.ProgressToken == nil {
		return nil, false
	}
	return request.Params.Meta.ProgressToken, true
}

func allowedFilters(request mcp.CallToolRequest) map[string]any {
	raw, _ := request.GetArguments()["filters"].(map[string]any)
	if len(raw) == 0 {
		return nil
	}
	out := map[string]any{}
	for _, key := range []string{"language", "category", "source", "published_at_from", "published_at_to"} {
		if value, ok := raw[key]; ok && value != nil && value != "" {
			out[key] = value
		}
	}
	if len(out) == 0 {
		return nil
	}
	return out
}

func resolveIngestPath(root, name string) (string, error) {
	root = strings.TrimSpace(root)
	if root == "" {
		return "", errors.New("file_path requires RAG_MCP_INGEST_ROOT")
	}
	rootAbs, err := filepath.Abs(root)
	if err != nil {
		return "", err
	}
	if resolvedRoot, err := filepath.EvalSymlinks(rootAbs); err == nil {
		rootAbs = resolvedRoot
	}
	candidate := name
	if !filepath.IsAbs(candidate) {
		candidate = filepath.Join(rootAbs, name)
	}
	candidate = filepath.Clean(candidate)
	resolved := candidate
	if evaluated, err := filepath.EvalSymlinks(candidate); err == nil {
		resolved = evaluated
	} else if !os.IsNotExist(err) {
		return "", err
	}
	rel, err := filepath.Rel(rootAbs, resolved)
	if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
		return "", errors.New("file_path is outside RAG_MCP_INGEST_ROOT")
	}
	return resolved, nil
}

func readLimited(path string, maxBytes int64) (string, error) {
	file, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer file.Close()
	info, err := file.Stat()
	if err != nil {
		return "", err
	}
	if !info.Mode().IsRegular() {
		return "", errors.New("file_path is not a regular file")
	}
	if info.Size() > maxBytes {
		return "", fmt.Errorf("file exceeds %d bytes", maxBytes)
	}
	data, err := io.ReadAll(io.LimitReader(file, maxBytes+1))
	if err != nil {
		return "", err
	}
	if int64(len(data)) > maxBytes {
		return "", fmt.Errorf("file exceeds %d bytes", maxBytes)
	}
	return string(data), nil
}

func toolOK(payload any) (*mcp.CallToolResult, error) {
	raw, err := json.Marshal(payload)
	if err != nil {
		return toolError(err), nil
	}
	return &mcp.CallToolResult{
		Content: []mcp.Content{
			mcp.TextContent{Type: "text", Text: string(raw)},
		},
		StructuredContent: payload,
	}, nil
}

func toolError(err error) *mcp.CallToolResult {
	return &mcp.CallToolResult{
		Content: []mcp.Content{
			mcp.TextContent{Type: "text", Text: err.Error()},
		},
		IsError: true,
	}
}

func newTraceID() string {
	buf := make([]byte, 16)
	if _, err := rand.Read(buf); err != nil {
		return fmt.Sprintf("trace-%d", time.Now().UnixNano())
	}
	return hex.EncodeToString(buf)
}
