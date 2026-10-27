// Actvero organization bridge. Its root-only capability is never issued to organization users.
package controller

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"strconv"
	"strings"

	"github.com/QuantumNous/new-api/common"
	"github.com/QuantumNous/new-api/model"
	"github.com/gin-gonic/gin"
)

type actveroBridgeRequest struct {
	Method  string                     `json:"method"`
	Path    string                     `json:"path"`
	Params  map[string]json.RawMessage `json:"params"`
	Payload map[string]any             `json:"payload"`
}

type actveroCapture struct {
	gin.ResponseWriter
	body   bytes.Buffer
	status int
}

func (w *actveroCapture) Write(b []byte) (int, error)       { return w.body.Write(b) }
func (w *actveroCapture) WriteString(s string) (int, error) { return w.body.WriteString(s) }
func (w *actveroCapture) WriteHeader(code int)              { w.status = code }
func (w *actveroCapture) WriteHeaderNow()                   {}
func (w *actveroCapture) Status() int                       { return w.status }
func (w *actveroCapture) Size() int                         { return w.body.Len() }
func (w *actveroCapture) Written() bool                     { return w.body.Len() > 0 }
func (w *actveroCapture) Flush()                            {}

func ActveroOrganizationConnect(c *gin.Context) {
	owner := c.Param("organization")
	prefix, ok := common.ActveroNamespace(owner)
	if !ok {
		c.JSON(400, gin.H{"success": false})
		return
	}
	token, err := model.ActveroConnect(owner)
	if err != nil {
		common.ApiErrorMsg(c, "Organization gateway initialization failed")
		return
	}
	common.ApiSuccess(c, gin.H{"schema_version": 1, "namespace": prefix, "relay_key": token.Key, "relay_token_id": token.Id, "relay_group": "default"})
}

func ActveroOrganizationBridge(c *gin.Context) {
	prefix, ok := common.ActveroNamespace(c.Param("organization"))
	if !ok {
		c.JSON(400, gin.H{"success": false})
		return
	}
	var input actveroBridgeRequest
	if err := c.ShouldBindJSON(&input); err != nil || len(input.Path) > 200 || len(input.Params) > 1000 {
		c.JSON(400, gin.H{"success": false, "message": "Invalid bridge request"})
		return
	}
	path := "/" + strings.Trim(input.Path, "/")
	if !strings.HasPrefix(path, "/api/") || strings.Contains(path, "..") {
		c.JSON(404, gin.H{"success": false})
		return
	}
	c.Set("actvero_prefix", prefix)
	c.Set("actvero_owner", c.Param("organization"))
	params := url.Values{}
	for key, raw := range input.Params {
		var value any
		if json.Unmarshal(raw, &value) != nil {
			c.JSON(400, gin.H{"success": false})
			return
		}
		switch v := value.(type) {
		case string:
			params.Add(key, v)
		case float64:
			params.Add(key, strconv.FormatFloat(v, 'f', -1, 64))
		case []any:
			for _, element := range v {
				text, ok := element.(string)
				if !ok {
					c.JSON(400, gin.H{"success": false})
					return
				}
				params.Add(key, text)
			}
		default:
			c.JSON(400, gin.H{"success": false})
			return
		}
	}
	if input.Method == "GET" && regexp.MustCompile(`^/api/plugin/task/[A-Za-z0-9_-]{1,100}/icon$`).MatchString(path) {
		c.Params = gin.Params{{Key: "key", Value: strings.Split(path, "/")[4]}}
		GetTaskPluginIcon(c)
		return
	}
	input.Path = path
	handler, err := actveroBridgeHandler(c, prefix, &input, params)
	if err != nil {
		c.JSON(404, gin.H{"success": false, "message": "Organization resource or operation is unavailable"})
		return
	}
	if handler == nil {
		return
	}
	payload, err := json.Marshal(input.Payload)
	if err != nil || len(payload) > 2000000 {
		c.JSON(400, gin.H{"success": false})
		return
	}
	c.Request.Method = input.Method
	c.Request.URL.Path = path
	c.Request.URL.RawQuery = params.Encode()
	c.Request.Body = io.NopCloser(bytes.NewReader(payload))
	c.Request.ContentLength = int64(len(payload))
	capture := &actveroCapture{ResponseWriter: c.Writer, status: 200}
	c.Writer = capture
	handler(c)
	c.Writer = capture.ResponseWriter
	var packet any
	if err := json.Unmarshal(capture.body.Bytes(), &packet); err != nil {
		common.ApiErrorMsg(c, "Invalid organization gateway response")
		return
	}
	// Billing identifiers remain native; Actvero correlates them to its immutable attempt record.
	if path != "/api/log" {
		packet = actveroPublicValue(prefix, packet, "")
	}
	c.JSON(capture.status, packet)
}

