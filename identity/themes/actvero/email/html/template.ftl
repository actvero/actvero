<#macro emailLayout>
<!DOCTYPE html><html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:32px;font-family:Arial,sans-serif">
<table role="presentation" width="100%"><tr><td align="center"><table role="presentation" width="100%" style="max-width:560px"><tr><td>
<#if (properties.brandBaseUrl!"")?has_content><img src="${properties.brandBaseUrl}/api/v1/platform/branding/email-logo.png" alt="${realmName}" style="max-width:240px;max-height:56px;width:auto;height:auto"><#else><h2>${realmName}</h2></#if>
<#nested>
<p>${realmName}</p>
</td></tr></table></td></tr></table></body></html>
</#macro>
