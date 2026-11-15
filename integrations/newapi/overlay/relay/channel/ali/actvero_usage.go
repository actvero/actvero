package ali

import (
	"encoding/json"
	"github.com/QuantumNous/new-api/relaykit/dto"
	"github.com/gin-gonic/gin"
)

// Bailian rerank returns total_tokens for input-only billing. Confirm presence
// and consistency in the original response, never a synthesized zero/default.
func actveroConfirmRerankUsage(c *gin.Context, usage *dto.Usage, raw []byte) {
	var wire struct {
		Usage *struct {
			Total  *int `json:"total_tokens"`
			Input  *int `json:"input_tokens"`
			Output *int `json:"output_tokens"`
		} `json:"usage"`
	}
	if json.Unmarshal(raw, &wire) != nil || wire.Usage == nil || wire.Usage.Total == nil || usage == nil {
		return
	}
	u := wire.Usage
	if *u.Total <= 0 || (u.Input != nil && *u.Input != *u.Total) || (u.Output != nil && *u.Output != 0) || usage.PromptTokens != *u.Total || usage.TotalTokens != *u.Total || usage.CompletionTokens != 0 {
		return
	}
	c.Set("actvero_confirmed_input_usage", true)
}
