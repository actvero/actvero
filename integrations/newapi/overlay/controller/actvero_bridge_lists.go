package controller

import (
	"net/url"
	"sort"
	"strconv"
	"strings"

	"github.com/QuantumNous/new-api/common"
	"github.com/QuantumNous/new-api/model"
	"github.com/QuantumNous/new-api/relaykit/dto"
	"github.com/gin-gonic/gin"
	"gorm.io/gorm/clause"
)

func actveroPage(q url.Values) (int, int) {
	p, _ := strconv.Atoi(q.Get("p"))
	size, _ := strconv.Atoi(q.Get("page_size"))
	if p < 1 {
		p = 1
	}
	if size < 1 {
		size = 20
	}
	if size > 1000 {
		size = 1000
	}
	return p, size
}
func actveroRespond(c *gin.Context, prefix string, value any) {
	common.ApiSuccess(c, actveroJSON(prefix, value))
}
func actveroListChannels(c *gin.Context, prefix string, q url.Values) {
	query := actveroScope(model.DB.Model(&model.Channel{}), "name", prefix)
	if s := q.Get("keyword"); s != "" {
		id, _ := strconv.Atoi(s)
		query = query.Where("name LIKE ? OR id = ?", "%"+s+"%", id)
	}
	if s := q.Get("model"); s != "" {
		query = query.Where("models LIKE ?", "%"+prefix+s+"%")
	}
	if s := q.Get("status"); s != "" && s != "-1" {
		if s == "1" || s == "enabled" {
			query = query.Where("status = ?", 1)
		} else {
			query = query.Where("status <> ?", 1)
		}
	}
	if s := q.Get("group"); s != "" {
		query = query.Where(clause.Expr{SQL: "? LIKE ?", Vars: []any{clause.Column{Name: "group"}, "%" + prefix + s + "%"}})
	}
	if s := q.Get("type"); s != "" {
		query = query.Where("type = ?", s)
	}
	var total int64
	var rows []*model.Channel
	p, size := actveroPage(q)
	if err := query.Count(&total).Error; err != nil {
		common.ApiError(c, err)
		return
	}
	sorts := model.NewChannelSortOptions(q.Get("sort_by"), q.Get("sort_order"), q.Get("id_sort") == "true")
	if err := sorts.Apply(query).Omit("key").Offset((p - 1) * size).Limit(size).Find(&rows).Error; err != nil {
		common.ApiError(c, err)
		return
	}
	for _, row := range rows {
		clearChannelInfo(row)
	}
	actveroRespond(c, prefix, gin.H{"items": rows, "total": total, "page": p, "page_size": size})
}
func actveroListModels(c *gin.Context, prefix string, q url.Values) {
	var rows []*model.Model
	if err := actveroScope(model.DB, "model_name", prefix).Find(&rows).Error; err != nil {
		common.ApiError(c, err)
		return
	}
	if q.Get("include_channel_models") == "true" && q.Get("status") == "" && q.Get("sync_official") == "" {
		configured, err := model.GetConfiguredModelChannels()
		if err != nil {
			common.ApiError(c, err)
			return
		}
		exact := map[string]bool{}
		for _, row := range rows {
			if row.NameRule == model.NameRuleExact {
				exact[row.ModelName] = true
			}
		}
		for name := range configured {
			if strings.HasPrefix(name, prefix) && !exact[name] {
				rows = append(rows, &model.Model{ModelName: name, NameRule: model.NameRuleExact})
			}
		}
	}
	if err := enrichModels(rows); err != nil {
		common.ApiError(c, err)
		return
	}
	counts := map[int]int{}
	filtered := make([]*model.Model, 0, len(rows))
	for _, row := range rows {
		if row.Id > 0 {
			counts[row.VendorID]++
		}
		if keyword := q.Get("keyword"); keyword != "" && !strings.Contains(strings.ToLower(strings.TrimPrefix(row.ModelName, prefix)), strings.ToLower(keyword)) {
			continue
		}
		if vendor := q.Get("vendor"); vendor != "" && vendor != strconv.Itoa(row.VendorID) {
			continue
		}
		if status := q.Get("status"); status != "" && status != strconv.Itoa(row.Status) {
			continue
		}
		if sync := q.Get("sync_official"); sync != "" && sync != strconv.Itoa(row.SyncOfficial) {
			continue
		}
		if state := q.Get("square_state"); state != "" && state != string(row.SquareState) {
			continue
		}
		filtered = append(filtered, row)
	}
	sort.Slice(filtered, func(i, j int) bool { return filtered[i].ModelName < filtered[j].ModelName })
	p, size := actveroPage(q)
	start := min((p-1)*size, len(filtered))
	end := min(start+size, len(filtered))
	actveroRespond(c, prefix, gin.H{"items": filtered[start:end], "total": len(filtered), "page": p, "page_size": size, "vendor_counts": counts})
}
func actveroListVendors(c *gin.Context, prefix string, q url.Values) {
	query := actveroScope(model.DB.Model(&model.Vendor{}), "name", prefix)
	if s := q.Get("keyword"); s != "" {
		query = query.Where("name LIKE ?", "%"+s+"%")
	}
	var rows []*model.Vendor
	var total int64
	p, size := actveroPage(q)
	if err := query.Count(&total).Error; err != nil {
		common.ApiError(c, err)
		return
	}
	if err := query.Order("id desc").Offset((p - 1) * size).Limit(size).Find(&rows).Error; err != nil {
		common.ApiError(c, err)
		return
	}
	for _, row := range rows {
		model.DB.Model(&model.Model{}).Where("vendor_id = ?", row.Id).Count(&row.ModelCount)
		row.Version = model.VendorRecordVersion(row)
	}
	actveroRespond(c, prefix, gin.H{"items": rows, "total": total, "page": p, "page_size": size})
}
func actveroListGroups(c *gin.Context, prefix string) {
	// Actvero dispatches through a fixed organization group. Arbitrary native groups cannot widen access.
	actveroRespond(c, prefix, []string{prefix + "default"})
}
func actveroListPrefills(c *gin.Context, prefix, kind string) {
	var rows []*model.PrefillGroup
	query := actveroScope(model.DB, "name", prefix)
	if kind != "" {
		query = query.Where("type = ?", kind)
	}
	if err := query.Find(&rows).Error; err != nil {
		common.ApiError(c, err)
		return
	}
	actveroRespond(c, prefix, rows)
}
func actveroChannelModels(c *gin.Context, prefix string) {
	configured, err := model.GetConfiguredModelChannels()
	if err != nil {
		common.ApiError(c, err)
		return
	}
	names := []string{}
	for name := range configured {
		if strings.HasPrefix(name, prefix) {
			names = append(names, name)
		}
	}
	sort.Strings(names)
	actveroRespond(c, prefix, names)
}
func actveroMissingModels(c *gin.Context, prefix string) {
	names, err := model.GetMissingModels()
	if err != nil {
		common.ApiError(c, err)
		return
	}
	owned := []string{}
	for _, name := range names {
		if strings.HasPrefix(name, prefix) {
			owned = append(owned, name)
		}
	}
	actveroRespond(c, prefix, owned)
}
func actveroRatioChannels(c *gin.Context, prefix string) {
	var rows []model.Channel
	if err := actveroScope(model.DB.Model(&model.Channel{}), "name", prefix).Select("id,name,type,status,base_url").Find(&rows).Error; err != nil {
		common.ApiError(c, err)
		return
	}
	out := []dto.SyncableChannel{}
	for _, row := range rows {
		if base := row.GetBaseURL(); base != "" {
			out = append(out, dto.SyncableChannel{ID: row.Id, Name: row.Name, Type: row.Type, Status: row.Status, BaseURL: base})
		}
	}
	out = append(out, dto.SyncableChannel{ID: officialRatioPresetID, Name: officialRatioPresetName, BaseURL: officialRatioPresetBaseURL, Status: 1}, dto.SyncableChannel{ID: modelsDevPresetID, Name: modelsDevPresetName, BaseURL: modelsDevPresetBaseURL, Status: 1})
	actveroRespond(c, prefix, out)
}
func actveroLogs(c *gin.Context, prefix string, q url.Values) {
	var org model.ActveroOrganization
	if err := model.DB.First(&org, "owner = ?", c.GetString("actvero_owner")).Error; err != nil {
		common.ApiError(c, err)
		return
	}
	query := model.LOG_DB.Model(&model.Log{}).Where("user_id = ? OR token_id = ?", org.UserID, func() int {
		if org.LegacyTokenID > 0 {
			return org.LegacyTokenID
		}
		return -1
	}())
	for _, key := range []string{"request_id", "type", "token_id", "channel"} {
		if s := q.Get(key); s != "" {
			field := key
			if key == "channel" {
				field = "channel_id"
			}
			query = query.Where(field+" = ?", s)
		}
	}
	if s := q.Get("model_name"); s != "" {
		query = query.Where("model_name = ?", prefix+s)
	}
	var total int64
	var rows []model.Log
	p, size := actveroPage(q)
	if err := query.Count(&total).Error; err != nil {
		common.ApiError(c, err)
		return
	}
	if err := query.Order("id desc").Offset((p - 1) * size).Limit(size).Find(&rows).Error; err != nil {
		common.ApiError(c, err)
		return
	}
	common.ApiSuccess(c, gin.H{"items": rows, "total": total, "page": p, "page_size": size})
}
func actveroPricing(c *gin.Context, prefix string) {
	prices := []model.Pricing{}
	for _, row := range model.GetPricing() {
		if strings.HasPrefix(row.ModelName, prefix) {
			prices = append(prices, row)
		}
	}
	vendors := []model.PricingVendor{}
	for _, row := range model.GetVendors() {
		if strings.HasPrefix(row.Name, prefix) {
			vendors = append(vendors, row)
		}
	}
	c.JSON(200, actveroJSON(prefix, gin.H{"success": true, "data": prices, "vendors": vendors, "group_ratio": map[string]float64{prefix + "default": 1}, "usable_group": map[string]string{prefix + "default": "default"}, "supported_endpoint": model.GetSupportedEndpointMap(), "auto_groups": []string{}}))
}
