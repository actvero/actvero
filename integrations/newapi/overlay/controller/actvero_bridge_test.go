package controller

import (
	"bytes"
	"encoding/json"
	"fmt"
	"gorm.io/gorm"
	"net/http/httptest"
	"os"
	"strings"
	"testing"

	"github.com/QuantumNous/new-api/common"
	"github.com/QuantumNous/new-api/model"
	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"
)

const actveroOrgA = "00000000-0000-4000-8000-000000000001"
const actveroOrgB = "00000000-0000-4000-8000-000000000002"

func actveroTestBridge(t *testing.T, owner, method, path string, payload any, params map[string]any) map[string]any {
	t.Helper()
	raw, err := json.Marshal(map[string]any{"method": method, "path": path, "payload": payload, "params": params})
	require.NoError(t, err)
	recorder := httptest.NewRecorder()
	ctx, _ := gin.CreateTestContext(recorder)
	ctx.Request = httptest.NewRequest("POST", "/api/actvero/organizations/"+owner+"/bridge", bytes.NewReader(raw))
	ctx.Request.Header.Set("Content-Type", "application/json")
	ctx.Params = gin.Params{{Key: "organization", Value: owner}}
	ctx.Set("id", 1)
	ctx.Set("role", common.RoleRootUser)
	ActveroOrganizationBridge(ctx)
	var packet map[string]any
	require.NoError(t, json.Unmarshal(recorder.Body.Bytes(), &packet), recorder.Body.String())
	return packet
}
func TestActveroOrganizationBridgeIsolation(t *testing.T) {
	database := actveroTestDatabase(t)
	require.NoError(t, database.AutoMigrate(&model.ActveroOrganization{}, &model.Token{}, &model.UserAccessToken{}, &model.PrefillGroup{}))
	t.Setenv("ACTVERO_ORGANIZATION_ISOLATION", "true")
	a, err := model.ActveroConnect(actveroOrgA)
	require.NoError(t, err)
	b, err := model.ActveroConnect(actveroOrgB)
	require.NoError(t, err)
	require.NotEqual(t, a.Key, b.Key)
	require.NotEqual(t, a.UserId, b.UserId)
	require.NotEqual(t, a.Group, b.Group)
	again, err := model.ActveroConnect(actveroOrgA)
	require.NoError(t, err)
	require.Equal(t, a.Id, again.Id)
	require.Equal(t, a.Key, again.Key)
	ids := map[string]int{}
	for _, owner := range []string{actveroOrgA, actveroOrgB} {
		result := actveroTestBridge(t, owner, "POST", "/api/channel/", map[string]any{"mode": "single", "channel": map[string]any{"name": "Same supplier", "type": 1, "key": "fixture-only", "models": "same-model", "group": "default", "model_mapping": "{}"}}, nil)
		require.Equal(t, true, result["success"], result)
		result = actveroTestBridge(t, owner, "GET", "/api/channel/", nil, map[string]any{"p": 1, "page_size": 1})
		require.Equal(t, true, result["success"], result)
		data := result["data"].(map[string]any)
		require.Equal(t, float64(1), data["total"])
		row := data["items"].([]any)[0].(map[string]any)
		require.Equal(t, "Same supplier", row["name"])
		require.Equal(t, "same-model", row["models"])
		require.Equal(t, "default", row["group"])
		ids[owner] = int(row["id"].(float64))
		result = actveroTestBridge(t, owner, "POST", "/api/models/", map[string]any{"model_name": "same-model", "status": 1, "sync_official": 0}, nil)
		require.Equal(t, true, result["success"], result)
		snapshot := actveroTestBridge(t, owner, "GET", "/api/option/model_pricing", nil, map[string]any{"model": []string{"same-model"}})
		require.Equal(t, true, snapshot["success"], snapshot)
		entry := snapshot["data"].(map[string]any)["entries"].([]any)[0].(map[string]any)
		price := 0.1
		if owner == actveroOrgB {
			price = 0.2
		}
		result = actveroTestBridge(t, owner, "PATCH", "/api/option/model_pricing", map[string]any{"changes": []any{map[string]any{"model_name": "same-model", "expected_version": entry["version"], "pricing": map[string]any{"ModelPrice": price}}}}, nil)
		require.Equal(t, true, result["success"], result)
	}
	for _, owner := range []string{actveroOrgA, actveroOrgB} {
		sources := actveroTestBridge(t, owner, "GET", "/api/ratio_sync/channels", nil, nil)
		require.Equal(t, true, sources["success"], sources)
		rows := sources["data"].([]any)
		require.Len(t, rows, 3)
		for _, value := range rows {
			row := value.(map[string]any)
			if row["id"].(float64) > 0 {
				require.Equal(t, float64(ids[owner]), row["id"])
				require.Equal(t, "https://api.openai.com", row["base_url"])
				require.NotContains(t, row, "key")
			}
		}
		foreign := ids[actveroOrgA]
		if owner == actveroOrgA {
			foreign = ids[actveroOrgB]
		}
		for _, operation := range []struct {
			method, path string
			body         any
		}{{"GET", "/api/channel/%d", nil}, {"DELETE", "/api/channel/%d", nil}, {"POST", "/api/channel/%d/status", map[string]any{"status": 2}}, {"GET", "/api/channel/test/%d", nil}, {"GET", "/api/channel/fetch_models/%d", nil}, {"PUT", "/api/channel", map[string]any{"id": foreign, "name": "forged"}}} {
			path := operation.path
			if operation.body == nil || operation.method == "POST" {
				path = fmt.Sprintf(path, foreign)
			}
			result := actveroTestBridge(t, owner, operation.method, path, operation.body, nil)
			require.Equal(t, false, result["success"], result)
		}
		result := actveroTestBridge(t, owner, "GET", "/api/models/", nil, nil)
		require.Equal(t, float64(1), result["data"].(map[string]any)["total"])
		snapshot := actveroTestBridge(t, owner, "GET", "/api/option/model_pricing", nil, map[string]any{"model": []string{"same-model"}})
		entry := snapshot["data"].(map[string]any)["entries"].([]any)[0].(map[string]any)
		price := 0.1
		if owner == actveroOrgB {
			price = 0.2
		}
		require.Equal(t, price, entry["configured"].(map[string]any)["ModelPrice"])
		require.NotContains(t, string(mustActveroJSON(snapshot)), "avt_")
	}
	prefix, _ := common.ActveroNamespace(actveroOrgA)
	other, _ := common.ActveroNamespace(actveroOrgB)
	for _, rule := range []int{model.NameRuleExact, model.NameRulePrefix, model.NameRuleContains, model.NameRuleSuffix} {
		metadata := model.Model{ModelName: prefix + "same-model", NameRule: rule}
		require.True(t, metadata.MatchesName(prefix+"same-model"))
		require.False(t, metadata.MatchesName(other+"same-model"))
		require.False(t, metadata.MatchesName("same-model"))
	}
	require.Equal(t, false, actveroTestBridge(t, actveroOrgA, "POST", "/api/option/model_pricing/preflight", map[string]any{"token_id": b.Id, "model": "same-model"}, nil)["success"])
}
func mustActveroJSON(value any) []byte { raw, _ := json.Marshal(value); return raw }

