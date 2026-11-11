package controller

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/QuantumNous/new-api/common"
	"github.com/QuantumNous/new-api/i18n"
	"github.com/QuantumNous/new-api/model"
	"github.com/QuantumNous/new-api/service"
	"github.com/stretchr/testify/require"
)

func TestActveroAdminDiagnosticWithoutPriceRetainsNativeRequest(t *testing.T) {
	require.NoError(t, i18n.Init())
	db := actveroTestDatabase(t)
	require.NoError(t, db.AutoMigrate(&model.ActveroOrganization{}, &model.Token{}, &model.UserAccessToken{}, &model.PrefillGroup{}, &model.Log{}))
	t.Setenv("ACTVERO_ORGANIZATION_ISOLATION", "true")
	connection, err := model.ActveroConnect(actveroOrgA)
	require.NoError(t, err)
	calls := 0
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		require.Equal(t, "/v1/chat/completions", r.URL.Path)
		require.Equal(t, "Bearer fixture-only", r.Header.Get("Authorization"))
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"id":"fixture","object":"chat.completion","choices":[{"index":0,"message":{"role":"assistant","content":"ok"},"finish_reason":"stop"}],"usage":{"prompt_tokens":7,"completion_tokens":3,"total_tokens":10}}`))
	}))
	t.Cleanup(upstream.Close)
	t.Setenv("ACTVERO_EGRESS_PRIVATE_TARGETS", upstream.Listener.Addr().String())
	service.InitHttpClient()
	created := actveroTestBridge(t, actveroOrgA, "POST", "/api/channel", map[string]any{"mode": "single", "channel": map[string]any{"name": "Diagnostic fixture", "type": 1, "key": "fixture-only", "models": "unknown-diagnostic-model", "group": "default", "base_url": upstream.URL}}, nil)
	require.Equal(t, true, created["success"], created)
	var channel model.Channel
	prefix, _ := common.ActveroNamespace(actveroOrgA)
	require.NoError(t, db.Where("name = ?", prefix+"Diagnostic fixture").First(&channel).Error)
	// Native health checks still require native pricing. Only the bridge opts in.
	ordinary := testChannel(context.Background(), &channel, connection.UserId, "", "", false)
	require.Error(t, ordinary.localErr)
	require.Equal(t, 0, calls)
	result := actveroTestBridge(t, actveroOrgA, "GET", fmt.Sprintf("/api/channel/test/%d", channel.Id), nil, nil)
	require.Equal(t, true, result["success"], result)
	require.Equal(t, "unpriced", result["pricing_status"])
	require.Equal(t, "unknown-diagnostic-model", result["model_name"])
	require.Equal(t, float64(7), result["prompt_tokens"])
	require.Equal(t, float64(3), result["completion_tokens"])
	require.Equal(t, 1, calls)
	var logs []model.Log
	require.NoError(t, db.Find(&logs).Error)
	require.Len(t, logs, 1)
	require.Equal(t, model.LogTypeSystem, logs[0].Type)
	require.Equal(t, connection.UserId, logs[0].UserId)
	require.Contains(t, logs[0].Other, "unpriced")
	require.Equal(t, 7, logs[0].PromptTokens)
	foreign := actveroTestBridge(t, actveroOrgB, "GET", fmt.Sprintf("/api/channel/test/%d", channel.Id), nil, nil)
	require.Equal(t, false, foreign["success"])
	require.Equal(t, 1, calls)
}

func TestActveroStatisticsIgnoreForeignIdentity(t *testing.T) {
	db := actveroTestDatabase(t)
	require.NoError(t, db.AutoMigrate(&model.ActveroOrganization{}, &model.Token{}, &model.UserAccessToken{}, &model.PrefillGroup{}, &model.QuotaData{}))
	t.Setenv("ACTVERO_ORGANIZATION_ISOLATION", "true")
	a, err := model.ActveroConnect(actveroOrgA)
	require.NoError(t, err)
	b, err := model.ActveroConnect(actveroOrgB)
	require.NoError(t, err)
	timestamp := common.GetTimestamp() - 60
	for _, conn := range []*model.Token{a, b} {
		username, _ := model.GetUsernameById(conn.UserId, false)
		prefix := conn.Group[:len(conn.Group)-len("default")]
		require.NoError(t, db.Create(&model.QuotaData{UserID: conn.UserId, Username: username, ModelName: prefix + "same-model", CreatedAt: timestamp, Count: 1, Quota: 10, TokenUsed: 20}).Error)
	}
	for _, path := range []string{"/api/data", "/api/data/self", "/api/data/users"} {
		packet := actveroTestBridge(t, actveroOrgA, "GET", path, nil, map[string]any{"start_timestamp": timestamp - 60, "end_timestamp": timestamp + 60, "username": "forged", "user_id": b.UserId})
		require.Equal(t, true, packet["success"], packet)
		rows := packet["data"].([]any)
		require.Len(t, rows, 1)
		row := rows[0].(map[string]any)
		require.Equal(t, float64(a.UserId), row["user_id"])
		require.Equal(t, "本组织网关", row["username"])
		require.Equal(t, "same-model", row["model_name"])
	}
}
