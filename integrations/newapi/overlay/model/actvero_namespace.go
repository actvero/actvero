// Actvero-owned organization provisioning. New API remains the credential and billing owner.
package model

import (
	"encoding/json"
	"errors"
	"math"
	"os"
	"sync"

	"github.com/QuantumNous/new-api/common"
	"github.com/QuantumNous/new-api/setting/ratio_setting"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
)

type ActveroOrganization struct {
	Owner         string `gorm:"primaryKey;size:36"`
	UserID        int    `gorm:"uniqueIndex;not null"`
	LegacyTokenID int
	TokenID       int `gorm:"uniqueIndex;not null"`
}

var actveroProvisionMu sync.Mutex

func ActveroConnect(owner string) (*Token, error) {
	if os.Getenv("ACTVERO_ORGANIZATION_ISOLATION") != "true" {
		return nil, errors.New("organization isolation must be enabled by the deployment")
	}
	prefix, valid := common.ActveroNamespace(owner)
	if !valid {
		return nil, errors.New("invalid organization")
	}
	// Ordinary requests read their existing identity without a deployment-wide write lock.
	var existing ActveroOrganization
	lookup := DB.First(&existing, "owner = ?", owner).Error
	if lookup == nil {
		var token Token
		var user User
		if err := DB.First(&token, existing.TokenID).Error; err != nil {
			return nil, err
		}
		if err := DB.First(&user, existing.UserID).Error; err != nil {
			return nil, err
		}
		if token.UserId != existing.UserID || token.Group != prefix+"default" || token.CrossGroupRetry || !token.UnlimitedQuota || token.Status != common.TokenStatusEnabled || user.Group != prefix+"default" || user.Role != common.RoleCommonUser || user.Status != common.UserStatusEnabled {
			return nil, errors.New("organization identity changed")
		}
		if user.Quota >= math.MaxInt32/2 && ratio_setting.ContainsGroupRatio(prefix+"default") {
			return &token, nil
		}
	} else if !errors.Is(lookup, gorm.ErrRecordNotFound) {
		return nil, lookup
	}
	actveroProvisionMu.Lock()
	defer actveroProvisionMu.Unlock()
	var token Token
	var fundedUser int
	err := DB.Transaction(func(tx *gorm.DB) error {
		// A persistent lock serializes first provisioning across gateway processes.
		anchor := Option{Key: "actvero_organization_lock", Value: ""}
		if err := tx.Clauses(clause.OnConflict{DoNothing: true}).Create(&anchor).Error; err != nil {
			return err
		}
		if err := lockForUpdate(tx).Where(commonKeyCol+" = ?", anchor.Key).First(&anchor).Error; err != nil {
			return err
		}
		var org ActveroOrganization
		err := tx.First(&org, "owner = ?", owner).Error
		if errors.Is(err, gorm.ErrRecordNotFound) {
			password, e := common.GenerateRandomKey(48)
			if e != nil {
				return e
			}
			username, e := common.GenerateRandomCharsKey(16)
			if e != nil {
				return e
			}
			user := User{Username: "avo_" + username, Password: password, DisplayName: "Actvero service", Role: common.RoleCommonUser, Status: common.UserStatusEnabled, Group: prefix + "default"}
			if e := user.InsertWithTx(tx, 0); e != nil {
				return e
			}
			key, e := common.GenerateKey()
			if e != nil {
				return e
			}
			token = Token{UserId: user.Id, Key: key, Name: prefix + "relay", Status: common.TokenStatusEnabled, CreatedTime: common.GetTimestamp(), ExpiredTime: -1, UnlimitedQuota: true, Group: prefix + "default", CrossGroupRetry: false, AllowUserQuotaQuery: false}
			if e := tx.Create(&token).Error; e != nil {
				return e
			}
			org = ActveroOrganization{Owner: owner, UserID: user.Id, TokenID: token.Id}
			if e := tx.Create(&org).Error; e != nil {
				return e
			}
		} else if err != nil {
			return err
		} else if err := tx.First(&token, org.TokenID).Error; err != nil {
			return err
		}
		if token.UserId != org.UserID || token.Group != prefix+"default" || token.CrossGroupRetry || !token.UnlimitedQuota || token.Status != common.TokenStatusEnabled {
			return errors.New("organization relay configuration changed")
		}
		var user User
		if err := tx.First(&user, org.UserID).Error; err != nil {
			return err
		}
		if user.Group != prefix+"default" || user.Role != common.RoleCommonUser || user.Status != common.UserStatusEnabled {
			return errors.New("organization service account changed")
		}
		// This is a funded technical account, not the Actvero member's business quota.
		funded := tx.Model(&User{}).Where("id = ? AND quota < ?", org.UserID, math.MaxInt32/2).Update("quota", math.MaxInt32)
		if funded.Error != nil {
			return funded.Error
		}
		if funded.RowsAffected > 0 {
			fundedUser = org.UserID
		}
		ratios := ratio_setting.GetGroupRatioCopy()
		var saved Option
		e := lockForUpdate(tx).First(&saved, commonKeyCol+" = ?", "GroupRatio").Error
		if e == nil {
			if err := json.Unmarshal([]byte(saved.Value), &ratios); err != nil {
				return err
			}
		} else if !errors.Is(e, gorm.ErrRecordNotFound) {
			return e
		}
		if _, exists := ratios[prefix+"default"]; !exists || errors.Is(e, gorm.ErrRecordNotFound) {
			ratios[prefix+"default"] = 1
			raw, e := common.Marshal(ratios)
			if e != nil {
				return e
			}
			option := Option{Key: "GroupRatio", Value: string(raw)}
			if e := tx.Clauses(clause.OnConflict{Columns: []clause.Column{{Name: "key"}}, DoUpdates: clause.AssignmentColumns([]string{"value"})}).Create(&option).Error; e != nil {
				return e
			}
		}
		return nil
	})
	if err != nil {
		return nil, err
	}
	if fundedUser > 0 {
		if err := invalidateUserCache(fundedUser); err != nil {
			return nil, err
		}
	}
	var option Option
	if err := DB.First(&option, commonKeyCol+" = ?", "GroupRatio").Error; err != nil {
		return nil, err
	}
	if err := ratio_setting.UpdateGroupRatioByJSONString(option.Value); err != nil {
		return nil, err
	}
	return &token, nil
}

