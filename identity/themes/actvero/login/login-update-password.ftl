<#import "template.ftl" as layout>
<#import "controls.ftl" as controls>
<@layout.registrationLayout displayMessage=!messagesPerField.existsError('password','password-confirm'); section>
<#if section == "header">${msg('updatePasswordTitle')}
<#elseif section == "form">
<form id="kc-passwd-update-form" class="${properties.kcFormClass}" action="${url.loginAction}" method="post">
<@controls.password id="password-new" name="password-new" label=msg('passwordNew') errorField="password"/>
<@controls.password id="password-confirm" name="password-confirm" label=msg('passwordConfirm') errorField="password-confirm"/>
<@controls.logoutOtherSessions/>
<div class="flex flex-col gap-2 pt-2">
<input name="login" class="${properties.kcButtonClass} w-full" type="submit" value="${msg('doSubmit')}" />
<#if isAppInitiatedAction??><button class="${properties.kcSecondaryButtonClass}" type="submit" name="cancel-aia" value="true" formnovalidate>${msg('doCancel')}</button></#if>
</div>
</form>
</#if>
</@layout.registrationLayout>
