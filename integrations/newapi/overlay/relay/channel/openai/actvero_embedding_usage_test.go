package openai

import (
	relaycommon "github.com/QuantumNous/new-api/relay/common"
	relayconstant "github.com/QuantumNous/new-api/relay/constant"
	"github.com/QuantumNous/new-api/relaykit/dto"
	"github.com/gin-gonic/gin"
	"testing"
)

func TestActveroEmbeddingUsageRejectsMissingOrEstimatedCounters(t *testing.T) {
	cases := []struct {
		name, wire                string
		prompt, total, completion int
		confirmed                 bool
	}{
		{"missing", `{}`, 7, 7, 0, false},
		{"missing-total", `{"usage":{"prompt_tokens":7}}`, 7, 7, 0, false},
		{"missing-prompt", `{"usage":{"total_tokens":7}}`, 7, 7, 0, false},
		{"mismatched-wire", `{"usage":{"prompt_tokens":7,"total_tokens":8}}`, 7, 8, 0, false},
		{"local-fallback", `{"usage":{"prompt_tokens":7,"total_tokens":7}}`, 8, 8, 0, false},
		{"zero", `{"usage":{"prompt_tokens":0,"total_tokens":0}}`, 0, 0, 0, false},
		{"negative", `{"usage":{"prompt_tokens":-7,"total_tokens":-7}}`, -7, -7, 0, false},
		{"unexpected-output", `{"usage":{"prompt_tokens":7,"completion_tokens":1,"total_tokens":7}}`, 7, 7, 0, false},
		{"valid-input-only", `{"usage":{"prompt_tokens":7,"total_tokens":7}}`, 7, 7, 0, true},
		{"valid-explicit-zero", `{"usage":{"prompt_tokens":7,"completion_tokens":0,"total_tokens":7}}`, 7, 7, 0, true},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			c, _ := gin.CreateTestContext(nil)
			usage := &dto.Usage{PromptTokens: tc.prompt, TotalTokens: tc.total, CompletionTokens: tc.completion}
			actveroConfirmEmbeddingUsage(c, &relaycommon.RelayInfo{RelayMode: relayconstant.RelayModeEmbeddings}, usage, []byte(tc.wire))
			if c.GetBool("actvero_confirmed_input_usage") != tc.confirmed {
				t.Fatal("incorrect input billing evidence")
			}
			chat, _ := gin.CreateTestContext(nil)
			actveroConfirmEmbeddingUsage(chat, &relaycommon.RelayInfo{RelayMode: relayconstant.RelayModeChatCompletions}, usage, []byte(tc.wire))
			if chat.GetBool("actvero_confirmed_input_usage") {
				t.Fatal("embedding evidence must not confirm chat")
			}
		})
	}
}
