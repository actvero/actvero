package model

import (
	"errors"
	"os"
	"strings"

	"github.com/QuantumNous/new-api/common"
	"gorm.io/gorm"
)

// Opt-in bootstrap owns a dedicated service principal, never an existing administrator.
// The plaintext token is supplied by the deployment secret and is only hashed in SQL.
func ActveroBootstrap() error {
	raw := os.Getenv("ACTVERO_BOOTSTRAP_TOKEN")
	if raw == "" {
		if os.Getenv("ACTVERO_ORGANIZATION_ISOLATION") == "true" && !RootUserExists() {
			return errors.New("a new organization gateway requires a bootstrap credential")
		}
		return nil
	}
	if !strings.HasPrefix(raw, AccessTokenPrefix) || len(raw) < 48 {
		return errors.New("invalid Actvero bootstrap token")
	}
	return DB.Transaction(func(tx *gorm.DB) error {
		var token UserAccessToken
		err := tx.First(&token, "token_hash = ?", AccessTokenFingerprint(raw)).Error
		if err == nil {
			var user User
			if e := tx.First(&user, token.UserId).Error; e != nil {
				return e
			}
			if user.Username != "actvero-svc" || user.Role != common.RoleRootUser || user.Status != common.UserStatusEnabled || token.Scopes != "[\"actvero:write\"]" {
				return errors.New("Actvero bootstrap credential conflict")
			}
			return nil
		}
		if !errors.Is(err, gorm.ErrRecordNotFound) {
			return err
		}
		// A changed secret must be rotated explicitly; restarting cannot grant a new token.
		var count int64
		if e := tx.Model(&User{}).Where("username = ?", "actvero-svc").Count(&count).Error; e != nil {
			return e
		}
		if count > 0 {
			return errors.New("Actvero bootstrap principal already exists; rotate its token explicitly")
		}
		password, e := common.GenerateRandomKey(48)
		if e != nil {
			return e
		}
		hashed, e := common.HashAccountPassword(password)
		if e != nil {
			return e
		}
		affCode, e := common.GenerateRandomCharsKey(16)
		if e != nil {
			return e
		}
		user := User{AffCode: affCode, Username: "actvero-svc", Password: hashed, DisplayName: "Actvero gateway service", Role: common.RoleRootUser, Status: common.UserStatusEnabled, Group: "default"}
		if e := tx.Create(&user).Error; e != nil {
			return e
		}
		token = UserAccessToken{UserId: user.Id, Name: "Actvero organization bridge", TokenHash: AccessTokenFingerprint(raw), TokenHint: AccessTokenHint(raw), CreatedAt: common.GetTimestamp(), Scopes: "[\"actvero:write\"]"}
		return tx.Create(&token).Error
	})
}
