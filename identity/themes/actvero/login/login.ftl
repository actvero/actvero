<#import "template.ftl" as layout>
<#import "icons.ftl" as icons>
<#assign reauthentication = auth?has_content && auth.showUsername() && !auth.showResetCredentials()>
<@layout.registrationLayout reauthentication=reauthentication displayMessage=!messagesPerField.existsError('username','password'); section>
<#if section == "header"><#if reauthentication>重新登录<#else>登录 ${realm.displayName}</#if>
<#elseif section == "form">
<form id="kc-form-login" data-actvero-client="${client.clientId}" action="${url.loginAction}" method="post" class="flex flex-col gap-5">
<#if !usernameHidden??>
<div class="flex flex-col gap-2">
<label for="username" class="${properties.kcLabelClass}">邮箱</label>
<input id="username" name="username" type="text" autocomplete="username" autofocus required value="${(login.username!'')}" class="${properties.kcInputClass}" aria-invalid="${messagesPerField.existsError('username','password')?c}" <#if messagesPerField.existsError('username','password')>aria-describedby="login-error"</#if> />
</div>
</#if>
<div class="flex flex-col gap-2">
<div class="flex items-center justify-between gap-4"><label for="password" class="${properties.kcLabelClass}">密码</label><#if realm.resetPasswordAllowed><a class="text-sm text-muted-foreground underline-offset-4 hover:underline" href="${url.loginResetCredentialsUrl}">忘记密码？</a></#if></div>
<div class="relative rounded-md">
<input id="password" name="password" type="password" autocomplete="current-password" required <#if usernameHidden??>autofocus</#if> class="${properties.kcInputClass} pe-10" aria-invalid="${messagesPerField.existsError('username','password')?c}" <#if messagesPerField.existsError('username','password')>aria-describedby="login-error"</#if> />
<button type="button" class="${properties.kcPasswordToggleClass}" data-actvero-password="password" aria-label="${msg('showPassword')}" aria-controls="password" data-show-label="${msg('showPassword')}" data-hide-label="${msg('hidePassword')}"><span data-eye hidden><@icons.eye/></span><span data-eye-off><@icons.eyeOff/></span></button>
</div>
</div>
<#if messagesPerField.existsError('username','password')><p id="login-error" role="alert" class="${properties.kcInputErrorMessageClass}">${kcSanitize(messagesPerField.getFirstError('username','password'))?no_esc}</p></#if>
<input type="hidden" name="credentialId" <#if auth.selectedCredential?has_content>value="${auth.selectedCredential}"</#if> />
<button id="kc-login" type="submit" class="${properties.kcButtonClass} w-full">登录</button>
</form>
</#if>
</@layout.registrationLayout>
