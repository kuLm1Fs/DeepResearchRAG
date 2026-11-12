package config

import "testing"

func TestParseTokenMap(t *testing.T) {
	got, err := ParseTokenMap("alpha-token=acme, beta-token=other")
	if err != nil {
		t.Fatal(err)
	}
	if got["alpha-token"] != "acme" || got["beta-token"] != "other" {
		t.Fatalf("parsed %#v", got)
	}

	got, err = ParseTokenMap(`{"alpha-token":"acme"}`)
	if err != nil {
		t.Fatal(err)
	}
	if got["alpha-token"] != "acme" {
		t.Fatalf("json parsed %#v", got)
	}

	if _, err := ParseTokenMap("short=acme"); err == nil {
		t.Fatal("expected short token to be rejected")
	}
	if _, err := ParseTokenMap("alpha-token=bad tenant"); err == nil {
		t.Fatal("expected whitespace tenant to be rejected")
	}
}
