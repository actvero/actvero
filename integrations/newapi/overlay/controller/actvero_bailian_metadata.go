package controller

import (
	"encoding/json"
	"net/http"
	"net/url"
	"regexp"
	"strconv"
	"strings"

	"github.com/QuantumNous/new-api/common"
	"github.com/QuantumNous/new-api/constant"
	"github.com/QuantumNous/new-api/model"
	"github.com/gin-gonic/gin"
)

// This is a read-only supplement to native model discovery. Credentials stay
// inside the native adapter and may only be sent to the official service.
func ActveroBailianMetadata(c *gin.Context) {
	id, _ := strconv.Atoi(c.Param("id"))
	channel, err := model.GetChannelById(id, true)
	if err != nil || channel.Type != constant.ChannelTypeAli {
		common.ApiErrorMsg(c, "此渠道暂不支持供应商资料查询")
		return
	}
	name := c.Query("model")
	bound := false
	for _, candidate := range channel.GetModels() {
		if candidate == name {
			bound = true
		}
	}
	if !bound {
		common.ApiErrorMsg(c, "模型未关联此渠道")
		return
	}
	mapping := map[string]string{}
	if channel.ModelMapping != nil {
		_ = json.Unmarshal([]byte(*channel.ModelMapping), &mapping)
	}
	upstream := name
	if mapped, ok := mapping[name]; ok {
		upstream = mapped
	} else {
		_, upstream = common.ActveroSplitName(name)
	}
	if reference := c.Query("reference_model"); reference != "" {
		upstream = reference
	}
	base, err := url.Parse(channel.GetBaseURL())
	if err != nil || base.Scheme != "https" || base.User != nil || (base.Port() != "" && base.Port() != "443") {
		common.ApiErrorMsg(c, "供应商资料查询需要官方 HTTPS 地址")
		return
	}
	host := strings.ToLower(base.Hostname())
	official := host == "dashscope.aliyuncs.com" || host == "dashscope-intl.aliyuncs.com" || strings.HasSuffix(host, ".dashscope.aliyuncs.com") || strings.HasSuffix(host, ".maas.aliyuncs.com")
	if !official {
		common.ApiErrorMsg(c, "自定义代理地址不自动获取百炼官方资料")
		return
	}
	if workspace := c.Query("workspace_id"); workspace != "" {
		if !regexp.MustCompile(`^[A-Za-z0-9-]{1,64}$`).MatchString(workspace) {
			common.ApiErrorMsg(c, "业务空间 ID 格式无效")
			return
		}
		if host == "dashscope.aliyuncs.com" {
			base.Host = workspace + ".cn-beijing.maas.aliyuncs.com"
		}
	}
	base.Path = "/api/v1/models"
	base.RawQuery = url.Values{"model": {upstream}, "page_size": {"100"}, "language": {"zh-CN"}}.Encode()
	key, _, apiErr := channel.GetNextEnabledKey()
	if apiErr != nil {
		common.ApiErrorMsg(c, "渠道没有可用密钥")
		return
	}
	headers, err := buildFetchModelsHeaders(channel, strings.TrimSpace(key))
	if err != nil {
		common.ApiErrorMsg(c, "无法构建供应商资料请求")
		return
	}
	raw, err := getFetchModelsResponseBody(http.MethodGet, base.String(), channel, headers)
	if err != nil {
		common.ApiErrorMsg(c, "供应商资料暂不可用，请核对地域与业务空间，或手动填写")
		return
	}
	var result struct {
		Success bool `json:"success"`
		Output  struct {
			Models []map[string]any `json:"models"`
		} `json:"output"`
	}
	if json.Unmarshal(raw, &result) != nil || !result.Success {
		common.ApiErrorMsg(c, "供应商未返回有效模型资料，可手动填写")
		return
	}
	for _, item := range result.Output.Models {
		if item["model"] == upstream {
			public := map[string]any{}
			for _, field := range []string{"model", "name", "description", "provider", "inference_provider", "features", "capabilities", "inference_metadata", "model_info", "prices"} {
				if value, ok := item[field]; ok {
					public[field] = value
				}
			}
			common.ApiSuccess(c, public)
			return
		}
	}
	common.ApiErrorMsg(c, "供应商资料未匹配此模型，可填写明确的参考模型 ID 或手动补充")
}
