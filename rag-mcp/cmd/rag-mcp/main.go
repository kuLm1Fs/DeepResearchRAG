package main

import (
	"context"
	"errors"
	"flag"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"github.com/mark3labs/mcp-go/server"

	"rag-mcp/internal/auth"
	"rag-mcp/internal/backend"
	"rag-mcp/internal/config"
	"rag-mcp/internal/tools"
)

func main() {
	logger := newLogger(os.Getenv("LOG_LEVEL"))
	slog.SetDefault(logger)
	if err := run(os.Args[1:], logger); err != nil {
		logger.Error("server_stopped", slog.String("error", err.Error()))
		os.Exit(1)
	}
}

func run(args []string, logger *slog.Logger) error {
	fs := flag.NewFlagSet("rag-mcp", flag.ContinueOnError)
	fs.SetOutput(os.Stderr)
	transport := fs.String("transport", "", "stdio (local process) or http (Streamable HTTP)")
	addr := fs.String("addr", "", "listen address for http transport, for example :8081")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if *transport != "" {
		_ = os.Setenv("RAG_MCP_TRANSPORT", *transport)
	}
	if *addr != "" {
		_ = os.Setenv("RAG_MCP_ADDR", *addr)
	}

	cfg, err := config.FromEnv()
	if err != nil {
		return err
	}
	logger = newLogger(cfg.LogLevel)
	slog.SetDefault(logger)

	mcpServer, handler := newMCP(cfg, logger)

	if cfg.Transport == "stdio" {
		handler.AllowDefaultTenant = true
		handler.DefaultTenant = cfg.Tenant
		logger.Info("stdio_starting",
			slog.String("backend", cfg.BackendURL),
			slog.String("tenant", cfg.Tenant),
		)
		return server.ServeStdio(mcpServer)
	}

	httpServer := &http.Server{
		Addr:              cfg.Addr,
		Handler:           newHTTPMux(cfg, logger, mcpServer, handler),
		ReadHeaderTimeout: 10 * time.Second,
		IdleTimeout:       2 * time.Minute,
	}
	errCh := make(chan error, 1)
	go func() {
		logger.Info("http_listening", slog.String("addr", cfg.Addr), slog.String("path", "/mcp"))
		errCh <- httpServer.ListenAndServe()
	}()

	sig := make(chan os.Signal, 1)
	signal.Notify(sig, syscall.SIGINT, syscall.SIGTERM)
	select {
	case err := <-errCh:
		if errors.Is(err, http.ErrServerClosed) {
			return nil
		}
		return err
	case <-sig:
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		return httpServer.Shutdown(ctx)
	}
}

func newMCP(cfg config.Config, logger *slog.Logger) (*server.MCPServer, *tools.Handler) {
	mcpServer := server.NewMCPServer(
		"rag-finance",
		"0.1.0",
		server.WithToolCapabilities(true),
		server.WithInstructions("Finance document retrieval. search returns evidence chunks with doc_id, source, timestamp, and score. get_document loads the full text for a doc_id. ingest adds one document to the current tenant. Tenant isolation is enforced by the server."),
	)
	handler := tools.NewHandler(backend.NewClient(cfg.BackendURL, cfg.InternalToken), logger)
	handler.SearchTimeout = cfg.SearchTimeout
	handler.IngestTimeout = cfg.IngestTimeout
	handler.DocTimeout = cfg.DocTimeout
	handler.IngestRoot = cfg.IngestRoot
	handler.Register(mcpServer)
	return mcpServer, handler
}

func newHTTPMux(cfg config.Config, logger *slog.Logger, mcpServer *server.MCPServer, handler *tools.Handler) http.Handler {
	handler.AllowDefaultTenant = false
	authenticator := auth.NewAuthenticator(cfg.Tokens)
	streamable := server.NewStreamableHTTPServer(
		mcpServer,
		server.WithEndpointPath("/mcp"),
		server.WithStateful(true),
		server.WithHTTPContextFunc(authenticator.ContextFunc),
		server.WithStreamableHTTPLogger(logger),
		server.WithMaxRequestBodyBytes(10<<20),
	)
	mux := http.NewServeMux()
	mux.Handle("/mcp", authenticator.Wrap(streamable))
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"status":"ok"}`))
	})
	return mux
}

func newLogger(level string) *slog.Logger {
	var parsed slog.Level
	switch strings.ToUpper(strings.TrimSpace(level)) {
	case "DEBUG":
		parsed = slog.LevelDebug
	case "WARN", "WARNING":
		parsed = slog.LevelWarn
	case "ERROR":
		parsed = slog.LevelError
	default:
		parsed = slog.LevelInfo
	}
	return slog.New(slog.NewJSONHandler(os.Stderr, &slog.HandlerOptions{Level: parsed}))
}