func TestActveroAdoptionPreservesHistoricalBilling(t *testing.T) {
	t.Setenv("ACTVERO_ORGANIZATION_ISOLATION", "true")
	db := actveroTestDatabase(t)
	require.NoError(t, db.AutoMigrate(&model.ActveroOrganization{}, &model.Token{}, &model.UserAccessToken{}, &model.PrefillGroup{}))
	legacy := model.Token{UserId: 1, Key: "original-relay", Group: "default", Status: common.TokenStatusEnabled}
	require.NoError(t, db.Create(&legacy).Error)
	channel := model.Channel{Name: "legacy", Models: "same-model", Group: "default", Type: 1, Key: "private"}
	require.NoError(t, db.Create(&channel).Error)
	require.NoError(t, model.ActveroAdopt(actveroOrgA, legacy.Id))
	require.NoError(t, model.ActveroAdopt(actveroOrgA, legacy.Id))
	prefix, _ := common.ActveroNamespace(actveroOrgA)
	var saved model.Channel
	require.NoError(t, db.First(&saved, channel.Id).Error)
	require.Equal(t, prefix+"same-model", saved.Models)
	var original model.Token
	require.NoError(t, db.First(&original, legacy.Id).Error)
	require.Equal(t, "original-relay", original.Key)
	require.Equal(t, legacy.Id, func() int {
		var org model.ActveroOrganization
		require.NoError(t, db.First(&org, "owner = ?", actveroOrgA).Error)
		return org.LegacyTokenID
	}())
	_, err := model.ActveroConnect(actveroOrgB)
	require.NoError(t, err)
	require.Error(t, model.ActveroAdopt(actveroOrgB, legacy.Id))
}

