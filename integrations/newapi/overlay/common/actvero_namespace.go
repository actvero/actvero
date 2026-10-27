// Actvero organization identifiers are internal routing names, never public model labels.
package common

import (
	"github.com/google/uuid"
	"strings"
)

func ActveroNamespace(owner string) (string, bool) {
	parsed, err := uuid.Parse(owner)
	if err != nil || parsed.String() != owner {
		return "", false
	}
	id := strings.ReplaceAll(owner, "-", "")
	if len(id) != 32 {
		return "", false
	}
	for _, c := range id {
		if !(c >= '0' && c <= '9' || c >= 'a' && c <= 'f') {
			return "", false
		}
	}
	return "avt_" + id + "__", true
}

func ActveroSplitName(name string) (string, string) {
	if len(name) >= 38 && strings.HasPrefix(name, "avt_") && name[36:38] == "__" {
		raw := name[4:36]
		owner := raw[:8] + "-" + raw[8:12] + "-" + raw[12:16] + "-" + raw[16:20] + "-" + raw[20:]
		if prefix, ok := ActveroNamespace(owner); ok {
			return prefix, name[38:]
		}
	}
	return "", name
}
