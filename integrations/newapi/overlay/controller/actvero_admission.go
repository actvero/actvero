package controller

import (
	"fmt"
	"math"
	"net/http"
	"strconv"
	"time"

	"github.com/QuantumNous/new-api/common"
	"github.com/QuantumNous/new-api/constant"
	"github.com/QuantumNous/new-api/model"
	"github.com/QuantumNous/new-api/pkg/billingexpr"
	relaycommon "github.com/QuantumNous/new-api/relay/common"
	"github.com/QuantumNous/new-api/relaykit/dto"
	"github.com/QuantumNous/new-api/relaykit/types"
	"github.com/QuantumNous/new-api/service"
	"github.com/QuantumNous/new-api/setting/ratio_setting"
	"github.com/gin-gonic/gin"
)

// ActveroAdmissionPreview is read-only and uses the existing root/option:read guard.
// It returns no prompts, credentials, balances or token material.
func ActveroAdmissionPreview(c *gin.Context) {
	var request struct {
		Model   string                    `json:"model"`
		TokenID int                       `json:"token_id"`
		Input   int                       `json:"input_limit"`
		Output  int                       `json:"output_limit"`
		Chat    *dto.GeneralOpenAIRequest `json:"chat,omitempty"`
	}
	reject := func() {
		c.JSON(http.StatusUnprocessableEntity, gin.H{"success": false, "message": "No verified admission estimate is available for this model"})
	}
	if err := common.DecodeJson(c.Request.Body, &request); err != nil || request.Model == "" || len(request.Model) > 256 || request.TokenID <= 0 {
		reject()
		return
	}
	token, err := model.GetTokenById(request.TokenID)
	if err != nil || token.Group == "auto" {
		reject()
		return
	}
	userGroup, err := model.GetUserGroup(token.UserId, true)
	if err != nil {
		reject()
		return
	}
	group := token.Group
	if group == "" {
		group = userGroup
	}
	groupRatio, special := ratio_setting.GetGroupGroupRatio(userGroup, group)
	if !special {
		groupRatio = ratio_setting.GetGroupRatio(group)
	}
	snapshot, err := model.GetModelPricingSnapshot([]string{request.Model})
	if err != nil || len(snapshot.Entries) != 1 {
		reject()
		return
	}
	entry := snapshot.Entries[0]
	expression, _ := entry.Effective["billing_setting.billing_expr"].(string)
	if entry.Effective["billing_setting.billing_mode"] != "tiered_expr" || expression == "" {
		converted, err := model.PreviewModelPricingConversion(request.Model, entry.Configured)
		if err != nil || converted.Expression == "" {
			reject()
			return
		}
		expression = converted.Expression
	}
	pricedInput, inputSource, err := actveroAdmissionInput(c, request.Chat, request.Model, request.Input)
	if err != nil {
		reject()
		return
	}
	bound, err := billingexpr.AdmissionBound(expression, pricedInput, request.Output)
	raw := bound / 1000000 * common.QuotaPerUnit * groupRatio
	if err != nil || groupRatio < 0 || math.IsInf(raw, 0) || math.IsNaN(raw) || raw < 0 {
		reject()
		return
	}
	// Round upward and retain one quota unit of floating-point headroom.
	if raw > 0 {
		raw = math.Ceil(raw*(1+1e-12)) + 1
	}
	quota, err := common.QuotaRoundStrict(raw)
	if err != nil || common.QuotaPerUnit <= 0 {
		reject()
		return
	}
	common.ApiSuccess(c, gin.H{
		"schema_version": 1, "model": request.Model, "pricing_version": entry.Version,
		"expression_hash": billingexpr.ExprHashString(expression), "group": group, "group_ratio": groupRatio,
		"input_limit": request.Input, "output_limit": request.Output,
		"priced_input": pricedInput, "input_source": inputSource,
		"quota": strconv.Itoa(quota), "quota_per_unit": fmt.Sprintf("%.0f", common.QuotaPerUnit),
		"expires_at": time.Now().Add(60 * time.Second).Unix(),
	})
}

// Inline images, text and tools use the native relay counter. Other media keep
// the capacity bound so this read-only endpoint never downloads remote content.
func actveroAdmissionInput(c *gin.Context, chat *dto.GeneralOpenAIRequest, modelName string, limit int) (int, string, error) {
	if chat == nil {
		return limit, "capacity_bound", nil
	}
	meta := chat.GetTokenCountMeta()
	for _, file := range meta.Files {
		if file == nil || file.FileType != types.FileTypeImage {
			return limit, "capacity_bound", nil
		}
		if source, inline := file.Source.(*types.Base64Source); !inline || source == nil {
			return limit, "capacity_bound", nil
		}
	}
	defer service.CleanupFileSources(c)
	_, modelName = common.ActveroSplitName(modelName)
	common.SetContextKey(c, constant.ContextKeyOriginalModel, modelName)
	count, err := service.CountRequestToken(c, meta, &relaycommon.RelayInfo{
		RelayFormat: types.RelayFormatOpenAI, IsStream: chat.IsStream(c.Request),
	})
	if err != nil || count < 0 || count > limit {
		return 0, "", fmt.Errorf("no verified input estimate within the model capacity")
	}
	return max(1, count), "native_token_estimate", nil
}
