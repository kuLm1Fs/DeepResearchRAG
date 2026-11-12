FROM golang:1.25.5 AS build

WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/rag-mcp ./cmd/rag-mcp

FROM gcr.io/distroless/static-debian12
COPY --from=build /out/rag-mcp /rag-mcp
USER 65532:65532
EXPOSE 8081
ENTRYPOINT ["/rag-mcp"]
CMD ["-transport", "http", "-addr", ":8081"]
