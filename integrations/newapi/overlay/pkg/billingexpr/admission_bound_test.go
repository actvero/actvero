package billingexpr

import (
	"math"
	"testing"
)

func TestAdmissionBoundCoversNativeSettlements(t *testing.T) {
	expressions := []string{
		`tier("flat", p*2+c*8+cr*0.2+cc*3)`,
		`len>200 ? tier("long",p*4+c*12) : tier("short",p*2+c*6)`,
		`(hour("UTC")<8 ? tier("offpeak",p*1+c*2) : tier("peak",p*3+c*8)) * (param("service_tier")=="priority" ? 2 : 1)`,
		`tier("request",fixed(0.01))`,
		`tier("free",0)`,
	}
	for _, expression := range expressions {
		bound, err := AdmissionBound(expression, 1000, 500)
		if err != nil {
			t.Fatalf("bound %s: %v", expression, err)
		}
		for _, input := range []float64{0, 1, 200, 999, 1000} {
			for _, output := range []float64{0, 1, 499, 500} {
				actual, _, err := RunExprWithRequest(expression, TokenParams{P: input, C: output, Len: input, CR: input / 2, CC: input / 4}, RequestInput{Body: []byte(`{"service_tier":"priority"}`)})
				if err != nil || actual > bound+math.Abs(bound)*1e-12 {
					t.Fatalf("actual=%v bound=%v err=%v for %s", actual, bound, err, expression)
				}
			}
		}
	}
}

func TestAdmissionBoundRejectsUnboundedOrInvalidAmounts(t *testing.T) {
	for _, expression := range []string{`tier("bad",p/(c-5))`, `tier("bad",p*param("arbitrary"))`, `tier("task",u("second")*3)`, `tier("huge",p*1e308)`, `tier("negative",-1)`} {
		if _, err := AdmissionBound(expression, 1000, 500); err == nil {
			t.Fatalf("accepted %s", expression)
		}
	}
	if _, err := AdmissionBound(`tier("price",p)`, 0, 500); err == nil {
		t.Fatal("accepted missing limit")
	}
}
