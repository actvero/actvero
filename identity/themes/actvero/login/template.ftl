<#import "icons.ftl" as icons>
<#macro registrationLayout bodyClass="" displayInfo=false displayMessage=true displayRequiredFields=false displayWide=false reauthentication=false>
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" /><meta name="viewport" content="width=device-width, initial-scale=1" />
<title>${realm.displayName}</title>
<link rel="icon" href="${(realm.attributes.actveroBrandFavicon)!"${url.resourcesPath}/img/favicon.ico"}" sizes="any" />
<link rel="apple-touch-icon" href="${(realm.attributes.actveroBrandAppleIcon)!"${url.resourcesPath}/img/actvero-icon.png"}" />
<link rel="stylesheet" href="${url.resourcesPath}/css/generated.css?v=${properties.actveroThemeVersion!'1'}" />
<script src="${url.resourcesPath}/js/actvero.js?v=${properties.actveroThemeVersion!'1'}" defer></script>
</head>
<body class="bg-background text-foreground">
<main class="flex min-h-svh items-center justify-center p-4 sm:p-8">
<div class="flex w-full max-w-md flex-col gap-6">
<#assign brand=(realm.attributes)!{}>
<#assign wordmark=(brand.actveroBrand_wordmark_light)!"">
<#assign wordmarkDark=(brand.actveroBrand_wordmark_dark)!wordmark>
<#if !wordmarkDark?has_content><#assign wordmarkDark=wordmark></#if>
<#assign mark=(brand.actveroBrand_mark_light)!"">
<#assign markDark=(brand.actveroBrand_mark_dark)!mark>
<#if !markDark?has_content><#assign markDark=mark></#if>
<div class="flex items-center justify-center gap-2" aria-label="${realm.displayName}">
<#if wordmark?has_content>
<img src="${wordmark}" alt="${realm.displayName}" class="max-h-14 max-w-64 object-contain dark:hidden" />
<span class="hidden dark:inline-flex <#if !(brand.actveroBrand_wordmark_dark!"")?has_content>brand-artwork-backed rounded-sm</#if>"><img src="${wordmarkDark}" alt="${realm.displayName}" class="max-h-14 max-w-64 object-contain" /></span>
<#else>
<#if mark?has_content><img src="${mark}" alt="" class="size-8 object-contain dark:hidden" /><span class="hidden dark:inline-flex <#if !(brand.actveroBrand_mark_dark!"")?has_content>brand-artwork-backed rounded-sm</#if>"><img src="${markDark}" alt="" class="size-8 object-contain" /></span><#else><@icons.logo/></#if>
<span class="text-xl font-medium">${realm.displayName}</span>
</#if>
</div>
<div class="${properties.kcCardClass}">
<header class="grid gap-2 px-6"><h1 id="kc-page-title" class="font-semibold leading-none"><#nested "header"></h1><#if reauthentication><p class="text-sm text-muted-foreground">请验证密码后继续。</p></#if></header>
<div class="flex flex-col gap-5 px-6">
<#if displayMessage && message?has_content && !(reauthentication && message.summary == msg('reauthenticate'))>
<div role="alert" class="relative w-full rounded-lg border px-4 py-3 text-sm <#if message.type == 'error'>text-destructive</#if>">${kcSanitize(message.summary)?no_esc}</div>
</#if>
<#if auth?has_content && auth.showUsername() && !auth.showResetCredentials()>
<div class="${properties.kcAccountCardClass}">
<div class="flex items-center gap-3 px-4">
<div class="flex size-10 shrink-0 items-center justify-center rounded-full bg-muted"><@icons.user/></div>
<div class="grid min-w-0 flex-1 gap-1"><span class="text-sm text-muted-foreground">当前账号</span><span class="truncate text-sm font-medium" title="${auth.attemptedUsername}">${auth.attemptedUsername}</span></div>
<a id="reset-login" class="shrink-0 text-sm underline-offset-4 hover:underline focus-visible:outline-ring" href="${url.loginRestartFlowUrl}">切换账号</a>
</div>
</div>
</#if>
<#nested "form">
<#if displayInfo><div class="text-sm text-muted-foreground"><#nested "info"></div></#if>
<#nested "socialProviders">
</div>
</div>
</div>
</main>
</body>
</html>
</#macro>
