package model

import (
	"encoding/json"
	"errors"
	"os"
	"strconv"
	"strings"

	"github.com/QuantumNous/new-api/common"
	"github.com/QuantumNous/new-api/setting/ratio_setting"
	"gorm.io/gorm"
)

// Explicit, one-time adoption of a previously single-organization instance.
// Original logs and relay tokens stay immutable for pending Actvero settlements.
func ActveroAdoptConfigured() error {
	owner := os.Getenv("ACTVERO_ADOPT_ORGANIZATION")
	if owner == "" {
		return nil
	}
	tokenID, err := strconv.Atoi(os.Getenv("ACTVERO_ADOPT_RELAY_TOKEN_ID"))
	if err != nil || tokenID < 1 {
		return errors.New("adoption requires the original relay token ID")
	}
	return ActveroAdopt(owner, tokenID)
}
func ActveroAdopt(owner string, legacyTokenID int) error {
	prefix, valid := common.ActveroNamespace(owner)
	if !valid {
		return errors.New("invalid adoption owner")
	}
	if _, err := ActveroConnect(owner); err != nil {
		return err
	}
	err := mutateModelPricingOptions(func(tx *gorm.DB, values map[string]map[string]any) error {
		var org ActveroOrganization
		if err := lockForUpdate(tx).First(&org, "owner = ?", owner).Error; err != nil {
			return err
		}
		if org.LegacyTokenID > 0 {
			if org.LegacyTokenID == legacyTokenID {
				return nil
			}
			return errors.New("organization already adopted another relay")
		}
		var others int64
		if err := tx.Model(&ActveroOrganization{}).Where("owner <> ?", owner).Count(&others).Error; err != nil {
			return err
		}
		if others > 0 {
			return errors.New("legacy adoption requires an otherwise unassigned gateway")
		}
		var token Token
		if err := tx.First(&token, legacyTokenID).Error; err != nil {
			return err
		}
		if token.Group != "default" || token.CrossGroupRetry {
			return errors.New("legacy adoption requires a fixed default relay group")
		}
		if token.Id == org.TokenID {
			return errors.New("adopt the original relay, not the organization relay")
		}
		var channels []Channel
		if err := tx.Find(&channels).Error; err != nil {
			return err
		}
		names := map[string]bool{}
		for _, channel := range channels {
			if p, _ := common.ActveroSplitName(channel.Name); p != "" {
				if p != prefix {
					return errors.New("another namespace exists")
				}
				continue
			}
			if channel.GetSetting().Proxy != "" {
				return errors.New("remove organization channel proxies before adoption")
			}
			mapping := map[string]string{}
			if channel.ModelMapping != nil && *channel.ModelMapping != "" {
				if err := json.Unmarshal([]byte(*channel.ModelMapping), &mapping); err != nil {
					return err
				}
			}
			nativeMapping := map[string]string{}
			models := strings.Split(channel.Models, ",")
			for i, name := range models {
				names[name] = true
				target := mapping[name]
				if target == "" {
					target = name
				}
				nativeMapping[prefix+name] = target
				models[i] = prefix + name
			}
			encoded, _ := json.Marshal(nativeMapping)
			groups := strings.Split(channel.Group, ",")
			for i, name := range groups {
				groups[i] = prefix + name
			}
			updates := map[string]any{"name": prefix + channel.Name, "models": strings.Join(models, ","), "group": strings.Join(groups, ","), "model_mapping": string(encoded)}
			if channel.Tag != nil && *channel.Tag != "" {
				updates["tag"] = prefix + *channel.Tag
			}
			if channel.TestModel != nil && *channel.TestModel != "" {
				updates["test_model"] = prefix + *channel.TestModel
			}
			if err := tx.Model(&Channel{}).Where("id = ?", channel.Id).Updates(updates).Error; err != nil {
				return err
			}
			channel.Name = prefix + channel.Name
			channel.Models = strings.Join(models, ",")
			channel.Group = strings.Join(groups, ",")
			if err := channel.UpdateAbilities(tx); err != nil {
				return err
			}
		}
		var metadata []Model
		if err := tx.Find(&metadata).Error; err != nil {
			return err
		}
		for _, row := range metadata {
			if p, _ := common.ActveroSplitName(row.ModelName); p == "" {
				names[row.ModelName] = true
				if err := tx.Model(&Model{}).Where("id = ?", row.Id).Update("model_name", prefix+row.ModelName).Error; err != nil {
					return err
				}
			}
		}
		var vendors []Vendor
		if err := tx.Find(&vendors).Error; err != nil {
			return err
		}
		for _, row := range vendors {
			if p, _ := common.ActveroSplitName(row.Name); p == "" {
				if err := tx.Model(&Vendor{}).Where("id = ?", row.Id).Update("name", prefix+row.Name).Error; err != nil {
					return err
				}
			}
		}
		var prefills []PrefillGroup
		if err := tx.Find(&prefills).Error; err != nil {
			return err
		}
		for _, row := range prefills {
			if p, _ := common.ActveroSplitName(row.Name); p == "" {
				if err := tx.Model(&PrefillGroup{}).Where("id = ?", row.Id).Update("name", prefix+row.Name).Error; err != nil {
					return err
				}
			}
		}
		for _, entries := range values {
			original := map[string]any{}
			for name, price := range entries {
				if p, _ := common.ActveroSplitName(name); p == "" {
					original[name] = price
				}
			}
			for name, price := range original {
				entries[prefix+name] = price
			}
		}
		var groupOption Option
		if err := lockForUpdate(tx).First(&groupOption, commonKeyCol+" = ?", "GroupRatio").Error; err != nil {
			return err
		}
		ratios := map[string]float64{}
		if err := json.Unmarshal([]byte(groupOption.Value), &ratios); err != nil {
			return err
		}
		originals := map[string]float64{}
		for name, ratio := range ratios {
			if p, _ := common.ActveroSplitName(name); p == "" {
				originals[name] = ratio
			}
		}
		for name, ratio := range originals {
			ratios[prefix+name] = ratio
		}
		raw, _ := json.Marshal(ratios)
		if err := tx.Model(&groupOption).Update("value", string(raw)).Error; err != nil {
			return err
		}
		if err := tx.Model(&token).Update("status", common.TokenStatusDisabled).Error; err != nil {
			return err
		}
		return tx.Model(&org).Update("legacy_token_id", legacyTokenID).Error
	})
	if err != nil {
		return err
	}
	var groups Option
	if err := DB.First(&groups, commonKeyCol+" = ?", "GroupRatio").Error; err != nil {
		return err
	}
	if err := ratio_setting.UpdateGroupRatioByJSONString(groups.Value); err != nil {
		return err
	}
	InitChannelCache()
	return nil
}
