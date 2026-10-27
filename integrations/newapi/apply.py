"""Apply the Actvero organization and preflight overlay to a verified New API source tree."""
import shutil
import sys
from pathlib import Path

root = Path(sys.argv[1])
base = Path(__file__).parent
for source in (base / "overlay").rglob("*.go"):
    target = root / source.relative_to(base / "overlay")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
for relative, old, new in [
    ("router/api-router.go", 'optionRoute.GET("/model_pricing", controller.GetModelPricingConfig)', 'optionRoute.GET("/model_pricing", controller.GetModelPricingConfig)\n\t\t\toptionRoute.POST("/model_pricing/preflight", controller.ActveroAdmissionPreview)'),
    ("middleware/access_token_routes.go", '"GET /api/option/model_pricing":', '"POST /api/option/model_pricing/preflight": accessTokenScopeRule("option:read"),\n\t"GET /api/option/model_pricing":'),
    ("relay/channel/openai/relay-openai.go", 'if simpleResponse.Usage.PromptTokens == 0 {', 'actveroConfirmChatUsage(c, &simpleResponse.Usage, responseBody)\n\tif simpleResponse.Usage.PromptTokens == 0 {'),
    ("relay/channel/openai/relay-openai.go", 'applyUsagePostProcessing(info, usage, common.StringToByteSlice(usageFrame))', 'applyUsagePostProcessing(info, usage, common.StringToByteSlice(usageFrame))\n\tif containStreamUsage { actveroConfirmChatUsage(c, usage, common.StringToByteSlice(usageFrame)) }'),
    ("service/text_quota.go", 'appendUsageBillingPathForLog(other, common.GetContextKeyBool(ctx, constant.ContextKeyLocalCountTokens), originUsage)', 'appendUsageBillingPathForLog(other, common.GetContextKeyBool(ctx, constant.ContextKeyLocalCountTokens), originUsage)\n\tif ctx.GetBool("actvero_confirmed_chat_usage") && !common.GetContextKeyBool(ctx, constant.ContextKeyLocalCountTokens) { other.SetAdmin("actvero_upstream_usage_confirmed", true) }'),
]:
    path = root / relative
    text = path.read_text()
    if new in text or "".join(new.split()) in "".join(text.split()):
        continue
    if text.count(old) != 1:
        raise RuntimeError(f"Pinned upstream contract changed: {relative}")
    path.write_text(text.replace(old, new))

