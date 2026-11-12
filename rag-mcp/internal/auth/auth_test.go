package auth

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestAuthenticateIsolatesTenants(t *testing.T) {
	a := NewAuthenticator(map[string]string{
		"token-acme":  "acme",
		"token-other": "other",
	})
	tenant, err := a.Authenticate("Bearer token-acme")
	if err != nil || tenant != "acme" {
		t.Fatalf("acme token: %q %v", tenant, err)
	}
	if _, err := a.Authenticate("Bearer token-other"); err != nil {
		t.Fatal(err)
	}
	if _, err := a.Authenticate("Bearer no-such-token"); err == nil {
		t.Fatal("expected unknown token to fail")
	}
	if _, err := a.Authenticate(""); err == nil {
		t.Fatal("expected missing header to fail")
	}
}

func TestWrapSetsTenantAndRejectsMissingToken(t *testing.T) {
	a := NewAuthenticator(map[string]string{"token-acme": "acme"})
	var seen string
	handler := a.Wrap(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		tenant, ok := TenantFromContext(r.Context())
		if !ok {
			t.Fatal("tenant missing from context")
		}
		seen = tenant
		w.WriteHeader(http.StatusNoContent)
	}))

	denied := httptest.NewRequest(http.MethodPost, "/mcp", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, denied)
	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("status %d", rec.Code)
	}

	allowed := httptest.NewRequest(http.MethodPost, "/mcp", nil)
	allowed.Header.Set("Authorization", "Bearer token-acme")
	rec = httptest.NewRecorder()
	handler.ServeHTTP(rec, allowed)
	if rec.Code != http.StatusNoContent {
		t.Fatalf("status %d", rec.Code)
	}
	if seen != "acme" {
		t.Fatalf("tenant %q", seen)
	}
}
