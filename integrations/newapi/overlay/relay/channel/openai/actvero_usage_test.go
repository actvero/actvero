package openai

import (
	"github.com/QuantumNous/new-api/relaykit/dto"
	"github.com/gin-gonic/gin"
	"testing"
)

func TestActveroConfirmedUsageRequiresRealCounters(t *testing.T) {
	cases := []struct {
		wire      string
		usage     *dto.Usage
		confirmed bool
	}{
		{`{}`, nil, false},
		{`{"usage":{}}`, &dto.Usage{}, false},
		{`{"usage":{"prompt_tokens":100,"total_tokens":100}}`, &dto.Usage{PromptTokens: 100, TotalTokens: 100}, false},
		{`{"usage":{"prompt_tokens":100,"completion_tokens":10,"total_tokens":1}}`, &dto.Usage{PromptTokens: 100, CompletionTokens: 10, TotalTokens: 1}, false},
		{`{"usage":{"prompt_tokens":100,"completion_tokens":10,"total_tokens":110}}`, &dto.Usage{PromptTokens: 100, CompletionTokens: 10, TotalTokens: 110}, true},
		{`{"usage":{"prompt_tokens":100,"completion_tokens":0,"total_tokens":100}}`, &dto.Usage{PromptTokens: 100, TotalTokens: 100}, true},
		{`{"usage":{"prompt_tokens":100,"completion_tokens":10}}`, &dto.Usage{PromptTokens: 100, CompletionTokens: 10}, true},
	}
	for _, test := range cases {
		c, _ := gin.CreateTestContext(nil)
		actveroConfirmChatUsage(c, test.usage, []byte(test.wire))
		if c.GetBool("actvero_confirmed_chat_usage") != test.confirmed {
			t.Fatalf("wrong evidence decision for %s", test.wire)
		}
	}
}
