.PHONY: build test run-stdio run-http up

BINARY := bin/rag-mcp

build:
	go build -o $(BINARY) ./cmd/rag-mcp

test:
	go test ./...

run-stdio: build
	./$(BINARY) -transport stdio

run-http: build
	./$(BINARY) -transport http -addr $${RAG_MCP_ADDR:-:8081}

up:
	docker compose up --build
