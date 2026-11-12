// Package auth maps bearer tokens to tenants and stores the tenant on a context.
package auth

import (
	"context"
	"crypto/subtle"
	"net/http"
	"strings"
)

type tenantKey struct{}

// WithTenant returns a context that carries the authenticated tenant.
func WithTenant(ctx context.Context, tenant string) context.Context {
	return context.WithValue(ctx, tenantKey{}, tenant)
}

// TenantFromContext returns the tenant set by HTTP authentication.
func TenantFromContext(ctx context.Context) (string, bool) {
	tenant, ok := ctx.Value(tenantKey{}).(string)
	return tenant, ok && tenant != ""
}

// Authenticator accepts the bearer tokens configured for this process.
type Authenticator struct {
	tokens map[string]string
}

// NewAuthenticator copies the token to tenant map.
func NewAuthenticator(tokens map[string]string) *Authenticator {
	copied := make(map[string]string, len(tokens))
	for token, tenant := range tokens {
		copied[token] = tenant
	}
	return &Authenticator{tokens: copied}
}

// Authenticate returns the tenant for an Authorization header.
func (a *Authenticator) Authenticate(header string) (string, error) {
	token := bearerToken(header)
	if token == "" {
		return "", errUnauthorized
	}
	var (
		tenant string
		found  bool
	)
	for candidate, name := range a.tokens {
		if subtle.ConstantTimeCompare([]byte(candidate), []byte(token)) == 1 {
			tenant = name
			found = true
		}
	}
	if !found {
		return "", errUnauthorized
	}
	return tenant, nil
}

// Wrap rejects requests that do not carry a configured bearer token and
// stores the tenant on the request context.
func (a *Authenticator) Wrap(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		tenant, err := a.Authenticate(r.Header.Get("Authorization"))
		if err != nil {
			w.Header().Set("WWW-Authenticate", `Bearer realm="rag-mcp"`)
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
		next.ServeHTTP(w, r.WithContext(WithTenant(r.Context(), tenant)))
	})
}

// ContextFunc is the mcp-go HTTP context hook. It re-reads the bearer token
// so the tenant is present on the context the tool handler actually sees.
func (a *Authenticator) ContextFunc(ctx context.Context, r *http.Request) context.Context {
	tenant, err := a.Authenticate(r.Header.Get("Authorization"))
	if err != nil {
		return ctx
	}
	return WithTenant(ctx, tenant)
}

func bearerToken(header string) string {
	const prefix = "bearer "
	if len(header) < len(prefix) || !strings.EqualFold(header[:len(prefix)], prefix) {
		return ""
	}
	return strings.TrimSpace(header[len(prefix):])
}

type unauthorizedError struct{}

func (unauthorizedError) Error() string { return "unauthorized" }

var errUnauthorized = unauthorizedError{}
