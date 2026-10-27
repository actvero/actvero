package billingexpr

import (
	"fmt"
	"math"

	"github.com/expr-lang/expr/ast"
	"github.com/expr-lang/expr/parser"
)

type admissionInterval struct{ lo, hi float64 }

// AdmissionBound analyzes the same validated expression used by settlement.
// Conditions include every branch (including time and request-dependent tiers).
// Unknown quantities and unbounded arithmetic fail closed instead of pricing at zero.
func AdmissionBound(expression string, input, output int) (float64, error) {
	if input <= 0 || output <= 0 || input > 100000000 || output > 100000000 {
		return 0, fmt.Errorf("invalid admission limits")
	}
	if _, err := CompileFromCache(expression); err != nil {
		return 0, err
	}
	_, body := ParseExprVersion(expression)
	tree, err := parser.Parse(body)
	if err != nil {
		return 0, err
	}
	var walk func(ast.Node) (admissionInterval, error)
	bad := func() (admissionInterval, error) {
		return admissionInterval{}, fmt.Errorf("expression has no supported finite admission bound")
	}
	walk = func(node ast.Node) (admissionInterval, error) {
		var result admissionInterval
		switch n := node.(type) {
		case *ast.IntegerNode:
			result = admissionInterval{float64(n.Value), float64(n.Value)}
		case *ast.FloatNode:
			result = admissionInterval{n.Value, n.Value}
		case *ast.IdentifierNode:
			switch n.Value {
			case "p", "len", "cr", "cc", "cc1h", "cc12h", "img", "img_cr", "ai":
				result.hi = float64(input)
			case "c", "img_o", "ao":
				result.hi = float64(output)
			case "image_count":
				result = admissionInterval{1, 1}
			default:
				return bad()
			}
		case *ast.ConditionalNode:
			a, err := walk(n.Exp1)
			if err != nil {
				return a, err
			}
			b, err := walk(n.Exp2)
			if err != nil {
				return b, err
			}
			result = admissionInterval{math.Min(a.lo, b.lo), math.Max(a.hi, b.hi)}
		case *ast.UnaryNode:
			a, err := walk(n.Node)
			if err != nil {
				return a, err
			}
			switch n.Operator {
			case "+":
				result = a
			case "-":
				result = admissionInterval{-a.hi, -a.lo}
			default:
				return bad()
			}
		case *ast.BinaryNode:
			a, err := walk(n.Left)
			if err != nil {
				return a, err
			}
			b, err := walk(n.Right)
			if err != nil {
				return b, err
			}
			switch n.Operator {
			case "+":
				result = admissionInterval{a.lo + b.lo, a.hi + b.hi}
			case "-":
				result = admissionInterval{a.lo - b.hi, a.hi - b.lo}
			case "*", "/":
				if n.Operator == "/" {
					if b.lo <= 0 && b.hi >= 0 {
						return bad()
					}
					b = admissionInterval{1 / b.hi, 1 / b.lo}
				}
				values := []float64{a.lo * b.lo, a.lo * b.hi, a.hi * b.lo, a.hi * b.hi}
				result = admissionInterval{values[0], values[0]}
				for _, v := range values {
					result.lo = math.Min(result.lo, v)
					result.hi = math.Max(result.hi, v)
				}
			default:
				return bad()
			}
		case *ast.CallNode:
			fn, ok := n.Callee.(*ast.IdentifierNode)
			if !ok {
				return bad()
			}
			switch fn.Value {
			case "tier":
				if len(n.Arguments) != 2 {
					return bad()
				}
				return walk(n.Arguments[1])
			case "fixed", "ceil", "floor", "abs":
				if len(n.Arguments) != 1 {
					return bad()
				}
				a, err := walk(n.Arguments[0])
				if err != nil {
					return a, err
				}
				switch fn.Value {
				case "fixed":
					result = admissionInterval{a.lo * 1000000, a.hi * 1000000}
				case "ceil":
					result = admissionInterval{math.Ceil(a.lo), math.Ceil(a.hi)}
				case "floor":
					result = admissionInterval{math.Floor(a.lo), math.Floor(a.hi)}
				case "abs":
					result = admissionInterval{0, math.Max(math.Abs(a.lo), math.Abs(a.hi))}
				}
			case "min", "max":
				if len(n.Arguments) != 2 {
					return bad()
				}
				a, err := walk(n.Arguments[0])
				if err != nil {
					return a, err
				}
				b, err := walk(n.Arguments[1])
				if err != nil {
					return b, err
				}
				f := math.Max
				if fn.Value == "min" {
					f = math.Min
				}
				result = admissionInterval{f(a.lo, b.lo), f(a.hi, b.hi)}
			default:
				return bad()
			}
		default:
			return bad()
		}
		if math.IsNaN(result.lo) || math.IsNaN(result.hi) || math.IsInf(result.lo, 0) || math.IsInf(result.hi, 0) {
			return bad()
		}
		return result, nil
	}
	result, err := walk(tree.Node)
	if err != nil {
		return 0, err
	}
	if result.hi < 0 {
		return 0, fmt.Errorf("negative admission price")
	}
	return result.hi, nil
}
