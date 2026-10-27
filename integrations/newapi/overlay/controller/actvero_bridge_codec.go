package controller

import (
	"encoding/json"
	"errors"
	"math"
	"os"
	"strings"
	"unicode/utf8"

	"github.com/QuantumNous/new-api/common"
	"github.com/QuantumNous/new-api/model"
	"gorm.io/gorm"
)

func actveroScope(db *gorm.DB, field, prefix string) *gorm.DB {
	// The namespace contains underscores: never use it as an unescaped LIKE pattern.
	return db.Where("substr("+field+", 1, ?) = ?", len(prefix), prefix)
}
func actveroOwnsID(prefix, kind string, id int) bool {
	var row any
	field := "name"
	switch kind {
	case "channel":
		row = &model.Channel{}
	case "models":
		row = &model.Model{}
		field = "model_name"
	case "vendors":
		row = &model.Vendor{}
	case "prefill_group":
		row = &model.PrefillGroup{}
	default:
		return false
	}
	var count int64
	return actveroScope(model.DB.Model(row), field, prefix).Where("id = ?", id).Count(&count).Error == nil && count == 1
}
func actveroID(value any) (int, bool) {
	n, ok := value.(float64)
	return int(n), ok && n > 0 && n <= math.MaxInt32 && math.Trunc(n) == n
}
func actveroOwnsNumber(prefix, kind string, value any) bool {
	id, ok := actveroID(value)
	return ok && actveroOwnsID(prefix, kind, id)
}
func actveroZeroOrOwn(prefix, kind string, value any) bool {
	if value == nil || value == float64(0) {
		return true
	}
	return actveroOwnsNumber(prefix, kind, value)
}
func actveroOwnsNumbers(prefix, kind string, value any) bool {
	ids, ok := value.([]any)
	if !ok || len(ids) > 1000 {
		return false
	}
	for _, id := range ids {
		if !actveroOwnsNumber(prefix, kind, id) {
			return false
		}
	}
	return true
}
func actveroCSV(prefix, raw string) string {
	if strings.TrimSpace(raw) == "" {
		return ""
	}
	names := strings.Split(raw, ",")
	for i, name := range names {
		names[i] = prefix + strings.TrimSpace(name)
	}
	return strings.Join(names, ",")
}
func actveroChannelPayload(prefix string, body map[string]any, create bool) error {
	bad := errors.New("invalid organization channel")
	if os.Getenv("ACTVERO_ORGANIZATION_ISOLATION") != "true" {
		return errors.New("organization egress protection is required")
	}
	var channel model.Channel
	rawChannel, _ := json.Marshal(body)
	if json.Unmarshal(rawChannel, &channel) != nil {
		return bad
	}
	if channel.GetSetting().Proxy != "" {
		return errors.New("organization channel proxies require deployment configuration")
	}
	for _, key := range []string{"name", "test_model", "tag"} {
		if value, ok := body[key].(string); ok && value != "" {
			if key == "name" {
				name, err := actveroName(prefix, value, 200)
				if err != nil {
					return err
				}
				body[key] = name
			} else {
				body[key] = prefix + value
			}
		}
	}
	if create {
		if n, ok := body["name"].(string); !ok || len(n) <= len(prefix) {
			return bad
		}
		if _, ok := body["group"]; !ok {
			body["group"] = "default"
		}
	}
	if groups, ok := body["group"].(string); ok {
		body["group"] = actveroCSV(prefix, groups)
	}
	var mappings map[string]string
	raw, _ := body["model_mapping"].(string)
	if raw != "" && json.Unmarshal([]byte(raw), &mappings) != nil {
		return bad
	}
	models, provided := body["models"].(string)
	// Updating model selection without a mapping still regenerates identity mappings.
	if provided {
		native := map[string]string{}
		for _, name := range strings.Split(models, ",") {
			name = strings.TrimSpace(name)
			if name == "" {
				continue
			}
			target := name
			if mapped := mappings[name]; mapped != "" {
				target = mapped
			}
			native[prefix+name] = target
		}
		encoded, _ := json.Marshal(native)
		body["model_mapping"] = string(encoded)
		body["models"] = actveroCSV(prefix, models)
	} else if raw != "" {
		native := map[string]string{}
		for name, target := range mappings {
			native[prefix+name] = target
		}
		encoded, _ := json.Marshal(native)
		body["model_mapping"] = string(encoded)
	}
	return nil
}
func actveroQualifyFields(prefix string, value any) {
	switch v := value.(type) {
	case map[string]any:
		for key, item := range v {
			if key == "model_name" || key == "model" || key == "group" {
				if name, ok := item.(string); ok && name != "" {
					v[key] = prefix + name
					continue
				}
			}
			actveroQualifyFields(prefix, item)
		}
	case []any:
		for _, item := range v {
			actveroQualifyFields(prefix, item)
		}
	}
}
func actveroPublicValue(prefix string, value any, key string) any {
	switch v := value.(type) {
	case string:
		if key == "model_mapping" {
			var mappings map[string]string
			if json.Unmarshal([]byte(v), &mappings) == nil {
				out := map[string]string{}
				for name, target := range mappings {
					public := strings.TrimPrefix(name, prefix)
					if target != public {
						out[public] = target
					}
				}
				raw, _ := json.Marshal(out)
				return string(raw)
			}
		}
		if key == "models" || key == "group" {
			items := strings.Split(v, ",")
			for i, name := range items {
				items[i] = strings.TrimPrefix(name, prefix)
			}
			return strings.Join(items, ",")
		}
		return strings.TrimPrefix(v, prefix)
	case []any:
		for i, item := range v {
			v[i] = actveroPublicValue(prefix, item, key)
		}
		return v
	case map[string]any:
		result := map[string]any{}
		for name, item := range v {
			// Native pricing options are global maps serialized as JSON strings. Keep only this namespace.
			if key == "options" && model.IsModelPricingOption(name) {
				var entries map[string]any
				if text, ok := item.(string); ok && json.Unmarshal([]byte(text), &entries) == nil {
					owned := map[string]any{}
					for n, p := range entries {
						if strings.HasPrefix(n, prefix) {
							owned[strings.TrimPrefix(n, prefix)] = p
						}
					}
					raw, _ := json.Marshal(owned)
					result[name] = string(raw)
				}
				continue
			}
			result[strings.TrimPrefix(name, prefix)] = actveroPublicValue(prefix, item, name)
		}
		return result
	}
	return value
}
func actveroJSON(prefix string, value any) any {
	raw, _ := common.Marshal(value)
	var packet any
	_ = json.Unmarshal(raw, &packet)
	return actveroPublicValue(prefix, packet, "")
}

func actveroPricingSyncData(prefix string, data map[string]any, upstream bool) map[string]any {
	if prefix == "" {
		return data
	}
	result := map[string]any{}
	for field, raw := range data {
		entries := valueMap(raw)
		owned := map[string]any{}
		for name, price := range entries {
			if upstream {
				owned[prefix+name] = price
			} else if strings.HasPrefix(name, prefix) {
				owned[name] = price
			}
		}
		result[field] = owned
	}
	return result
}

func actveroName(prefix string, value string, limit int) (string, error) {
	value = strings.TrimSpace(value)
	if value == "" || utf8.RuneCountInString(value) > limit {
		return "", errors.New("invalid public resource name")
	}
	return prefix + value, nil
}
