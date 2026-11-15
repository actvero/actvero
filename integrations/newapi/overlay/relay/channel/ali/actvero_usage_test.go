package ali

import (
	"github.com/QuantumNous/new-api/relaykit/dto"
	"github.com/gin-gonic/gin"
	"testing"
)

func TestActveroRerankUsageRequiresOriginalInputCounters(t *testing.T) {
	cases := []struct {
		name, wire string
		tokens     int
		confirmed  bool
	}{
		{"missing", `{}`, 52, false},
		{"missing-counter", `{"usage":{}}`, 52, false},
		{"zero", `{"usage":{"total_tokens":0}}`, 0, false},
		{"negative", `{"usage":{"total_tokens":-1}}`, -1, false},
		{"estimated", `{"usage":{"total_tokens":52}}`, 60, false},
		{"mismatch", `{"usage":{"total_tokens":52,"input_tokens":51}}`, 52, false},
		{"unexpected-output", `{"usage":{"total_tokens":52,"output_tokens":2}}`, 52, false},
		{"valid", `{"usage":{"total_tokens":52}}`, 52, true},
		{"explicit-input", `{"usage":{"total_tokens":52,"input_tokens":52,"output_tokens":0}}`, 52, true},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			c, _ := gin.CreateTestContext(nil)
			actveroConfirmRerankUsage(c, &dto.Usage{PromptTokens: tc.tokens, TotalTokens: tc.tokens}, []byte(tc.wire))
			if c.GetBool("actvero_confirmed_input_usage") != tc.confirmed {
				t.Fatal("incorrect rerank billing evidence")
			}
		})
	}
}
