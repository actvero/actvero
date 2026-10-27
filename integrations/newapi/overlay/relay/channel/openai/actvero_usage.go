package openai

import (
	"github.com/QuantumNous/new-api/common"
	"github.com/QuantumNous/new-api/relaykit/dto"
	"github.com/gin-gonic/gin"
)

// Confirm field presence in the received wire usage before any local fallback.
// Typed zero values alone cannot distinguish a missing counter from a real zero.
func actveroConfirmChatUsage(c *gin.Context, usage *dto.Usage, raw []byte) {
	var wire struct {
		Usage *struct {
			Prompt     *int `json:"prompt_tokens"`
			Completion *int `json:"completion_tokens"`
			Total      *int `json:"total_tokens"`
		} `json:"usage"`
	}
	if common.Unmarshal(raw, &wire) != nil || wire.Usage == nil || wire.Usage.Prompt == nil || wire.Usage.Completion == nil {
		return
	}
	if usage == nil || usage.PromptTokens <= 0 || usage.CompletionTokens < 0 || *wire.Usage.Prompt != usage.PromptTokens || *wire.Usage.Completion != usage.CompletionTokens {
		return
	}
	if wire.Usage.Total != nil && (*wire.Usage.Total < 0 || *wire.Usage.Total != usage.PromptTokens+usage.CompletionTokens) {
		return
	}
	if _, ok := dto.NewOpenAIChatBillingUsage(usage).CanonicalUsage(); !ok {
		return
	}
	c.Set("actvero_confirmed_chat_usage", true)
}
