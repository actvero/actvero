<#import "icons.ftl" as icons>
<#macro password id name label errorField>
<div class="${properties.kcFormGroupClass}">
<label for="${id}" class="${properties.kcLabelClass}">${label}</label>
<div class="relative rounded-md">
<input class="${properties.kcInputClass} pe-10" type="password" id="${id}" name="${name}" required autocomplete="new-password" aria-invalid="${messagesPerField.existsError(errorField)?c}" <#if messagesPerField.existsError(errorField)>aria-describedby="${id}-error"</#if> />
<button type="button" class="${properties.kcPasswordToggleClass}" data-actvero-password="${id}" aria-label="${msg('showPassword')}" aria-controls="${id}" data-show-label="${msg('showPassword')}" data-hide-label="${msg('hidePassword')}"><span data-eye hidden><@icons.eye/></span><span data-eye-off><@icons.eyeOff/></span></button>
</div>
<#if messagesPerField.existsError(errorField)><p id="${id}-error" class="${properties.kcInputErrorMessageClass}" role="alert">${kcSanitize(messagesPerField.get(errorField))?no_esc}</p></#if>
</div>
</#macro>
<#macro logoutOtherSessions>
<label class="flex items-center gap-2 text-sm" for="logout-sessions">
<span class="relative inline-flex items-center justify-center"><input class="${properties.kcCheckboxClass}" type="checkbox" id="logout-sessions" name="logout-sessions" value="on" /><span class="pointer-events-none absolute hidden text-primary-foreground peer-checked:block"><@icons.check/></span></span>
${msg('logoutOtherSessions')}
</label>
</#macro>
