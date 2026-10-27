package common

import (
	"net/http"
	"net/http/httptest"
	"reflect"
	"strings"
	"testing"
)

func TestActveroNamespaceCanonical(t *testing.T) {
	owner := "00000000-0000-4000-8000-000000000001"
	prefix, ok := ActveroNamespace(owner)
	if !ok || len(prefix) != 38 {
		t.Fatal("namespace")
	}
	for _, invalid := range []string{strings.ReplaceAll(owner, "-", ""), "other", owner + "/../other"} {
		if _, ok := ActveroNamespace(invalid); ok {
			t.Fatal("accepted noncanonical organization")
		}
	}
	actual, name := ActveroSplitName(prefix + "model")
	if actual != prefix || name != "model" {
		t.Fatal("roundtrip")
	}
}
func TestActveroEgressPrivateTarget(t *testing.T) {
	t.Setenv("ACTVERO_ORGANIZATION_ISOLATION", "true")
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(204) }))
	defer server.Close()
	transport := http.DefaultTransport.(*http.Transport).Clone()
	ActveroSecureTransport(transport)
	defer transport.CloseIdleConnections()
	client := http.Client{Transport: transport}
	if response, err := client.Get(server.URL); err == nil {
		response.Body.Close()
		t.Fatal("private destination accepted")
	}
	// Opt-in is an exact host and port, not a wildcard over an entire internal host.
	t.Setenv("ACTVERO_EGRESS_PRIVATE_TARGETS", strings.TrimPrefix(server.URL, "http://"))
	response, err := client.Get(server.URL)
	if err != nil {
		t.Fatal(err)
	}
	response.Body.Close()
	if response.StatusCode != 204 {
		t.Fatal("fixture")
	}
}

func TestActveroNamespaceKeepsEndpointCapabilities(t *testing.T) {
	prefix, _ := ActveroNamespace("00000000-0000-4000-8000-000000000001")
	for _, kind := range []int{1, 14, 24, 43} {
		for _, name := range []string{"gpt-4o", "text-embedding-3-small", "gpt-image-1", "whisper-1", "tts-1", "deepseek-chat"} {
			if !reflect.DeepEqual(GetEndpointTypesByChannelType(kind, name), GetEndpointTypesByChannelType(kind, prefix+name)) {
				t.Fatal("namespace changed protocol capabilities", kind, name)
			}
		}
	}
}