func actveroBridgeHandler(c *gin.Context, prefix string, input *actveroBridgeRequest, q url.Values) (gin.HandlerFunc, error) {
	path, method := input.Path, input.Method
	bad := errors.New("unsupported organization operation")
	// Only these public configuration packets are safe to share across namespaces.
	if method == http.MethodGet {
		switch path {
		case "/api/status":
			return GetStatus, nil
		case "/api/notice":
			return GetNotice, nil
		case "/api/channel/default_base_urls":
			return GetChannelDefaultBaseURLs, nil
		case "/api/task_plugin_options":
			return GetTaskPluginOptions, nil
		case "/api/channel/ops":
			return GetChannelOps, nil
		case "/api/channel", "/api/channel/search":
			actveroListChannels(c, prefix, q)
			return nil, nil
		case "/api/models", "/api/models/search":
			actveroListModels(c, prefix, q)
			return nil, nil
		case "/api/vendors", "/api/vendors/search":
			actveroListVendors(c, prefix, q)
			return nil, nil
		case "/api/group":
			actveroListGroups(c, prefix)
			return nil, nil
		case "/api/prefill_group":
			actveroListPrefills(c, prefix, q.Get("type"))
			return nil, nil
		case "/api/channel/models":
			actveroChannelModels(c, prefix)
			return nil, nil
		case "/api/pricing":
			actveroPricing(c, prefix)
			return nil, nil
		case "/api/models/missing":
			actveroMissingModels(c, prefix)
			return nil, nil
		case "/api/models/sync_upstream/preview":
			return SyncUpstreamPreview, nil
		case "/api/option/model_pricing":
			names := q["model"]
			if len(names) == 0 {
				return nil, bad
			}
			if err := model.ActveroPrepareModels(prefix, names); err != nil {
				return nil, err
			}
			q.Del("model")
			for _, name := range names {
				q.Add("model", prefix+name)
			}
			return GetModelPricingConfig, nil
		case "/api/ratio_sync/channels":
			actveroRatioChannels(c, prefix)
			return nil, nil
		case "/api/log":
			actveroLogs(c, prefix, q)
			return nil, nil
		}
	}
	parts := strings.Split(strings.Trim(path, "/"), "/")
	if len(parts) >= 3 && parts[0] == "api" {
		kind := parts[1]
		idPosition := 2
		if kind == "channel" && len(parts) == 4 && (parts[2] == "test" || parts[2] == "fetch_models") {
			idPosition = 3
		}
		if id, err := strconv.Atoi(parts[idPosition]); err == nil && id > 0 {
			if !actveroOwnsID(prefix, kind, id) {
				return nil, bad
			}
			c.Params = gin.Params{{Key: "id", Value: strconv.Itoa(id)}}
			switch {
			case kind == "channel" && len(parts) == 3 && method == "GET":
				return GetChannel, nil
			case kind == "channel" && len(parts) == 3 && method == "DELETE":
				return DeleteChannel, nil
			case kind == "channel" && len(parts) == 4 && parts[2] == "test" && method == "GET":
				if q.Get("model") != "" {
					q.Set("model", prefix+q.Get("model"))
				}
				return TestChannel, nil
			case kind == "channel" && len(parts) == 4 && parts[2] == "fetch_models" && method == "GET":
				return FetchUpstreamModels, nil
			case kind == "channel" && len(parts) == 4 && parts[3] == "status" && method == "POST":
				return UpdateChannelStatus, nil
			case kind == "models" && len(parts) == 3 && method == "GET":
				return GetModelMeta, nil
			case kind == "models" && len(parts) == 3 && method == "DELETE":
				return DeleteModelMeta, nil
			case kind == "vendors" && len(parts) == 3 && method == "GET":
				return GetVendorMeta, nil
			case kind == "vendors" && len(parts) == 3 && method == "DELETE":
				return DeleteVendorMeta, nil
			case kind == "prefill_group" && len(parts) == 3 && method == "DELETE":
				return DeletePrefillGroup, nil
			}
		}
	}
	body := input.Payload
	if body == nil {
		return nil, bad
	}
	switch {
	case path == "/api/channel/fetch_models" && method == "POST":
		delete(body, "channel_id")
		return FetchModels, nil
	case path == "/api/channel" && (method == "POST" || method == "PUT"):
		value := body
		if method == "POST" {
			var ok bool
			value, ok = body["channel"].(map[string]any)
			if !ok {
				return nil, bad
			}
			delete(value, "id")
		} else if !actveroOwnsNumber(prefix, "channel", body["id"]) {
			return nil, bad
		}
		if err := actveroChannelPayload(prefix, value, method == "POST"); err != nil {
			return nil, err
		}
		if method == "POST" {
			return AddChannel, nil
		}
		return UpdateChannel, nil
	case path == "/api/models" && (method == "POST" || method == "PUT"):
		if method == "POST" {
			delete(body, "id")
		} else if !actveroOwnsNumber(prefix, "models", body["id"]) {
			return nil, bad
		}
		if n, ok := body["model_name"].(string); ok {
			var err error
			body["model_name"], err = actveroName(prefix, n, 128)
			if err != nil {
				return nil, err
			}
		}
		if vendor, exists := body["vendor_id"]; exists && !actveroZeroOrOwn(prefix, "vendors", vendor) {
			return nil, bad
		}
		if method == "POST" {
			return CreateModelMeta, nil
		}
		return UpdateModelMeta, nil
	case path == "/api/models/delete" && method == "POST":
		if !actveroOwnsNumbers(prefix, "models", body["model_ids"]) {
			return nil, bad
		}
		return BatchDeleteModelMeta, nil
	case path == "/api/models/sync_upstream" && method == "POST":
		actveroQualifyFields(prefix, body)
		return SyncUpstreamModels, nil
	case path == "/api/vendors" && (method == "POST" || method == "PUT"):
		if method == "POST" {
			delete(body, "id")
		} else if !actveroOwnsNumber(prefix, "vendors", body["id"]) {
			return nil, bad
		}
		if n, ok := body["name"].(string); ok {
			var err error
			body["name"], err = actveroName(prefix, n, 128)
			if err != nil {
				return nil, err
			}
		}
		if method == "POST" {
			return CreateVendorMeta, nil
		}
		return UpdateVendorMeta, nil
	case (path == "/api/vendors/operations" || path == "/api/vendors/operations/preview") && method == "POST":
		for key, kind := range map[string]string{"vendor_ids": "vendors", "model_ids": "models"} {
			if v, exists := body[key]; exists && !actveroOwnsNumbers(prefix, kind, v) {
				return nil, bad
			}
		}
		if v, exists := body["target_vendor_id"]; exists && !actveroZeroOrOwn(prefix, "vendors", v) {
			return nil, bad
		}
		if path == "/api/vendors/operations/preview" {
			return PreviewVendorOperation, nil
		}
		return ApplyVendorOperation, nil
	case path == "/api/prefill_group" && (method == "POST" || method == "PUT"):
		if method == "POST" {
			delete(body, "id")
		} else if !actveroOwnsNumber(prefix, "prefill_group", body["id"]) {
			return nil, bad
		}
		if n, ok := body["name"].(string); ok {
			var err error
			body["name"], err = actveroName(prefix, n, 128)
			if err != nil {
				return nil, err
			}
		}
		if method == "POST" {
			return CreatePrefillGroup, nil
		}
		return UpdatePrefillGroup, nil
	case path == "/api/ratio_sync/fetch" && method == "POST":
		if v, exists := body["channel_ids"]; exists && !actveroOwnsNumbers(prefix, "channel", v) {
			return nil, bad
		}
		return FetchUpstreamRatios, nil
	case path == "/api/option/model_pricing" && method == "PATCH":
		actveroQualifyFields(prefix, body)
		return UpdateModelPricingConfig, nil
	case path == "/api/option/model_pricing/preview" && method == "POST":
		actveroQualifyFields(prefix, body)
		return PreviewModelPricing, nil
	case path == "/api/option/model_pricing/convert" && method == "POST":
		actveroQualifyFields(prefix, body)
		return PreviewModelPricingConversion, nil
	case path == "/api/option/model_pricing/preflight" && method == "POST":
		token, err := model.ActveroConnect(c.GetString("actvero_owner"))
		if err != nil {
			return nil, err
		}
		if id, ok := body["token_id"].(float64); !ok || id != float64(token.Id) {
			return nil, bad
		}
		if name, ok := body["model"].(string); ok {
			if err := model.ActveroPrepareModels(prefix, []string{name}); err != nil {
				return nil, err
			}
		}
		actveroQualifyFields(prefix, body)
		return ActveroAdmissionPreview, nil
	}
	return nil, bad
}