# These anchors target the checksummed release, never an unpinned working tree.
patches = [
 ("setting/ratio_setting/model_ratio.go", 'func FormatMatchingModelName(name string) string {', 'func FormatMatchingModelName(name string) string {\n namespace,publicName:=common.ActveroSplitName(name);name=publicName'),
 ("setting/ratio_setting/model_ratio.go", 'return name\n}\n\n// result: 倍率or价格， usePrice， exist', 'return namespace+name\n}\n\n// result: 倍率or价格， usePrice， exist'),
 ("setting/ratio_setting/model_ratio.go", 'func ResolveCompletionRatio(name string, configured *float64) CompletionRatioInfo {', 'func ResolveCompletionRatio(name string, configured *float64) CompletionRatioInfo {\n _,name=common.ActveroSplitName(name)'),

 ("setting/billing_setting/tiered_billing.go", 'if _, ok := builtinBillingExpr[model]; ok {', '_,publicModel:=common.ActveroSplitName(model)\n if _, ok := builtinBillingExpr[publicModel]; ok {'),
 ("setting/billing_setting/tiered_billing.go", 'expr, ok := builtinBillingExpr[model]', '_,publicModel:=common.ActveroSplitName(model)\n expr, ok := builtinBillingExpr[publicModel]'),
 ("setting/billing_setting/tiered_billing.go", 'expression, ok := builtinBillingExpr[model]', '_,publicModel:=common.ActveroSplitName(model)\n expression, ok := builtinBillingExpr[publicModel]'),

 ("common/endpoint_type.go", 'func GetEndpointTypesByChannelType(channelType int, modelName string) []constant.EndpointType {', 'func GetEndpointTypesByChannelType(channelType int, modelName string) []constant.EndpointType {\n _,modelName=ActveroSplitName(modelName)'),
 ("model/pricing.go", 'func getPricingEndpointTypesForAbility(ability AbilityWithChannel, advancedCustomConfigs map[int]*dto.AdvancedCustomConfig) []constant.EndpointType {', 'func getPricingEndpointTypesForAbility(ability AbilityWithChannel, advancedCustomConfigs map[int]*dto.AdvancedCustomConfig) []constant.EndpointType {\n _,ability.Model=common.ActveroSplitName(ability.Model)'),

 ("controller/misc.go", '"quota_per_unit":              common.QuotaPerUnit,', '"quota_per_unit":              common.QuotaPerUnit,\n "actvero_organization_isolation": model.ActveroIsolationEnabled(),'),
 ("service/token_counter.go", 'model := common.GetContextKeyString(c, constant.ContextKeyOriginalModel)', 'model := common.GetContextKeyString(c, constant.ContextKeyOriginalModel)\n _, model = common.ActveroSplitName(model)'),
 ("main.go", 'model.InitOptionMap()', 'model.InitOptionMap()\n if err := model.ActveroAdoptConfigured(); err != nil { return err }'),
 ("service/http_client.go", '\n\treturn transport\n}', '\n common.ActveroSecureTransport(transport)\n\treturn transport\n}'),
 ("controller/ratio_sync.go", 'client := &http.Client{Transport: transport}', 'common.ActveroSecureTransport(transport)\n client := &http.Client{Transport: transport, CheckRedirect: func(req *http.Request,via []*http.Request)error{if len(via)>5{return fmt.Errorf("too many redirects")};return nil}}'),

 ("router/api-router.go", 'optionRoute := apiRouter.Group("/option")', 'actveroRoute := apiRouter.Group("/actvero/organizations/:organization")\n\t\tactveroRoute.Use(middleware.RootAuth())\n\t\tactveroRoute.POST("/connect", controller.ActveroOrganizationConnect)\n\t\tactveroRoute.POST("/bridge", controller.ActveroOrganizationBridge)\n\t\toptionRoute := apiRouter.Group("/option")'),
 ("middleware/access_token_routes.go", 'var accessTokenRouteRules = map[string]accessTokenRouteRule{', 'var accessTokenRouteRules = map[string]accessTokenRouteRule{\n "POST /api/actvero/organizations/:organization/connect": accessTokenScopeRule("actvero:write"),\n "POST /api/actvero/organizations/:organization/bridge": accessTokenScopeRule("actvero:write"),'),
 ("service/access_token_scope.go", 'var accessTokenStaticResources = []AccessTokenResource{', 'var accessTokenStaticResources = []AccessTokenResource{\n {Resource: "actvero", LabelKey: "Actvero organizations", group: AccessTokenGroupSystem, minRole: common.RoleRootUser, Actions: []authz.ActionDefinition{accessTokenEdit("Operate the organization bridge from a trusted Actvero server.")}},'),
 ("model/main.go", 'err := DB.AutoMigrate(\n\t\t&Channel{},', 'err := DB.AutoMigrate(\n\t\t&ActveroOrganization{},\n\t\t&Channel{},'),
 ("main.go", 'model.CheckSetup()', 'if err := model.ActveroBootstrap(); err != nil { return err }\n\tmodel.CheckSetup()'),
 ("model/model_meta.go", 'switch mi.NameRule {', 'owner, public := common.ActveroSplitName(mi.ModelName)\n candidateOwner, candidate := common.ActveroSplitName(name)\n if owner != candidateOwner { return false }\n name = candidate\n switch mi.NameRule {'),
 ("model/model_meta.go", 'strings.HasPrefix(name, mi.ModelName)', 'strings.HasPrefix(name, public)'),
 ("model/model_meta.go", 'strings.HasSuffix(name, mi.ModelName)', 'strings.HasSuffix(name, public)'),
 ("model/model_meta.go", 'strings.Contains(name, mi.ModelName)', 'strings.Contains(name, public)'),
 ("model/model_meta.go", 'return name == mi.ModelName', 'return name == public'),
 ("model/model_meta.go", 'size:128;not null;uniqueIndex:uk_model_name', 'size:256;not null;uniqueIndex:uk_model_name'),
 ("model/vendor_meta.go", 'size:128;not null;uniqueIndex:uk_vendor_name', 'size:256;not null;uniqueIndex:uk_vendor_name'),
 ("model/prefill_group.go", 'size:64;not null;uniqueIndex:uk_prefill_name', 'size:256;not null;uniqueIndex:uk_prefill_name'),
 ("model/model_pricing_config.go", 'pricing = modelPricingValues(defaults, change.ModelName)', 'pricing = ActveroDefaultModelPricing(defaults, change.ModelName)'),
 ("controller/model_sync.go", 'encoded, err := common.Marshal([]any{source.Locale, models, vendors})', 'if prefix := c.GetString("actvero_prefix"); prefix != "" {\n scopedModels := make(map[string]model.MetadataValues); scopedVendors := make(map[string]model.Vendor)\n for name, value := range models { if value.Vendor != "" {value.Vendor=prefix+value.Vendor}; scopedModels[prefix+name]=value }\n for name, value := range vendors {value.Name=prefix+value.Name;scopedVendors[prefix+name]=value}\n models,vendors=scopedModels,scopedVendors\n }\n encoded, err := common.Marshal([]any{source.Locale, models, vendors})'),
 ("controller/model_sync.go", 'siteNames := make(map[string]bool)', 'if prefix := c.GetString("actvero_prefix"); prefix != "" {\n for name := range locals {if !strings.HasPrefix(name,prefix){delete(locals,name)}}\n for name := range vendors {if !strings.HasPrefix(name,prefix){delete(vendors,name)}}\n scoped := []string{}; for _,name:=range missing{if strings.HasPrefix(name,prefix){scoped=append(scoped,name)}};missing=scoped\n }\n siteNames := make(map[string]bool)'),
 ("controller/ratio_sync.go", 'localData := effectivePricingSyncData(getLocalPricingSyncData())', 'localData := effectivePricingSyncData(getLocalPricingSyncData())\n if prefix:=c.GetString("actvero_prefix");prefix!=""{localData=actveroPricingSyncData(prefix,localData,false)}'),
 ("controller/ratio_sync.go", 'data: effectivePricingSyncData(r.Data)', 'data: actveroPricingSyncData(c.GetString("actvero_prefix"),effectivePricingSyncData(r.Data),true)'),
]
for relative, old, new in patches:
 path=root/relative
 text=path.read_text()
 if new in text or "".join(new.split()) in "".join(text.split()): continue
 if text.count(old)!=1: raise RuntimeError(f"Pinned upstream contract changed: {relative}: {old[:60]}")
 path.write_text(text.replace(old,new))
# Namespace length is internal; retain native public name limits.
path=root/"model/vendor_management.go"
text=path.read_text().replace('utf8.RuneCountInString(vendor.Name) > 128', 'utf8.RuneCountInString(strings.TrimPrefix(vendor.Name, func() string {p,_:=common.ActveroSplitName(vendor.Name);return p}())) > 128')
path.write_text(text)
for relative in ("model/channel.go","model/ability.go","model/user.go","model/token.go"):
 path=root/relative
 text=path.read_text()
 lines=text.splitlines(keepends=True)
 for i,line in enumerate(lines):
  if 'Group ' in line and ('varchar(64)' in line or 'varchar(256)' in line):
   lines[i]=line.replace('varchar(64)','varchar(256)')
   if relative == 'model/channel.go': lines[i]=lines[i].replace('varchar(256)','text')
 path.write_text(''.join(lines))