func TestActveroBootstrapOwnsOnlyBridgeCredential(t *testing.T) {
	db := actveroTestDatabase(t)
	require.NoError(t, db.AutoMigrate(&model.UserAccessToken{}))
	existing := model.User{Username: "existing-admin", Password: "fixture-hash", Role: common.RoleRootUser, Status: common.UserStatusEnabled}
	require.NoError(t, db.Create(&existing).Error)
	raw := "nap_" + strings.Repeat("a", 64)
	t.Setenv("ACTVERO_BOOTSTRAP_TOKEN", raw)
	require.NoError(t, model.ActveroBootstrap())
	require.NoError(t, model.ActveroBootstrap())
	var tokens []model.UserAccessToken
	require.NoError(t, db.Find(&tokens).Error)
	require.Len(t, tokens, 1)
	require.Equal(t, []string{"actvero:write"}, tokens[0].GetScopes())
	t.Setenv("ACTVERO_BOOTSTRAP_TOKEN", "nap_"+strings.Repeat("b", 64))
	require.Error(t, model.ActveroBootstrap())
	var count int64
	require.NoError(t, db.Model(&model.UserAccessToken{}).Count(&count).Error)
	require.Equal(t, int64(1), count)
}

func actveroTestDatabase(t *testing.T) *gorm.DB {
	if dsn := os.Getenv("TEST_ACTVERO_POSTGRES_DSN"); dsn != "" {
		return modelManagementDB(t, "postgres", dsn)
	}
	return modelManagementDB(t, "sqlite", "")
}

func TestActveroNamespaceInheritsBuiltinExpressionWithoutSharedOverrides(t *testing.T) {
	db := actveroTestDatabase(t)
	t.Setenv("ACTVERO_ORGANIZATION_ISOLATION", "true")
	require.NoError(t, db.AutoMigrate(&model.ActveroOrganization{}, &model.Token{}))
	_, err := model.ActveroConnect(actveroOrgA)
	require.NoError(t, err)
	_, err = model.ActveroConnect(actveroOrgB)
	require.NoError(t, err)
	for _, owner := range []string{actveroOrgA, actveroOrgB} {
		packet := actveroTestBridge(t, owner, "GET", "/api/option/model_pricing", nil, map[string]any{"model": []string{"deepseek-flash"}})
		require.Equal(t, true, packet["success"])
		entry := packet["data"].(map[string]any)["entries"].([]any)[0].(map[string]any)
		effective := entry["effective"].(map[string]any)
		require.Equal(t, "tiered_expr", effective["billing_setting.billing_mode"])
		require.NotEmpty(t, effective["billing_setting.billing_expr"])
		if owner == actveroOrgA {
			update := actveroTestBridge(t, owner, "PATCH", "/api/option/model_pricing", map[string]any{"changes": []any{map[string]any{"model_name": "deepseek-flash", "expected_version": entry["version"], "pricing": map[string]any{"ModelRatio": 5, "CompletionRatio": 1, "billing_setting.billing_mode": "ratio"}}}}, nil)
			require.Equal(t, true, update["success"], update)
		}
	}
}
