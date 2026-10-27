package ratio_setting

import (
	"github.com/QuantumNous/new-api/common"
	"reflect"
	"testing"
)

func TestActveroNamespaceKeepsNativeRatioRules(t *testing.T) {
	prefix, _ := common.ActveroNamespace("00000000-0000-4000-8000-000000000001")
	configured := float64(9)
	for _, name := range []string{"gpt-4o-2024-05-13", "gpt-4o", "gemini-2.5-flash-thinking-128", "gpt-4-gizmo-example", "claude-sonnet-4-5"} {
		if FormatMatchingModelName(prefix+name) != prefix+FormatMatchingModelName(name) {
			t.Fatal("ratio alias lost organization", name)
		}
		for _, value := range []*float64{nil, &configured} {
			if !reflect.DeepEqual(ResolveCompletionRatio(name, value), ResolveCompletionRatio(prefix+name, value)) {
				t.Fatal("native completion rule changed", name)
			}
		}
	}
}
