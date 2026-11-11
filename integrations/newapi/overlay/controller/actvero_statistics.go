package controller

import (
	"github.com/QuantumNous/new-api/common"
	"github.com/QuantumNous/new-api/model"
	"github.com/gin-gonic/gin"
	"net/url"
	"strings"
)

func actveroStatisticIdentity(c *gin.Context, q url.Values) error {
	var org model.ActveroOrganization
	if err := model.DB.First(&org, "owner = ?", c.GetString("actvero_owner")).Error; err != nil {
		return err
	}
	c.Set("id", org.UserID)
	c.Set("role", common.RoleCommonUser)
	q.Del("username")
	q.Del("user_id")
	return nil
}

func actveroMetricGroups(c *gin.Context, groups []string) []string {
	prefix := c.GetString("actvero_prefix")
	if prefix == "" {
		return groups
	}
	owned := []string{prefix + "default"}
	for _, group := range groups {
		if strings.HasPrefix(group, prefix) && group != prefix+"default" {
			owned = append(owned, group)
		}
	}
	return owned
}

func actveroPublicStatistics(value any) any {
	switch v := value.(type) {
	case []any:
		for i, item := range v {
			v[i] = actveroPublicStatistics(item)
		}
		return v
	case map[string]any:
		for key, item := range v {
			if key == "username" {
				v[key] = "本组织网关"
			} else {
				v[key] = actveroPublicStatistics(item)
			}
		}
		return v
	}
	return value
}
