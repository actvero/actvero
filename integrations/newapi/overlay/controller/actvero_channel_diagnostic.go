package controller

import (
	"context"

	"github.com/QuantumNous/new-api/common"
	"github.com/QuantumNous/new-api/model"
	relaycommon "github.com/QuantumNous/new-api/relay/common"
	"github.com/QuantumNous/new-api/relay/helper"
	"github.com/QuantumNous/new-api/relaykit/types"
	hosttypes "github.com/QuantumNous/new-api/types"
	"github.com/gin-gonic/gin"
)

// Only the authenticated organization bridge can create this request context.
// Automatic health checks and ordinary relay requests retain native billing.
type actveroTestContextKey struct{}
type actveroTestContext struct {
	UserID           int
	Model            string
	Endpoint         string
	UsageRecorded    bool
	PromptTokens     int
	CompletionTokens int
}

func actveroTestPrice(c *gin.Context, info *relaycommon.RelayInfo, promptTokens int, meta *types.TokenCountMeta) (hosttypes.PriceData, error) {
	if state, ok := c.Request.Context().Value(actveroTestContextKey{}).(*actveroTestContext); ok && info.IsChannelTest {
		state.Model = info.OriginModelName
		state.Endpoint = info.RequestURLPath
		info.PriceData = hosttypes.PriceData{}
		return info.PriceData, nil
	}
	return helper.ModelPriceHelper(c, info, promptTokens, meta)
}

func actveroRecordTestLog(c *gin.Context, userID int, params model.RecordConsumeLogParams) {
	state, ok := c.Request.Context().Value(actveroTestContextKey{}).(*actveroTestContext)
	if !ok {
		model.RecordConsumeLog(c, userID, params)
		return
	}
	state.Model, state.PromptTokens, state.CompletionTokens = params.ModelName, params.PromptTokens, params.CompletionTokens
	state.UsageRecorded = true
	// Diagnostic use is a system event, never a zero-cost consumption record.
	other := model.NewLogOther()
	other.SetAdmin("pricing_status", "unpriced")
	other.SetAdmin("purpose", "administrator_channel_test")
	username, _ := model.GetUsernameById(state.UserID, false)
	entry := model.Log{UserId: state.UserID, Username: username, CreatedAt: common.GetTimestamp(), Type: model.LogTypeSystem, Content: "管理员渠道测试（未计价）", ModelName: params.ModelName, ChannelId: params.ChannelId, PromptTokens: params.PromptTokens, CompletionTokens: params.CompletionTokens, UseTime: params.UseTimeSeconds, IsStream: params.IsStream, Other: other.JSONString(), RequestId: common.NewRequestId()}
	if err := model.LOG_DB.Create(&entry).Error; err != nil {
		common.SysLog(common.LogText("failed to record administrator channel test"))
	}
}

func actveroPrepareChannelTest(c *gin.Context) (*actveroTestContext, error) {
	var org model.ActveroOrganization
	if err := model.DB.First(&org, "owner = ?", c.GetString("actvero_owner")).Error; err != nil {
		return nil, err
	}
	state := &actveroTestContext{UserID: org.UserID, Endpoint: c.Query("endpoint_type")}
	c.Set("id", org.UserID)
	c.Request = c.Request.WithContext(context.WithValue(c.Request.Context(), actveroTestContextKey{}, state))
	return state, nil
}

func actveroAnnotateTestResponse(packet any, state *actveroTestContext) {
	if state == nil {
		return
	}
	if result, ok := packet.(map[string]any); ok {
		result["pricing_status"] = "unpriced"
		result["model_name"] = state.Model
		result["endpoint_type"] = state.Endpoint
		if state.UsageRecorded {
			result["prompt_tokens"] = state.PromptTokens
			result["completion_tokens"] = state.CompletionTokens
		}
	}
}