// Persist native built-in defaults once, so the relay's live pricing cache sees them too.
func ActveroPrepareModels(prefix string, names []string) error {
	targets := map[string]bool{}
	for _, name := range names {
		targets[name] = true
		targets[ratio_setting.FormatMatchingModelName(name)] = true
	}
	names = make([]string, 0, len(targets))
	for name := range targets {
		names = append(names, name)
	}
	// Most reads are no-ops. Persist only a missing built-in default.
	snapshot, err := GetModelPricingSnapshot(func() []string {
		out := []string{}
		for _, name := range names {
			out = append(out, prefix+name)
		}
		return out
	}())
	if err != nil {
		return err
	}
	needed := false
	defaults := defaultPricingMaps()
	for _, entry := range snapshot.Entries {
		if len(entry.Configured) == 0 && len(ActveroDefaultModelPricing(defaults, entry.ModelName)) > 0 {
			needed = true
		}
	}
	if !needed {
		return nil
	}
	return mutateModelPricingOptions(func(_ *gorm.DB, values map[string]map[string]any) error {
		defaults := defaultPricingMaps()
		for _, name := range names {
			native := prefix + name
			if len(modelPricingValues(values, native)) == 0 {
				inherited := ActveroDefaultModelPricing(defaults, native)
				if len(inherited) > 0 {
					replaceModelPricing(values, native, inherited)
				}
			}
		}
		return nil
	})
}

func ActveroDefaultModelPricing(values map[string]map[string]any, name string) PricingValues {
	_, public := common.ActveroSplitName(name)
	return modelPricingValues(values, public)
}

func ActveroIsolationEnabled() bool {
	if os.Getenv("ACTVERO_ORGANIZATION_ISOLATION") == "true" {
		return true
	}
	if DB == nil || !DB.Migrator().HasTable(&ActveroOrganization{}) {
		return false
	}
	var rows []ActveroOrganization
	return DB.Select("owner").Limit(1).Find(&rows).Error == nil && len(rows) > 0
}
