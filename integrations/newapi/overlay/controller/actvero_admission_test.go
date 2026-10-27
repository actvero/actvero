package controller

import (
	"bytes"
	"encoding/base64"
	"image"
	"image/png"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"

	"github.com/QuantumNous/new-api/common"
	"github.com/QuantumNous/new-api/constant"
	"github.com/QuantumNous/new-api/relaykit/dto"
	"github.com/QuantumNous/new-api/tokenkit"
	"github.com/gin-gonic/gin"
)

func actveroAdmissionChat(t *testing.T, content any) *dto.GeneralOpenAIRequest {
	t.Helper()
	body, err := common.Marshal(map[string]any{
		"stream":   true,
		"messages": []any{map[string]any{"role": "user", "content": content}},
		"tools": []any{map[string]any{"type": "function", "function": map[string]any{
			"name": "lookup", "description": "Look up a record", "parameters": map[string]any{"type": "object"},
		}}},
	})
	if err != nil {
		t.Fatal(err)
	}
	var chat dto.GeneralOpenAIRequest
	if err := common.Unmarshal(body, &chat); err != nil {
		t.Fatal(err)
	}
	return &chat
}

func actveroAdmissionContext() *gin.Context {
	c, _ := gin.CreateTestContext(httptest.NewRecorder())
	c.Request = httptest.NewRequest(http.MethodPost, "/", nil)
	return c
}

func TestActveroAdmissionInlineImages(t *testing.T) {
	previous := constant.GetMediaToken
	constant.GetMediaToken = true
	t.Cleanup(func() { constant.GetMediaToken = previous })
	var encoded bytes.Buffer
	if err := png.Encode(&encoded, image.NewRGBA(image.Rect(0, 0, 32, 64))); err != nil {
		t.Fatal(err)
	}
	url := "data:image/png;base64," + base64.StdEncoding.EncodeToString(encoded.Bytes())
	text := map[string]any{"type": "text", "text": "Describe this image"}
	imagePart := map[string]any{"type": "image_url", "image_url": map[string]any{"url": url}}
	for _, modelName := range []string{"deepseek-flash", "gpt-4o", "claude-sonnet-4-5"} {
		t.Run(modelName, func(t *testing.T) {
			baseline, _, err := actveroAdmissionInput(actveroAdmissionContext(), actveroAdmissionChat(t, []any{text}), modelName, 1000000)
			if err != nil {
				t.Fatal(err)
			}
			count, source, err := actveroAdmissionInput(actveroAdmissionContext(), actveroAdmissionChat(t, []any{text, imagePart, imagePart}), modelName, 1000000)
			want := baseline + 2*tokenkit.ImageTokens(modelName, tokenkit.Image{Width: 32, Height: 64})
			if err != nil || source != "native_token_estimate" || count != want || count >= 1000000 {
				t.Fatalf("count=%d, want=%d, source=%q, err=%v", count, want, source, err)
			}
		})
	}
}

func TestActveroAdmissionRemoteMediaKeepsCapacityWithoutFetching(t *testing.T) {
	var hits atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { hits.Add(1) }))
	t.Cleanup(server.Close)
	for _, content := range []any{
		[]any{map[string]any{"type": "image_url", "image_url": map[string]any{"url": server.URL + "/private.png"}}},
		[]any{map[string]any{"type": "input_audio", "input_audio": map[string]any{"data": "AAAA", "format": "wav"}}},
	} {
		count, source, err := actveroAdmissionInput(actveroAdmissionContext(), actveroAdmissionChat(t, content), "gpt-4o", 1000000)
		if err != nil || count != 1000000 || source != "capacity_bound" {
			t.Fatalf("count=%d, source=%q, err=%v", count, source, err)
		}
	}
	if hits.Load() != 0 {
		t.Fatal("admission fetched remote media")
	}
}

func TestActveroAdmissionRejectsInvalidImageOrExcessInput(t *testing.T) {
	previous := constant.GetMediaToken
	constant.GetMediaToken = true
	t.Cleanup(func() { constant.GetMediaToken = previous })
	invalid := []any{map[string]any{"type": "image_url", "image_url": map[string]any{"url": "data:image/png;base64,invalid"}}}
	for _, chat := range []*dto.GeneralOpenAIRequest{
		actveroAdmissionChat(t, invalid),
		actveroAdmissionChat(t, strings.Repeat("large input ", 100)),
	} {
		if _, _, err := actveroAdmissionInput(actveroAdmissionContext(), chat, "gpt-4o", 10); err == nil {
			t.Fatal("expected unavailable estimate")
		}
	}
}
